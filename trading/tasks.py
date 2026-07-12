from celery import shared_task, chord
from celery.result import allow_join_result
from time import sleep
from decimal import Decimal, ROUND_HALF_UP
import numpy as np
import random
import json
import threading
import uuid
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from .models import Configuration, DataLog, BacktestTask
from .backtesting import Backtesting
import logging

logger = logging.getLogger(__name__)


class _EagerAsyncResultStub:
    """Minimales Ersatz-Objekt fuer AsyncResult im Free-Tier Fallback.

    Bietet nur das .id Attribut, das der aufrufende Code (views.py) in
    BacktestTask.celery_task_id speichert. AsyncResult(diese_id) liefert
    spaeter naturgemaess PENDING zurueck, da kein Broker/Backend involviert
    ist - Pause/Cancel ueber Celery-Revoke funktioniert daher im Fallback-
    Modus nicht (siehe README/Deployment-Doku).
    """
    def __init__(self, task_id):
        self.id = task_id


def dispatch_task(task, *args, **kwargs):
    """Startet einen Celery-Task, Render-Free-Tier-kompatibel.

    - Ist ein echter Broker konfiguriert (REDIS_URL gesetzt, z.B. auf einem
      bezahlten Plan mit Redis/Key-Value + separatem Worker-Service):
      normales verteiltes .delay().
    - Ohne Broker (Render Free Tier, CELERY_TASK_ALWAYS_EAGER=True):
      .delay() wuerde synchron *im selben Thread* laufen und damit die
      HTTP-Antwort blockieren (bei einer Kombinationsexplosion von
      Backtest-Parametern potenziell fuer Minuten). Stattdessen wird der
      Task hier in einem Hintergrund-Thread desselben Prozesses ausgefuehrt -
      kein Broker/Worker noetig, blockiert aber den Request nicht.
    """
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        synthetic_id = f"eager-{uuid.uuid4()}"

        def _run():
            try:
                task.apply(args=args, kwargs=kwargs, task_id=synthetic_id, throw=True)
            except Exception:
                logger.exception(
                    "Fehler bei Hintergrund-Ausfuehrung von %s (Free-Tier Fallback ohne Broker)",
                    getattr(task, "name", task),
                )

        threading.Thread(
            target=_run, daemon=True, name=f"task-{getattr(task, 'name', 'unknown')}"
        ).start()
        return _EagerAsyncResultStub(synthetic_id)

    return task.delay(*args, **kwargs)

def decimal_to_str(obj):
    """Konvertiert Decimal-Objekte rekursiv in Strings."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: decimal_to_str(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [decimal_to_str(elem) for elem in obj]
    return obj

@shared_task(bind=True)
def simulate_candidate(self, config_id, params, symbol, task_id, acc_threshold, nda_threshold, deltadelta_threshold):
    """Führt die Backtest-Simulation für einen Schwellenwert-Kandidaten durch."""
    try:
        config = Configuration.objects.get(id=config_id)
        # Optimierung: Preise einmalig abrufen
        historical_prices = [log.price for log in DataLog.objects.filter(
            configuration=config, symbol=symbol).order_by('timestamp')]
        if not historical_prices:
            return {'symbol': symbol, 'error': f"Keine historischen Preise für {symbol} gefunden."}

        prices_decimal = [Decimal(str(p)) for p in historical_prices]
        simulation_params = {
            'start_capital': config.start_capital,
            'trade_amount': config.trade_amount,
            'take_profit': config.take_profit,
            'fee_percentage': config.fee  # Konsistenz: fee in Prozent
        }

        final_capital, report = Backtesting.simulate_trading_detailed(
            prices_decimal, acc_threshold, nda_threshold, deltadelta_threshold, simulation_params
        )

        return {
            'symbol': symbol,
            'thresholds': {
                'acc_threshold': acc_threshold,
                'nda_threshold': nda_threshold,
                'deltadelta_threshold': deltadelta_threshold
            },
            'final_capital': final_capital,
            'report': report,
            'params': params
        }
    except Exception as e:
        logger.error(f"Fehler bei Simulation für {symbol} (Task {task_id}): {e}", exc_info=True)
        return {'symbol': symbol, 'error': f"Simulationsfehler für {symbol}: {e}"}
        
@shared_task
def collect_results(results, task_id):
    """Sammelt Simulationergebnisse und findet beste Schwellenwerte pro Symbol."""
    task = BacktestTask.objects.get(id=task_id)
    symbol_results = {}

    if not results or not isinstance(results, list):
        logger.error(f"Ungültige Ergebnisse für Task {task_id}: {results}")
        task.status = 'failed'
        task.result = {'error': 'Ungültige oder leere Ergebnisse'}
        task.save()
        return

    # Ergebnisse pro Symbol sammeln
    for result in results:
        if isinstance(result, dict) and 'symbol' in result and 'final_capital' in result:
            symbol = result['symbol']
            if symbol not in symbol_results:
                symbol_results[symbol] = []
            symbol_results[symbol].append(result)

    # Beste Schwellenwerte pro Symbol ermitteln
    processed_symbol_results = {}
    for symbol, sym_results in symbol_results.items():
        best_capital = Decimal('-Infinity')
        best_thresholds = None
        best_report = None
        for result in sym_results:
            if result['final_capital'] > best_capital:
                best_capital = result['final_capital']
                best_thresholds = result['thresholds']
                best_report = result['report']
        processed_symbol_results[symbol] = {
            'best_capital': decimal_to_str(best_capital),
            'best_thresholds': decimal_to_str(best_thresholds),
            'report': decimal_to_str(best_report),
            'optimized_thresholds_str': ', '.join([f"{k.split('_')[0]}: {v}" for k, v in best_thresholds.items()]) if best_thresholds else "Keine optimierten Schwellenwerte"
        }

    task.result = {'symbol_results': processed_symbol_results}
    task.status = 'completed'
    task.save()
    return task.result

@shared_task
def run_backtest(config_id, params, symbols, task_id):
    """Startet den Backtest-Prozess."""
    try:
        task = BacktestTask.objects.get(id=task_id)
    except BacktestTask.DoesNotExist:
        logger.error(f"Task {task_id} nicht gefunden.")
        return {'error': f"Task {task_id} nicht gefunden"}
    if not task:
        logger.error(f"Task {task_id} nicht gefunden.")
        return {'error': f"Task {task_id} nicht gefunden"}

    task.status = 'running'
    task.save()

    acc_range = np.arange(params['acc_from'], params['acc_to'] + params['acc_steps']/2, params['acc_steps'])
    nda_range = np.arange(params['nda_from'], params['nda_to'] + params['nda_steps']/2, params['nda_steps'])
    deltadelta_range = np.arange(params['deltadelta_from'], params['deltadelta_to'] + params['deltadelta_steps']/2, params['deltadelta_steps'])

    tasks = []
    total_combinations = len(acc_range) * len(nda_range) * len(deltadelta_range) * len(symbols)
    combination_count = 0

    for symbol in symbols:
        for acc_threshold in acc_range:
            for nda_threshold in nda_range:
                for deltadelta_threshold in deltadelta_range:
                    combination_count += 1
                    if combination_count % 100 == 0:  # Effizientere Aktualisierung
                        progress_percentage = (combination_count / total_combinations) * 100
                        task.update_progress(int(progress_percentage))
                    tasks.append(simulate_candidate.s(config_id, params, symbol, task_id, float(acc_threshold), float(nda_threshold), float(deltadelta_threshold)))

    callback = collect_results.s(task_id=task_id)
    final_chord = chord(tasks)(callback)
    return final_chord

@shared_task
def schedule_backtests():
    now = timezone.now()
    logger.info(f"schedule_backtests gestartet. Aktuelle Zeit: {now}")
    scheduled_tasks = BacktestTask.objects.filter(
        status='scheduled',
        scheduled_start_time__lte=now
    )
    logger.info(f"Anzahl geplanter Tasks gefunden: {scheduled_tasks.count()}")

    for task in scheduled_tasks:
        logger.info(f"Verarbeite geplanten Task ID: {task.id}, Startzeit: {task.scheduled_start_time}")
        symbols_str = task.symbol
        symbols = [symbol.strip() for symbol in symbols_str.split(',')]
        params = task.parameters
        task_id = task.id

        logger.info(f"Starte Task {task_id} mit run_backtest. Symbole: {symbols}, Parameter: {params}")
        celery_task = dispatch_task(run_backtest, task.configuration_id, params, symbols, task_id)
        logger.info(f"run_backtest dispatcht. Task ID: {celery_task.id}") # Log der Task ID
        task.celery_task_id = celery_task.id
        task.status = 'pending'
        task.is_scheduled = False
        task.scheduled_start_time = None
        task.save()
        logger.info(f"Task {task_id} aktualisiert. Status: pending, Celery Task ID: {task.celery_task_id}")
    logger.info("schedule_backtests beendet.")

from decimal import Decimal, InvalidOperation
from django.conf import settings
from datetime import datetime, timedelta, date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.template.loader import render_to_string
from django.db.models import Sum, F, DecimalField, Max, Min
from .forms import RegistrationForm, LoginForm, ConfigurationForm, DashboardConfigurationForm, BacktestForm
from .models import Configuration, TradingLog, DataLog, BacktestTask
from .backtesting import Backtesting
from .tasks import run_backtest, dispatch_task
from channels.layers import get_channel_layer
from celery.result import AsyncResult
from celery import shared_task, Celery
from celery.schedules import crontab
from asgiref.sync import async_to_sync
import plotly.express as px
from .trading_bot import bot_manager
import logging
import numpy as np
from weasyprint import HTML
from collections import Counter
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import io
import asyncio
from io import BytesIO
import base64
import math

# Logging konfigurieren
logger = logging.getLogger(__name__)


def home(request):    
    return redirect('login')


def passphrase_gate_view(request):
    """Landingpage mit Disclaimer + Passphrase-Eingabe (siehe PassphraseGateMiddleware).

    Nach erfolgreicher Eingabe wird ein Session-Flag gesetzt, sodass die
    Passphrase pro Browser-Session nur einmal eingegeben werden muss.
    """
    # Bereits verifiziert -> direkt zur eigentlich gewuenschten Seite (oder Login)
    if request.session.get("passphrase_verified"):
        return redirect(request.GET.get("next") or "login")

    error = None
    next_url = request.POST.get("next") or request.GET.get("next") or ""

    if request.method == "POST":
        submitted = request.POST.get("passphrase", "")
        import secrets as _secrets
        if _secrets.compare_digest(submitted.strip(), str(settings.PASSPHRASE)):
            request.session["passphrase_verified"] = True
            return redirect(next_url or "login")
        else:
            error = "Falsche Passphrase. Zugang verweigert."

    return render(request, "trading/passphrase_gate.html", {"error": error, "next": next_url})


def register_view(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            try:
                user = form.save(commit=False)
                user.set_password(form.cleaned_data['password'])
                user.save()
                logger.debug("User registered: %s", user.username)
                return redirect('login')
            except Exception as e:
                logger.error("Registrierungsfehler: %s", e)
    else:
        form = RegistrationForm()
    return render(request, 'trading/register.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            try:
                username = form.cleaned_data['username']
                password = form.cleaned_data['password']
                user = authenticate(request, username=username, password=password)
                if user:
                    login(request, user)
                    logger.debug("User logged in: %s", user.username)
                    return redirect('dashboard')
                else:
                    logger.warning("Login fehlgeschlagen für: %s", username)
            except Exception as e:
                logger.error("Login-Fehler: %s", e)
    else:
        form = LoginForm()
    return render(request, 'trading/login.html', {'form': form})

def logout_view(request):
    logout(request)
    return redirect('login')

@login_required
def config_view(request):
    """
    Neue Konfiguration erstellen
    """
    try:
        if request.method == 'POST':
            form = ConfigurationForm(request.POST)
            if form.is_valid():
                config = form.save(commit=False)
                config.user = request.user
                if config.start_capital <= config.trade_amount:
                    form.add_error('trade_amount', "Trade amount muss kleiner als Startkapital sein.")
                    return render(request, 'trading/config_form.html', {'form': form})
                config.save()
                logger.debug("Configuration created: %s", config.id)
                return redirect('config_list')
        else:
            form = ConfigurationForm()
    except Exception as e:
        logger.error("Konfigurationsfehler: %s", e)
        form = ConfigurationForm()
    return render(request, 'trading/config_form.html', {'form': form})

@login_required
def config_list_view(request):
    """
    Liste aller Konfigurationen des Users; von hier aus können Konfigurationen geladen, bearbeitet,
    aktiviert, deaktiviert oder gelöscht werden.
    """
    try:
        configs = Configuration.objects.filter(user=request.user)
        return render(request, 'trading/config_list.html', {'configs': configs})
    except Exception as e:
        logger.error("Fehler beim Laden der Konfigurationen: %s", e)
        return render(request, 'trading/config_list.html', {'configs': []})

@login_required
def config_edit_view(request, config_id):
    # Hole die Konfiguration, die dem eingeloggten User gehört
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    if request.method == 'POST':
        # Das Formular mit den POST-Daten und der bestehenden Instanz initialisieren
        form = ConfigurationForm(request.POST, instance=config)
        if form.is_valid():
            form.save()  # Aktualisiert die Konfiguration in der Datenbank
            return redirect('config_list')  # Weiterleitung zur Übersicht der Konfigurationen
    else:
        # Formular mit den bestehenden Daten initialisieren
        form = ConfigurationForm(instance=config)
    return render(request, 'trading/config_edit.html', {'form': form, 'config': config})
    
@login_required
def config_activate(request, config_id):
    config = get_object_or_404(Configuration, id=config_id, user=request.user)

    # Bot nur starten, wenn er NICHT bereits laeuft (im echten, gemeinsamen
    # bot_manager-Singleton aus trading_bot.py - siehe Fehler "Bot: STOPPED"
    # im Debugging-Protokoll: es gab hier frueher ein zweites, komplett
    # unabhaengiges Status-Dict (trading/bot_manager.py), das nie aktualisiert
    # wurde. Das ist jetzt entfernt - Configuration.is_running (DB) und
    # bot_manager.is_running() (echter Thread) sind die einzigen beiden
    # Quellen der Wahrheit, und bot_status_api liest jetzt aus genau diesen.
    if not bot_manager.is_running(config.id):
        try:
            bot_manager.start_bot(config)
        except Exception as e:
            logger.exception("Bot-Start fuer Konfiguration %s fehlgeschlagen: %s", config.id, e)
            messages.error(
                request,
                f"Bot konnte nicht gestartet werden: {e}. "
                f"Bitte Exchange/Symbole in der Konfiguration pruefen."
            )
            return redirect('config_list')

    if not config.is_running:
        config.is_running = True
        config.save(update_fields=["is_running"])

    return redirect('config_list')

    
@login_required
def config_deactivate(request, config_id):
    config = get_object_or_404(Configuration, id=config_id, user=request.user)

    if bot_manager.is_running(config.id):
        bot_manager.stop_bot(config)

    if config.is_running:
        config.is_running = False
        config.save(update_fields=["is_running"])

    return redirect('config_list')


@login_required
def config_delete(request, config_id):
    """
    Löscht eine Konfiguration und alle zugehörigen Daten, nachdem der Benutzer dies bestätigt hat.
    """
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    if request.method == 'POST':
        config.delete()
        logger.debug("Configuration deleted: %s", config.id)
        return redirect('config_list')
    return render(request, 'trading/config_confirm_delete.html', {'config': config})


def calculate_performance_metrics(logs):
    """Berechnet detaillierte Performance-Metriken aus einer Liste von TradingLogs."""
    # Nur abgeschlossene Trades (Sells) für die Gewinnberechnung heranziehen
    sell_logs = [log for log in logs if log.action == 'sell']

    if not sell_logs:
        return {
            'win_rate': 0, 'avg_profit': 0, 'total_wins': 0, 'total_losses': 0,
            'risk_reward': 0, 'profit_factor': 0, 'max_win': 0, 'max_loss': 0,
            'avg_win': 0, 'avg_loss': 0
        }

    profits = [float(log.pl_nominal) for log in sell_logs]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]

    total_wins = len(wins)
    total_losses = len(losses)
    win_rate = (total_wins / len(profits) * 100) if profits else 0

    avg_win = (sum(wins) / total_wins) if wins else 0
    avg_loss = (sum(losses) / total_losses) if losses else 0

    # Profit Faktor: Bruttogewinn / Bruttoverlust
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss != 0 else (gross_profit if gross_profit > 0 else 0)

    # Risk/Reward Ratio (basierend auf Durchschnittswerten)
    rrr = (abs(avg_win / avg_loss)) if avg_loss != 0 else 0

    return {
        'win_rate': round(win_rate, 2),
        'avg_profit': round(sum(profits) / len(profits), 4) if profits else 0,
        'total_wins': total_wins,
        'total_losses': total_losses,
        'avg_win': round(avg_win, 4),
        'avg_loss': round(avg_loss, 4),
        'risk_reward': round(rrr, 2),
        'profit_factor': round(profit_factor, 2),
        'max_win': round(max(profits), 4) if profits else 0,
        'max_loss': round(min(profits), 4) if profits else 0,
    }


@login_required
def dashboard_info(request, config_id):
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    logs = TradingLog.objects.filter(configuration=config).order_by('timestamp')

    # Performance Metriken berechnen
    metrics = calculate_performance_metrics(logs)

    # Equity Curve Daten
    equity_curve = [float(config.start_capital)]
    current_equity = float(config.start_capital)
    equity_timestamps = [timezone.now().strftime("%H:%M:%S")] # Fallback Startzeit

    for log in logs:
        current_equity += float(log.pl_nominal or 0)
        equity_curve.append(current_equity)
        equity_timestamps.append(log.timestamp.strftime("%H:%M:%S"))

    # Letzte Logs für die Tabelle
    recent_logs_list = []
    for log in logs.order_by('-timestamp')[:10]:
        recent_logs_list.append({
            'timestamp': log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            'symbol': log.symbol,
            'action': log.action,
            'price': str(log.price),
            'amount': str(log.amount),
            'pl_nominal': str(log.pl_nominal) if log.pl_nominal else "0.00"
        })

    data = {
        'recent_logs': recent_logs_list,
        'equity_curve': equity_curve,
        'equity_timestamps': equity_timestamps,
        'metrics': metrics,  # Metriken zum JSON hinzufügen
        'current_capital': str(round(current_equity, 2)),
    }
    return JsonResponse(data)

@login_required
def dashboard_view(request):
    """
    Zeigt das Dashboard an. Der Benutzer kann über einen GET-Parameter config_id zwischen
    verschiedenen Konfigurationen wechseln. Zusätzlich wird geprüft, ob die Konfiguration
    als aktiv (is_running=True) markiert ist – wenn ja, wird der Bot gestartet.
    """
    config_id = request.GET.get('config_id')
    if config_id:
        config = get_object_or_404(Configuration, id=config_id, user=request.user)
    else:
        config = Configuration.objects.filter(user=request.user).order_by('-id').first()

    
    if request.method == 'POST':
        form = DashboardConfigurationForm(request.POST, instance=config)  # Verwende das neue Formular
        if form.is_valid():
            form.save()
            logger.debug("Dashboard Configuration updated from dashboard: %s", config.id)
            return redirect('dashboard')  # Refresh the dashboard
        else:
            logger.warning("Dashboard Configuration update from dashboard failed: %s", form.errors)
    else:
        form = DashboardConfigurationForm(instance=config)  # Verwende das neue Formular

    context = {'config': config, 'form': form}
    
    if config:
        logs = config.logs.all()
        total_pl = sum((log.pl_nominal for log in logs), Decimal('0.0'))
        # Anzahl der profitablen und unprofitablen Verkäufe zählen
        profitable_sells = logs.filter(action='sell', pl_nominal__gt=0).count()
        unprofitable_sells = logs.filter(action='sell', pl_nominal__lt=0).count()
        context.update({
            'logs': logs,
            'current_capital': config.start_capital + total_pl,
            'tank': total_pl,
            'buy_orders': logs.filter(action='buy').count(),
            'sell_orders': logs.filter(action='sell').count(),
            'profitable_sells': profitable_sells,
            'unprofitable_sells': unprofitable_sells,
            'symbols': [s.strip() for s in config.symbols.split(',')],
            'data_logs': {
                symbol: config.data_logs.filter(symbol=symbol).order_by('timestamp')
                for symbol in config.symbols.split(',')
            },
            # Zusätzlich alle Konfigurationen des Benutzers zur Navigation
            'all_configs': Configuration.objects.filter(user=request.user)
        })
    else:
        context.update({
            'current_capital': Decimal('0.0'),
            'tank': Decimal('0.0'),
            'buy_orders': 0,
            'sell_orders': 0,
            'symbols': [],
            'data_logs': {},
            'all_configs': []
        })
    return render(request, 'trading/dashboard.html', context)

@login_required
def reset_log(request, config_id):
    try:
        config = get_object_or_404(Configuration, id=config_id, user=request.user)
        config.logs.all().delete()
        logger.debug("Trading-Logbuch zurückgesetzt für Konfig: %s", config.id)
    except Exception as e:
        logger.error("Fehler beim Zurücksetzen des Logbuchs: %s", e)
    return redirect('dashboard')


@login_required
def data_logs_api(request):
    config_id = request.GET.get('config_id')
    symbol = request.GET.get('symbol')
    try:
        config = Configuration.objects.get(id=config_id, user=request.user)
    except Configuration.DoesNotExist:
        return JsonResponse({"error": "Configuration not found"}, status=404)
    
    data_logs = config.data_logs.filter(symbol=symbol).order_by('timestamp')
    data = []
    for dl in data_logs:
        data.append({
            "timestamp": dl.timestamp.isoformat(),
            "price": dl.price,
            "deltadelta": dl.deltadelta if dl.deltadelta is not None else 0,
            "div_DVA_prev_NDA": dl.div_DVA_prev_NDA if dl.div_DVA_prev_NDA is not None else 0,
            "nda": dl.nda if dl.nda is not None else 0,
        })
    return JsonResponse(data, safe=False)

@login_required
def trades_api(request):
    config_id = request.GET.get('config_id')
    symbol = request.GET.get('symbol')
    try:
        config = Configuration.objects.get(id=config_id, user=request.user)
    except Configuration.DoesNotExist:
        return JsonResponse({"error": "Configuration not found"}, status=404)
    
    trades = TradingLog.objects.filter(configuration=config, symbol=symbol).order_by('timestamp')
    data = []
    for trade in trades:
        data.append({
            "timestamp": trade.timestamp.isoformat(),
            "action": trade.action,
            "price": float(trade.price),
        })
    return JsonResponse(data, safe=False)

@login_required
def info_api(request, config_id):
    logs = (
        TradingLog.objects
        .filter(configuration_id=config_id)
        .order_by("timestamp")
    )

    if not logs.exists():
        return JsonResponse({
            "equity": [],
            "sharpe": 0,
            "max_drawdown": 0
        })

    equity = []
    returns = []
    peak = None
    max_drawdown = Decimal("0")
    prev_capital = None

    for log in logs:
        cap = log.current_capital
        equity.append({
            "t": log.timestamp.isoformat(),
            "v": float(cap)
        })

        if prev_capital:
            r = (cap - prev_capital) / prev_capital
            returns.append(float(r))

        prev_capital = cap

        if peak is None or peak <= 0:
            drawdown = Decimal("0")
        else:
            drawdown = max(Decimal("0"), (peak - cap) / peak)

        if drawdown > max_drawdown:
            max_drawdown = drawdown

    # Sharpe Ratio
    if len(returns) > 1:
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(variance)
        sharpe = (mean / std) * math.sqrt(252) if std > 0 else 0
    else:
        sharpe = 0

    return JsonResponse({
        "equity": equity,
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(float(max_drawdown) * 100, 2)
    })

@login_required
def bot_status_api(request):
    config_id = request.GET.get('config_id')
    if not config_id:
        return JsonResponse({"error": "config_id fehlt"}, status=400)
    try:
        config = Configuration.objects.get(id=config_id, user=request.user)
    except Configuration.DoesNotExist:
        return JsonResponse({"error": "Configuration not found"}, status=404)

    status = bot_manager.status(config.id)
    # DB-Flag ergaenzen: is_running kann True sein, obwohl der Thread in
    # diesem Prozess (z.B. nach einem Render-Neustart) nicht mehr existiert -
    # das ist ein separates, sichtbares Signal fuer den Nutzer.
    status["is_running_flag"] = config.is_running
    return JsonResponse(status)

@login_required
def logs_api(request, config_id):
    """
    Returns all TradingLog entries for a configuration as JSON.
    """
    try:
        config = Configuration.objects.get(id=config_id, user=request.user)
    except Configuration.DoesNotExist:
        return JsonResponse({"error": "Configuration not found"}, status=404)
    
    logs = config.logs.all().order_by('timestamp')
    data = []
    for log in logs:
        data.append({
            "timestamp": log.timestamp.isoformat(),
            "date": log.timestamp.date().isoformat(),
            "time": log.timestamp.time().strftime("%H:%M:%S"),
            "symbol": log.symbol,
            "action": log.action,
            "price": float(log.price),
            "fee_amount": float(log.fee_amount) if log.fee_amount is not None else 0,
            "amount": float(log.amount) if log.amount is not None else 0,
            "order_id": log.order_id,
            "pl_nominal": float(log.pl_nominal) if log.pl_nominal is not None else 0,
            "pl_relative": float(log.pl_relative) if log.pl_relative is not None else 0,
            "total_pl": float(log.total_pl) if log.total_pl is not None else 0,
            "current_capital": float(log.current_capital) if log.current_capital is not None else 0,
            "tank": float(log.tank) if log.tank is not None else 0,
        })
    return JsonResponse(data, safe=False)

@login_required
def generate_report(request, config_id):
    """
    Generiert einen ausführlichen Trading-Analyse-Report als PDF für die gegebene Konfiguration.
    Der Report enthält allgemeine Statistiken, Tabellen, Charts (Häufigkeitsverteilung, Profitverlauf,
    Profitabilitätsübersicht) und weitere nützliche Kennzahlen.
    """
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    logs = config.logs.all().order_by('timestamp')
    total_trades = logs.count()
    buy_trades = logs.filter(action='buy').count()
    sell_trades = logs.filter(action='sell').count()
    total_profit = logs.filter(action='sell').aggregate(
        total_profit=Sum('pl_nominal', output_field=DecimalField())
    )['total_profit'] or Decimal('0.0')

    # Häufigkeitsverteilung der Symbole
    symbol_counts = dict(Counter(log.symbol for log in logs))

    # Erzeuge ein Balkendiagramm für die Trades pro Symbol
    fig, ax = plt.subplots(figsize=(6, 4))
    symbols_chart = list(symbol_counts.keys())
    counts = list(symbol_counts.values())
    ax.bar(symbols_chart, counts, color='skyblue')
    ax.set_title('Trades pro Symbol')
    ax.set_xlabel('Symbol')
    ax.set_ylabel('Anzahl Trades')
    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    bar_chart = base64.b64encode(buf.getvalue()).decode('utf-8')
    plt.close(fig)

    # Erzeuge ein Liniendiagramm für den kumulativen Profitverlauf (global)
    times = []
    profits = []
    cum_profit = Decimal('0.0')
    for log in logs:
        if log.action == 'sell':
            cum_profit += log.pl_nominal
        times.append(log.timestamp.strftime("%Y-%m-%d %H:%M"))
        profits.append(float(cum_profit))

    fig2, ax2 = plt.subplots(figsize=(8, 4))
    if times:  # nur plotten, wenn Daten vorhanden sind
        ax2.plot(times, profits, marker='o', linestyle='-', color='green')
    ax2.set_title('Kumulativer Profitverlauf')
    ax2.set_xlabel('Zeit')
    ax2.set_ylabel('Profit')
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    buf2 = BytesIO()
    plt.savefig(buf2, format='png')
    buf2.seek(0)
    profit_chart = base64.b64encode(buf2.getvalue()).decode('utf-8')
    plt.close(fig2)

    # Profit pro Symbol
    symbol_profits = logs.filter(action='sell').values('symbol').annotate(
        total_profit=Sum('pl_nominal', output_field=DecimalField())
    )
    symbol_profits_dict = {item['symbol']: item['total_profit'] for item in symbol_profits}

    # Erzeuge ein Balkendiagramm für den Profit pro Symbol
    fig3, ax3 = plt.subplots(figsize=(6, 4))
    symbols_profit_chart = list(symbol_profits_dict.keys())
    profits_symbol = list(symbol_profits_dict.values())
    ax3.bar(symbols_profit_chart, profits_symbol, color='lightgreen')
    ax3.set_title('Profit pro Symbol')
    ax3.set_xlabel('Symbol')
    ax3.set_ylabel('Profit')
    plt.tight_layout()
    buf3 = BytesIO()
    plt.savefig(buf3, format='png')
    buf3.seek(0)
    profit_symbol_chart = base64.b64encode(buf3.getvalue()).decode('utf-8')
    plt.close(fig3)

    # Profit pro Tag
    daily_profits = logs.filter(action='sell').values('timestamp__date').annotate(
        total_profit=Sum('pl_nominal', output_field=DecimalField())
    )
    daily_profits_dict = {}
    for item in daily_profits:
        date_obj = item['timestamp__date']
        if isinstance(date_obj, date):
            date_str = date_obj.strftime('%Y-%m-%d')
        else:
            date_str = str(date_obj)
        daily_profits_dict[date_str] = item['total_profit']

    # Erzeuge ein Balkendiagramm für den Profit pro Tag
    fig4, ax4 = plt.subplots(figsize=(8, 4))
    dates = list(daily_profits_dict.keys())
    profits_daily = list(daily_profits_dict.values())
    ax4.bar(dates, profits_daily, color='lightcoral')
    ax4.set_title('Profit pro Tag')
    ax4.set_xlabel('Datum')
    ax4.set_ylabel('Profit')
    ax4.xaxis.set_major_locator(MaxNLocator(nbins=10))
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    buf4 = BytesIO()
    plt.savefig(buf4, format='png')
    buf4.seek(0)
    profit_daily_chart = base64.b64encode(buf4.getvalue()).decode('utf-8')
    plt.close(fig4)

    # Ermittlung der profitablen und unprofitablen Trades (nur Sell-Trades)
    profitable_trades = logs.filter(action='sell', pl_nominal__gt=0).count()
    unprofitable_trades = logs.filter(action='sell', pl_nominal__lt=0).count()

    # Aufschlüsselung nach Symbol: profitable und unprofitable Trades
    symbol_profit_counts = {}
    for sym in symbol_counts.keys():
        profit_count = logs.filter(action='sell', symbol=sym, pl_nominal__gt=0).count()
        loss_count = logs.filter(action='sell', symbol=sym, pl_nominal__lt=0).count()
        symbol_profit_counts[sym] = {'profit': profit_count, 'loss': loss_count}

    # Erzeuge ein gruppiertes Balkendiagramm für die Profitabilitätsübersicht pro Symbol
    fig5, ax5 = plt.subplots(figsize=(8, 4))
    symbols = list(symbol_profit_counts.keys())
    profit_counts = [symbol_profit_counts[s]['profit'] for s in symbols]
    loss_counts = [symbol_profit_counts[s]['loss'] for s in symbols]
    bar_width = 0.35
    x = np.arange(len(symbols))
    ax5.bar(x - bar_width/2, profit_counts, width=bar_width, label='Profit Trades', color='green')
    ax5.bar(x + bar_width/2, loss_counts, width=bar_width, label='Loss Trades', color='red')
    ax5.set_xlabel('Symbol')
    ax5.set_ylabel('Anzahl Trades')
    ax5.set_title('Profitabilitätsübersicht pro Symbol')
    ax5.set_xticks(x)
    ax5.set_xticklabels(symbols)
    ax5.legend()
    plt.tight_layout()
    buf5 = BytesIO()
    plt.savefig(buf5, format='png')
    buf5.seek(0)
    profitability_chart = base64.b64encode(buf5.getvalue()).decode('utf-8')
    plt.close(fig5)

    # Laufzeiten pro Symbol (optional, falls im Template benötigt)
    symbols_list = [s.strip() for s in config.symbols.split(',') if s.strip()]
    symbol_times = {}
    for sym in symbols_list:
        sym_logs = logs.filter(symbol=sym).order_by('timestamp')
        if sym_logs.exists():
            start_time = sym_logs.first().timestamp.strftime("%Y-%m-%d %H:%M")
            end_time = sym_logs.last().timestamp.strftime("%Y-%m-%d %H:%M")
            symbol_times[sym] = f"{start_time}-{end_time}"
        else:
            symbol_times[sym] = "no_data"

    if times:
        global_time_range = f"{times[0]}-{times[-1]}"
    else:
        global_time_range = "no_data"

    context = {
        'config': config,
        'logs': logs,
        'total_trades': total_trades,
        'buy_trades': buy_trades,
        'sell_trades': sell_trades,
        'total_profit': total_profit,
        'symbol_counts': symbol_counts,
        'bar_chart': bar_chart,
        'profit_chart': profit_chart,
        'symbol_profits': symbol_profits_dict,
        'profit_symbol_chart': profit_symbol_chart,
        'daily_profits': daily_profits_dict,
        'profit_daily_chart': profit_daily_chart,
        'profitable_trades': profitable_trades,
        'unprofitable_trades': unprofitable_trades,
        'symbol_profit_counts': symbol_profit_counts,
        'profitability_chart': profitability_chart,
        'symbol_times': symbol_times,
    }
    html_string = render_to_string('trading/report.html', context)
    pdf = HTML(string=html_string).write_pdf()

    filename_symbol_times = "_".join([f"{sym}:{rng}" for sym, rng in symbol_times.items()])
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="trading_report-config_{config.id}-{filename_symbol_times}.pdf"'
    )
    return response
    
@login_required
def config_list(request):
    configs = Configuration.objects.filter(user=request.user).order_by('-id')
    return render(request, 'trading/config_list.html', {'configs': configs})

@login_required
def config_create(request):
    if request.method == 'POST':
        form = ConfigurationForm(request.POST)
        if form.is_valid():
            config = form.save(commit=False)
            config.user = request.user
            config.save()
            return redirect('config_detail', config_id=config.id)
    else:
        form = ConfigurationForm()
    return render(request, 'trading/config_form.html', {'form': form})

@login_required
def config_detail(request, config_id):
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    return render(request, 'trading/config_list.html', {'config': config})

@login_required
def config_update(request, config_id):
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    if request.method == 'POST':
        form = ConfigurationForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            return redirect('config_detail', config_id=config.id)
    else:
        form = ConfigurationForm(instance=config)
    return render(request, 'trading/config_form.html', {'form': form, 'update': True})

@login_required
def backtesting_form(request, config_id):
    """Zeigt das Backtest-Formular und Ergebnisse an, inklusive Scheduler."""
    config = get_object_or_404(Configuration, id=config_id, user=request.user)

    form = BacktestForm()
    tasks_running = BacktestTask.objects.filter(configuration=config, status__in=['pending', 'running', 'paused'])
    tasks_scheduled = BacktestTask.objects.filter(configuration=config, status='scheduled').order_by('scheduled_start_time') # Neu: Geplante Tasks
    tasks_completed = BacktestTask.objects.filter(configuration=config, status='completed').order_by('-completed_at')[:5]

    if request.method == 'POST':
        form = BacktestForm(request.POST)
        if form.is_valid():
            params = form.cleaned_data
            symbols_str = config.symbols
            symbols = [symbol.strip() for symbol in symbols_str.split(',')]

            schedule_backtest = params.pop('schedule_backtest', False) # Aus den Parametern entfernen, da es kein Backtest-Parameter ist
            scheduled_start_time = params.pop('scheduled_start_time', None) # Ebenso

            backtest_task = BacktestTask.objects.create(
                configuration=config, symbol=symbols_str, parameters=params, result={},
                is_scheduled=schedule_backtest, scheduled_start_time=scheduled_start_time,
            )

            if schedule_backtest and scheduled_start_time:
                backtest_task.status = 'scheduled' # Status auf 'scheduled' setzen
                backtest_task.save()
                # Keine Celery-Task-Ausführung hier, da sie geplant ist
            else:
                task_id = backtest_task.id
                celery_task = dispatch_task(run_backtest, config.id, params, symbols, task_id)
                backtest_task.celery_task_id = celery_task.id
                backtest_task.status = 'pending' # Status auf 'pending' für sofortige Ausführung
                backtest_task.save()

            return redirect('backtesting_form', config_id=config_id)

    plots = {}
    for task_completed in tasks_completed:
        if task_completed.result and 'symbol_results' in task_completed.result:
            plots[task_completed.id] = {}
            for symbol, result in task_completed.result['symbol_results'].items():
                if result and 'report' in result:
                    historical_prices = [log.price for log in DataLog.objects.filter(configuration=config, symbol=symbol).order_by('timestamp')]
                    if historical_prices:
                        plot_html = Backtesting.create_plot_for_symbol(historical_prices, result['report']).to_html(full_html=False, include_plotlyjs='cdn')
                        plots[task_completed.id][symbol] = plot_html

    context = {
        'config': config,
        'form': form,
        'tasks_running': tasks_running,
        'tasks_scheduled': tasks_scheduled, # Neu: Geplante Tasks
        'backtests': tasks_completed,
        'plots': plots
    }
    return render(request, 'trading/backtesting_form.html', context)


@login_required
def control_backtest(request, task_id):
    task = get_object_or_404(BacktestTask, id=task_id)
    action = request.POST.get('action')

    if task.status == 'scheduled' and action == 'cancel': # Abbrechen von geplanten Tasks
        task.status = 'cancelled'
        task.save()
        return redirect('backtesting_form', config_id=task.configuration_id)

    if task.celery_task_id:
        celery_task = AsyncResult(task.celery_task_id)

        if action == 'cancel':
            celery_task.revoke(terminate=True) # Abbruch des Celery Tasks
            task.status = 'cancelled'
            task.save()
        elif action == 'pause':
            task.pause() # Verwende die Model-Methode zum Pausieren
        elif action == 'resume':
            task.resume() # Verwende die Model-Methode zum Fortsetzen
        else:
            return JsonResponse({'status': 'error', 'message': 'Ungültige Aktion'})

        return redirect('backtesting_form', config_id=task.configuration_id)
    else:
        return JsonResponse({'status': 'error', 'message': 'Keine Celery Task ID gefunden'})


@login_required
def backtest_results(request, task_id):
    task = get_object_or_404(BacktestTask, id=task_id)
    if task.status == 'completed':
        return render(request, 'trading/backtest_results.html', {'task': task})
    else:
        return render(request, 'trading/backtesting_form.html', {'config_id': task.configuration_id, 'error': 'Backtest ist noch nicht abgeschlossen.'})


@login_required
def generate_backtest_pdf(request, task_id):
    # Backtest-Task abrufen
    task = get_object_or_404(BacktestTask, id=task_id)
    if task.status != 'completed':
        return HttpResponse("Backtest nicht verfügbar", status=400)

    # Plots und Daten vorbereiten
    plots = {}
    if task.result and 'symbol_results' in task.result and 'global_results' in task.result:
        global_results = task.result['global_results']
        symbol_results = task.result['symbol_results']

        # Trades pro Symbol (Balkendiagramm)
        trades_per_symbol = global_results.get('trades_per_symbol', {})
        fig = go.Figure([go.Bar(x=list(trades_per_symbol.keys()), y=list(trades_per_symbol.values()))])
        fig.update_layout(title='Trades pro Symbol')
        plots['trades_per_symbol'] = plot(fig, output_type='div', include_plotlyjs=False)

        # Kumulativer Profitverlauf (Liniendiagramm)
        cumulative_profit = global_results.get('cumulative_profit', [])
        fig = go.Figure([go.Scatter(y=cumulative_profit, mode='lines', name='Kumulativer Profit')])
        fig.update_layout(title='Kumulativer Profitverlauf')
        plots['cumulative_profit'] = plot(fig, output_type='div', include_plotlyjs=False)

        # Profit pro Symbol (Balkendiagramm)
        profit_per_symbol = global_results.get('profit_per_symbol', {})
        fig = go.Figure([go.Bar(x=list(profit_per_symbol.keys()), y=list(profit_per_symbol.values()))])
        fig.update_layout(title='Profit pro Symbol')
        plots['profit_per_symbol'] = plot(fig, output_type='div', include_plotlyjs=False)

        # Profit pro Tag (Balkendiagramm)
        profit_per_day = global_results.get('profit_per_day', {})
        fig = go.Figure([go.Bar(x=list(profit_per_day.keys()), y=list(profit_per_day.values()))])
        fig.update_layout(title='Profit pro Tag')
        plots['profit_per_day'] = plot(fig, output_type='div', include_plotlyjs=False)

        # Profitabilitätsübersicht pro Symbol (gruppiertes Balkendiagramm)
        profitable = global_results.get('profitable_trades_per_symbol', {})
        unprofitable = global_results.get('unprofitable_trades_per_symbol', {})
        symbols = list(profitable.keys())
        fig = go.Figure(data=[
            go.Bar(name='Profitable', x=symbols, y=[profitable.get(s, 0) for s in symbols]),
            go.Bar(name='Unprofitable', x=symbols, y=[unprofitable.get(s, 0) for s in symbols])
        ])
        fig.update_layout(barmode='group', title='Profitabilitätsübersicht pro Symbol')
        plots['profitability_per_symbol'] = plot(fig, output_type='div', include_plotlyjs=False)

        # Preisanalyse pro Symbol (bestehende Plots)
        plots[task.id] = {}
        for symbol, result in symbol_results.items():
            if result and 'report' in result:
                historical_prices = [log.price for log in DataLog.objects.filter(
                    configuration=task.configuration,
                    symbol=symbol
                ).order_by('timestamp')]
                if historical_prices:
                    # Hier wird angenommen, dass Backtesting.create_plot_for_symbol existiert
                    plot_html = Backtesting.create_plot_for_symbol(
                        historical_prices,
                        result['report']
                    ).to_html(full_html=False, include_plotlyjs='cdn')
                    plots[task.id][symbol] = plot_html

        # Win Rate berechnen
        for symbol, result in symbol_results.items():
            num_trades = result['report'].get('num_trades', 0)
            profitable = result['report'].get('profitable_trades', 0)
            result['report']['win_rate'] = (profitable / num_trades * 100) if num_trades > 0 else 0

    # Kontext für das Template
    context = {
        'task': task,
        'config': task.configuration,
        'plots': plots
    }
    html_string = render_to_string('trading/backtest_report.html', context)
    html = HTML(string=html_string)
    pdf = html.write_pdf()

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="backtest_report-tid_{task_id}-conf_{task.configuration}.pdf"'
    return response
# Celery Beat Scheduler Task (tasks.py):
@shared_task
def schedule_backtests():
    """
    Sucht nach geplanten Backtests, deren Startzeit erreicht ist, und startet sie.
    """
    now = timezone.now()
    scheduled_tasks = BacktestTask.objects.filter(
        status='scheduled',
        scheduled_start_time__lte=now
    )
    logger.info(f"Gefundene geplante Tasks: {scheduled_tasks.count()}") # Logging hinzugefügt

    for task in scheduled_tasks:
        symbols_str = task.symbol
        symbols = [symbol.strip() for symbol in symbols_str.split(',')]
        params = task.parameters
        task_id = task.id

        logger.info(f"Starte geplanten Task {task_id} für Symbole: {symbols}, Parameter: {params}") # Logging hinzugefügt

        celery_task = dispatch_task(run_backtest, task.configuration_id, params, symbols, task_id) # Hier run_backtest verwenden
        task.celery_task_id = celery_task.id
        task.status = 'pending' # Status auf 'pending' setzen, um die Ausführung zu starten
        task.is_scheduled = False # Nicht mehr geplant
        task.scheduled_start_time = None # Geplante Startzeit entfernen
        task.save()
        logger.info(f"Celery Task ID {celery_task.id} für geplanten Task {task_id} gestartet.") # Logging hinzugefügt


@login_required
def analyse_view(request):
    """
    Generiert eine Analyse-Seite mit Kauf- und Verkaufssignalen für ausgewählte Kryptowährungen.
    """
    symbols = request.GET.getlist('symbols')  # Nimmt eine Liste von Symbolen aus den GET-Parametern entgegen
    timeframe = request.GET.get('timeframe', '1h')  # Nimmt den gewählten Zeitrahmen aus den GET-Parametern entgegen, Standard ist '1h'

    if not symbols:
        return render(request, 'trading/analyse.html', {'error': 'Bitte wählen Sie mindestens ein Symbol aus.'})

    async def fetch_and_analyze(symbol, timeframe):
        exchange_id = 'binance'  # Hier kannst du die gewünschte Exchange festlegen
        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class()

        if not exchange.has['fetchOHLCV']:
            return {'symbol': symbol, 'error': f"Die Börse {exchange_id} unterstützt das Abrufen von OHLCV-Daten nicht."}

        try:
            # Definiere die Startzeit für die Datenabfrage (z.B. die letzten 30 Perioden)
            limit = 30
            now = datetime.now()
            timeframe_timedelta = exchange.parse_timeframe(timeframe)
            since = int((now - timedelta(seconds=limit * timeframe_timedelta)).timestamp() * 1000)

            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            if not ohlcv or len(ohlcv) < 2:
                return {'symbol': symbol, 'error': f"Nicht genügend Daten für {symbol} im Zeitraum {timeframe}."}

            # Implementiere hier deine Signallogik (Beispiel: Einfacher gleitender Durchschnitt Crossover)
            # Berechne zwei einfache gleitende Durchschnitte (SMA) mit unterschiedlichen Perioden
            short_period = 5
            long_period = 15

            closes = [candle[4] for candle in ohlcv]

            def calculate_sma(data, period):
                if len(data) < period:
                    return None
                return sum(data[-period:]) / period

            sma_short = calculate_sma(closes, short_period)
            sma_long = calculate_sma(closes, long_period)

            signal = 'Neutral'
            if len(closes) > long_period and sma_short and sma_long:
                previous_sma_short = calculate_sma(closes[-short_period-1:-1], short_period)
                previous_sma_long = calculate_sma(closes[-long_period-1:-1], long_period)

                if previous_sma_short < previous_sma_long and sma_short > sma_long:
                    signal = 'Kaufen'
                elif previous_sma_short > previous_sma_long and sma_short < sma_long:
                    signal = 'Verkaufen'

            return {'symbol': symbol, 'signal': signal}

        except ccxt.NetworkError as e:
            return {'symbol': symbol, 'error': f"Netzwerkfehler beim Abrufen von Daten für {symbol}: {e}"}
        except ccxt.ExchangeError as e:
            return {'symbol': symbol, 'error': f"Börsenfehler beim Abrufen von Daten für {symbol}: {e}"}
        except Exception as e:
            return {'symbol': symbol, 'error': f"Ein unerwarteter Fehler ist aufgetreten für {symbol}: {e}"}
        finally:
            await asyncio.sleep(exchange.rateLimit / 1000) # Respektiere die Rate Limits der Börse

    async def analyze_all():
        tasks = [fetch_and_analyze(symbol, timeframe) for symbol in symbols]
        results = await asyncio.gather(*tasks)
        return results

    analysis_results = async_to_sync(analyze_all)()

    context = {
        'analysis_results': analysis_results,
        'selected_symbols': symbols,
        'selected_timeframe': timeframe,
    }
    return render(request, 'trading/analyse.html', context)

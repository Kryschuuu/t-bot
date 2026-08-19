import asyncio
import base64
import logging
import math
import threading
from collections import Counter, defaultdict
from decimal import Decimal
from io import BytesIO

from asgiref.sync import async_to_sync
from celery.result import AsyncResult
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from .forms import (
    BacktestForm,
    ConfigurationForm,
    DashboardConfigurationForm,
    LoginForm,
    RegistrationForm,
)
from .models import BacktestTask, Configuration, ErrorLog
from .tasks import dispatch_task, local_task_is_active, run_backtest
from .trading_bot import bot_manager

logger = logging.getLogger(__name__)
_PLOT_LOCK = threading.Lock()
_MAX_API_ROWS = 5_000
_MAX_LOG_ROWS = 2_000
_MAX_TOTAL_BACKTEST_COMBINATIONS = 20_000


def _safe_next_url(request, candidate):
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return None


def _redirect_dashboard(config_id):
    return redirect(f"{reverse('dashboard')}?config_id={config_id}")


def _latest_rows(queryset, limit):
    rows = list(queryset.order_by("-timestamp", "-id")[:limit])
    rows.reverse()
    return rows


def _symbols(config):
    return [symbol.strip() for symbol in config.symbols.split(",") if symbol.strip()]


def _realized_profit(config):
    return config.logs.filter(action="sell").aggregate(total=Sum("pl_nominal"))["total"] or Decimal(
        0
    )


def _portfolio_series(config, logs, opening_profit=Decimal(0)):
    capital = config.start_capital + opening_profit
    equity = []
    for log in logs:
        if log.action == "sell":
            capital += log.pl_nominal
        equity.append({"t": log.timestamp.isoformat(), "v": float(capital)})
    return capital, equity


def calculate_performance_metrics(logs):
    sell_profits = [float(log.pl_nominal) for log in logs if log.action == "sell"]
    wins = [profit for profit in sell_profits if profit > 0]
    losses = [profit for profit in sell_profits if profit <= 0]
    average_win = sum(wins) / len(wins) if wins else 0
    average_loss = sum(losses) / len(losses) if losses else 0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "win_rate": round(len(wins) / len(sell_profits) * 100, 2) if sell_profits else 0,
        "avg_profit": round(sum(sell_profits) / len(sell_profits), 4) if sell_profits else 0,
        "total_wins": len(wins),
        "total_losses": len(losses),
        "avg_win": round(average_win, 4),
        "avg_loss": round(average_loss, 4),
        "risk_reward": round(average_win / abs(average_loss), 2) if average_loss else 0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else 0,
        "max_win": round(max(sell_profits), 4) if sell_profits else 0,
        "max_loss": round(min(sell_profits), 4) if sell_profits else 0,
    }


@require_GET
def health_view(request):
    return JsonResponse({"status": "ok"})


def home(request):
    return redirect("dashboard" if request.user.is_authenticated else "login")


def passphrase_gate_view(request):
    requested_next = request.POST.get("next") or request.GET.get("next")
    next_url = _safe_next_url(request, requested_next)
    if request.session.get("passphrase_verified"):
        return redirect(next_url or "login")

    error = None
    if request.method == "POST":
        import secrets

        submitted = request.POST.get("passphrase", "").strip()
        if secrets.compare_digest(submitted, str(settings.PASSPHRASE)):
            request.session.cycle_key()
            request.session["passphrase_verified"] = True
            return redirect(next_url or "login")
        error = "Falsche Passphrase. Zugang verweigert."
    return render(
        request,
        "trading/passphrase_gate.html",
        {"error": error, "next": next_url or ""},
    )


def register_view(request):
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        logger.info("Benutzer %s wurde registriert", user.username)
        messages.success(request, "Registrierung erfolgreich. Bitte jetzt anmelden.")
        return redirect("login")
    return render(request, "trading/register.html", {"form": form})


def login_view(request):
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = authenticate(
            request,
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password"],
        )
        if user is not None:
            login(request, user)
            next_url = _safe_next_url(
                request,
                request.POST.get("next") or request.GET.get("next"),
            )
            return redirect(next_url or "dashboard")
        form.add_error(None, "Benutzername oder Passwort ist falsch.")
    return render(request, "trading/login.html", {"form": form})


@login_required
@require_POST
def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def config_view(request):
    form = ConfigurationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        config = form.save(commit=False)
        config.user = request.user
        config.save()
        messages.success(request, "Konfiguration wurde erstellt.")
        return redirect("config_list")
    return render(request, "trading/config_form.html", {"form": form})


@login_required
def config_list_view(request):
    configs = Configuration.objects.filter(user=request.user).order_by("-id")
    return render(request, "trading/config_list.html", {"configs": configs})


@login_required
def config_edit_view(request, config_id):
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    form = ConfigurationForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        was_running = config.is_running
        config = form.save()
        if was_running:
            bot_manager.restart_bot(config)
        messages.success(request, "Konfiguration wurde aktualisiert.")
        return redirect("config_list")
    return render(
        request,
        "trading/config_edit.html",
        {"form": form, "config": config},
    )


@login_required
@require_POST
def config_activate(request, config_id):
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    try:
        bot_manager.start_bot(config)
    except Exception as exc:
        logger.exception("Bot-Start für Konfiguration %s fehlgeschlagen", config.id)
        ErrorLog.objects.create(
            configuration=config,
            source="views.config_activate",
            message=str(exc)[:4000],
        )
        messages.error(request, f"Bot konnte nicht gestartet werden: {exc}")
    else:
        if not config.is_running:
            config.is_running = True
            config.save(update_fields=["is_running"])
        messages.success(request, "Bot wurde aktiviert.")
    return redirect("config_list")


@login_required
@require_POST
def config_deactivate(request, config_id):
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    bot_manager.stop_bot(config)
    if config.is_running:
        config.is_running = False
        config.save(update_fields=["is_running"])
    messages.success(request, "Bot wurde deaktiviert.")
    return redirect("config_list")


@login_required
def config_delete(request, config_id):
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    if request.method == "POST":
        bot_manager.stop_bot(config)
        config.delete()
        messages.success(request, "Konfiguration wurde gelöscht.")
        return redirect("config_list")
    return render(
        request,
        "trading/config_confirm_delete.html",
        {"config": config},
    )


@login_required
def dashboard_view(request):
    config_id = request.GET.get("config_id")
    if config_id:
        config = get_object_or_404(Configuration, id=config_id, user=request.user)
    else:
        config = Configuration.objects.filter(user=request.user).order_by("-id").first()

    if not config:
        return render(
            request,
            "trading/dashboard.html",
            {"config": None, "all_configs": []},
        )

    form = DashboardConfigurationForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Strategieparameter wurden gespeichert.")
        return _redirect_dashboard(config.id)

    logs = _latest_rows(config.logs.all(), _MAX_LOG_ROWS)
    total_profit = _realized_profit(config)
    current_capital = config.start_capital + total_profit
    context = {
        "config": config,
        "form": form,
        "logs": logs[-500:],
        "current_capital": current_capital,
        "tank": total_profit,
        "buy_orders": sum(log.action == "buy" for log in logs),
        "sell_orders": sum(log.action == "sell" for log in logs),
        "profitable_sells": sum(log.action == "sell" and log.pl_nominal > 0 for log in logs),
        "unprofitable_sells": sum(log.action == "sell" and log.pl_nominal <= 0 for log in logs),
        "symbols": _symbols(config),
        "all_configs": Configuration.objects.filter(user=request.user).order_by("-id"),
    }
    return render(request, "trading/dashboard.html", context)


@login_required
@require_POST
def reset_log(request, config_id):
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    if config.is_running:
        bot_manager.restart_bot(config, before_start=lambda: config.logs.all().delete())
        messages.success(
            request,
            "Der Bot wird sauber neu gestartet; dabei werden Trading-Log und Portfolio zurückgesetzt.",
        )
    else:
        config.logs.all().delete()
        messages.success(request, "Trading-Log und simuliertes Portfolio wurden zurückgesetzt.")
    return _redirect_dashboard(config.id)


def _validated_start_time(request):
    raw = request.GET.get("start_time")
    if not raw:
        return None
    parsed = parse_datetime(raw)
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


@login_required
@require_GET
def data_logs_api(request):
    config = get_object_or_404(
        Configuration,
        id=request.GET.get("config_id"),
        user=request.user,
    )
    symbol = request.GET.get("symbol", "").strip()
    if symbol not in _symbols(config):
        return JsonResponse({"error": "Ungültiges Symbol"}, status=400)
    queryset = config.data_logs.filter(symbol=symbol)
    start_time = _validated_start_time(request)
    if start_time:
        queryset = queryset.filter(timestamp__gte=start_time)
    rows = _latest_rows(queryset, _MAX_API_ROWS)
    return JsonResponse(
        [
            {
                "timestamp": row.timestamp.isoformat(),
                "price": float(row.price),
                "deltadelta": float(row.deltadelta or 0),
                "div_DVA_prev_NDA": float(row.div_DVA_prev_NDA or 0),
                "nda": float(row.nda or 0),
            }
            for row in rows
        ],
        safe=False,
    )


@login_required
@require_GET
def trades_api(request):
    config = get_object_or_404(
        Configuration,
        id=request.GET.get("config_id"),
        user=request.user,
    )
    symbol = request.GET.get("symbol", "").strip()
    if symbol not in _symbols(config):
        return JsonResponse({"error": "Ungültiges Symbol"}, status=400)
    queryset = config.logs.filter(symbol=symbol)
    start_time = _validated_start_time(request)
    if start_time:
        queryset = queryset.filter(timestamp__gte=start_time)
    rows = _latest_rows(queryset, _MAX_API_ROWS)
    return JsonResponse(
        [
            {
                "timestamp": row.timestamp.isoformat(),
                "action": row.action,
                "price": float(row.price),
            }
            for row in rows
        ],
        safe=False,
    )


@login_required
@require_GET
def info_api(request, config_id):
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    logs = _latest_rows(config.logs.all(), _MAX_LOG_ROWS)
    total_profit = _realized_profit(config)
    window_profit = sum(
        (log.pl_nominal for log in logs if log.action == "sell"),
        Decimal(0),
    )
    current_capital, equity = _portfolio_series(
        config,
        logs,
        opening_profit=total_profit - window_profit,
    )
    metrics = calculate_performance_metrics(logs)

    peak = float(config.start_capital)
    max_drawdown = 0.0
    current_drawdown = 0.0
    sell_returns = []
    previous_capital = float(config.start_capital)
    for point, log in zip(equity, logs):
        capital = point["v"]
        peak = max(peak, capital)
        current_drawdown = (peak - capital) / peak if peak > 0 else 0
        max_drawdown = max(max_drawdown, current_drawdown)
        if log.action == "sell":
            sell_returns.append(
                (capital - previous_capital) / previous_capital if previous_capital else 0
            )
            previous_capital = capital

    if len(sell_returns) > 1:
        mean = sum(sell_returns) / len(sell_returns)
        variance = sum((value - mean) ** 2 for value in sell_returns) / (len(sell_returns) - 1)
        standard_deviation = math.sqrt(variance)
        sharpe = mean / standard_deviation * math.sqrt(252) if standard_deviation else 0
    else:
        sharpe = 0

    buy_orders = sum(log.action == "buy" for log in logs)
    sell_orders = sum(log.action == "sell" for log in logs)
    return JsonResponse(
        {
            "current_capital": float(current_capital),
            "tank": float(current_capital - config.start_capital),
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "profitable_sells": metrics["total_wins"],
            "unprofitable_sells": metrics["total_losses"],
            "win_rate": metrics["win_rate"],
            "avg_profit_trade": metrics["avg_profit"],
            "avg_win": metrics["avg_win"],
            "avg_loss": metrics["avg_loss"],
            "risk_reward": metrics["risk_reward"],
            "profit_factor": metrics["profit_factor"],
            "biggest_win": metrics["max_win"],
            "biggest_loss": metrics["max_loss"],
            "sharpe": round(sharpe, 3),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown": round(max_drawdown * 100, 2),
            "current_drawdown": round(current_drawdown * 100, 2),
            "equity": equity,
            "equity_timestamps": [point["t"] for point in equity],
            "equity_curve": [point["v"] for point in equity],
            "metrics": metrics,
        }
    )


@login_required
@require_GET
def bot_status_api(request):
    config_id = request.GET.get("config_id")
    if not config_id:
        return JsonResponse({"error": "config_id fehlt"}, status=400)
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    if config.is_running and not bot_manager.is_running(config.id):
        try:
            bot_manager.start_bot(config)
        except Exception as exc:
            logger.exception("Automatischer Neustart für %s fehlgeschlagen", config.id)
            ErrorLog.objects.create(
                configuration=config,
                source="views.bot_status_api",
                message=str(exc)[:4000],
            )
            config.is_running = False
            config.save(update_fields=["is_running"])
    status = bot_manager.status(config.id)
    status["is_running_flag"] = config.is_running
    return JsonResponse(status)


@login_required
@require_GET
def logs_api(request, config_id):
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    logs = _latest_rows(config.logs.all(), _MAX_LOG_ROWS)
    return JsonResponse(
        [
            {
                "id": log.id,
                "timestamp": log.timestamp.isoformat(),
                "date": timezone.localtime(log.timestamp).date().isoformat(),
                "time": timezone.localtime(log.timestamp).strftime("%H:%M:%S"),
                "symbol": log.symbol,
                "action": log.action,
                "price": float(log.price),
                "fee_amount": float(log.fee_amount),
                "amount": float(log.amount),
                "order_id": log.order_id,
                "pl_nominal": float(log.pl_nominal),
                "pl_relative": float(log.pl_relative),
                "total_pl": float(log.total_pl),
                "current_capital": float(log.current_capital),
                "tank": float(log.tank),
            }
            for log in logs
        ],
        safe=False,
    )


@login_required
@require_POST
def manual_sell_view(request, config_id):
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    symbol = request.POST.get("symbol", "").strip()
    if symbol not in _symbols(config):
        return JsonResponse({"status": "error", "message": "Ungültiges Symbol"}, status=400)
    try:
        bot_manager.manual_sell(config.id, symbol)
        return JsonResponse({"status": "ok"})
    except ValueError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("Manueller Verkauf für %s/%s fehlgeschlagen", config.id, symbol)
        ErrorLog.objects.create(
            configuration=config,
            source="views.manual_sell",
            message=str(exc)[:4000],
        )
        return JsonResponse(
            {"status": "error", "message": "Verkauf fehlgeschlagen."},
            status=500,
        )


@login_required
def error_log_view(request):
    errors = ErrorLog.objects.filter(configuration__user=request.user).select_related(
        "configuration"
    )[:300]
    return render(request, "trading/error_log.html", {"errors": errors})


def _figure_to_base64(figure, pyplot):
    buffer = BytesIO()
    figure.savefig(buffer, format="png", bbox_inches="tight")
    buffer.seek(0)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    pyplot.close(figure)
    return encoded


def _pdf_response(request, template, context, filename, disposition="attachment"):
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        logger.exception("PDF-Engine ist nicht verfügbar")
        return HttpResponse(f"PDF-Engine nicht verfügbar: {exc}", status=503)
    html_string = render_to_string(template, context, request=request)
    pdf = HTML(
        string=html_string,
        base_url=request.build_absolute_uri("/"),
    ).write_pdf()
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response


@login_required
@require_GET
def generate_report(request, config_id):
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    logs = list(config.logs.all().order_by("timestamp", "id"))
    sell_logs = [log for log in logs if log.action == "sell"]
    symbol_counts = Counter(log.symbol for log in logs)
    symbol_profits = defaultdict(Decimal)
    daily_profits = defaultdict(Decimal)
    symbol_profit_counts = defaultdict(lambda: {"profit": 0, "loss": 0})
    cumulative_profit = Decimal(0)
    profit_times = []
    cumulative_values = []
    for log in sell_logs:
        symbol_profits[log.symbol] += log.pl_nominal
        daily_profits[timezone.localtime(log.timestamp).date().isoformat()] += log.pl_nominal
        key = "profit" if log.pl_nominal > 0 else "loss"
        symbol_profit_counts[log.symbol][key] += 1
        cumulative_profit += log.pl_nominal
        profit_times.append(timezone.localtime(log.timestamp).strftime("%Y-%m-%d %H:%M"))
        cumulative_values.append(float(cumulative_profit))

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        logger.exception("Diagramm-Engine ist nicht verfügbar")
        return HttpResponse(f"Diagramm-Engine nicht verfügbar: {exc}", status=503)

    with _PLOT_LOCK:
        figure, axis = plt.subplots(figsize=(6, 4))
        axis.bar(list(symbol_counts), list(symbol_counts.values()), color="skyblue")
        axis.set_title("Trades pro Symbol")
        bar_chart = _figure_to_base64(figure, plt)

        figure, axis = plt.subplots(figsize=(8, 4))
        axis.plot(profit_times, cumulative_values, marker="o", color="green")
        axis.set_title("Kumulativer Profitverlauf")
        axis.tick_params(axis="x", rotation=45)
        profit_chart = _figure_to_base64(figure, plt)

        figure, axis = plt.subplots(figsize=(6, 4))
        axis.bar(
            list(symbol_profits),
            [float(value) for value in symbol_profits.values()],
            color="lightgreen",
        )
        axis.set_title("Profit pro Symbol")
        profit_symbol_chart = _figure_to_base64(figure, plt)

        figure, axis = plt.subplots(figsize=(8, 4))
        axis.bar(
            list(daily_profits),
            [float(value) for value in daily_profits.values()],
            color="lightcoral",
        )
        axis.set_title("Profit pro Tag")
        axis.tick_params(axis="x", rotation=45)
        profit_daily_chart = _figure_to_base64(figure, plt)

        chart_symbols = list(symbol_profit_counts)
        positions = list(range(len(chart_symbols)))
        figure, axis = plt.subplots(figsize=(8, 4))
        axis.bar(
            [position - 0.2 for position in positions],
            [symbol_profit_counts[symbol]["profit"] for symbol in chart_symbols],
            width=0.4,
            label="Profitabel",
            color="green",
        )
        axis.bar(
            [position + 0.2 for position in positions],
            [symbol_profit_counts[symbol]["loss"] for symbol in chart_symbols],
            width=0.4,
            label="Verlust",
            color="red",
        )
        axis.set_xticks(positions, chart_symbols)
        axis.legend()
        profitability_chart = _figure_to_base64(figure, plt)

    context = {
        "config": config,
        "logs": logs,
        "total_trades": len(logs),
        "buy_trades": sum(log.action == "buy" for log in logs),
        "sell_trades": len(sell_logs),
        "total_profit": cumulative_profit,
        "symbol_counts": dict(symbol_counts),
        "bar_chart": bar_chart,
        "profit_chart": profit_chart,
        "symbol_profits": dict(symbol_profits),
        "profit_symbol_chart": profit_symbol_chart,
        "daily_profits": dict(daily_profits),
        "profit_daily_chart": profit_daily_chart,
        "profitable_trades": sum(log.pl_nominal > 0 for log in sell_logs),
        "unprofitable_trades": sum(log.pl_nominal <= 0 for log in sell_logs),
        "symbol_profit_counts": dict(symbol_profit_counts),
        "profitability_chart": profitability_chart,
    }
    return _pdf_response(
        request,
        "trading/report.html",
        context,
        f"trading-report-config-{config.id}.pdf",
    )


def _combination_count(params, symbol_count):
    result = symbol_count
    for prefix in ("acc", "nda", "deltadelta"):
        start = params[f"{prefix}_from"]
        end = params[f"{prefix}_to"]
        step = params[f"{prefix}_steps"]
        result *= math.floor((end - start) / step + 1e-9) + 1
    return result


@login_required
def backtesting_form(request, config_id):
    config = get_object_or_404(Configuration, id=config_id, user=request.user)
    form = BacktestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        params = form.cleaned_data.copy()
        schedule_backtest = params.pop("schedule_backtest", False)
        scheduled_start_time = params.pop("scheduled_start_time", None)
        symbols = _symbols(config)
        combinations = _combination_count(params, len(symbols))
        if combinations > _MAX_TOTAL_BACKTEST_COMBINATIONS:
            form.add_error(
                None,
                f"Mit allen Symbolen entstehen {combinations:,} Kombinationen; "
                f"maximal {_MAX_TOTAL_BACKTEST_COMBINATIONS:,} sind erlaubt.",
            )
        else:
            status = "scheduled" if schedule_backtest else "pending"
            backtest_task = BacktestTask.objects.create(
                configuration=config,
                symbol=",".join(symbols),
                parameters=params,
                result={},
                status=status,
                is_scheduled=schedule_backtest,
                scheduled_start_time=scheduled_start_time,
            )
            if not schedule_backtest:
                celery_task = dispatch_task(
                    run_backtest,
                    config.id,
                    params,
                    symbols,
                    backtest_task.id,
                )
                BacktestTask.objects.filter(id=backtest_task.id).update(
                    celery_task_id=celery_task.id
                )
            return redirect("backtesting_form", config_id=config.id)

    if settings.CELERY_TASK_ALWAYS_EAGER:
        interrupted = BacktestTask.objects.filter(
            configuration=config,
            status__in=["pending", "running", "paused"],
            celery_task_id__startswith="eager-",
        )
        for interrupted_task in interrupted:
            if not local_task_is_active(interrupted_task.celery_task_id):
                interrupted_task.status = "failed"
                interrupted_task.result = {
                    "error": "Der lokale Backtest wurde durch einen Prozessneustart unterbrochen."
                }
                interrupted_task.save()

    tasks_running = BacktestTask.objects.filter(
        configuration=config,
        status__in=["pending", "running", "paused"],
    )
    tasks_scheduled = BacktestTask.objects.filter(
        configuration=config,
        status="scheduled",
    ).order_by("scheduled_start_time")
    tasks_completed = BacktestTask.objects.filter(
        configuration=config,
        status__in=["completed", "failed", "cancelled"],
    ).order_by("-completed_at")[:10]
    return render(
        request,
        "trading/backtesting_form.html",
        {
            "config": config,
            "form": form,
            "tasks_running": tasks_running,
            "tasks_scheduled": tasks_scheduled,
            "backtests": tasks_completed,
        },
    )


@login_required
@require_POST
def control_backtest(request, task_id):
    task = get_object_or_404(
        BacktestTask,
        id=task_id,
        configuration__user=request.user,
    )
    action = request.POST.get("action")
    if action == "cancel":
        task.cancel()
        if task.celery_task_id and not task.celery_task_id.startswith("eager-"):
            AsyncResult(task.celery_task_id).revoke(terminate=True)
    elif action == "pause":
        task.pause()
    elif action == "resume":
        task.resume()
    else:
        return JsonResponse({"status": "error", "message": "Ungültige Aktion"}, status=400)
    return redirect("backtesting_form", config_id=task.configuration_id)


@login_required
@require_GET
def generate_backtest_pdf(request, task_id):
    task = get_object_or_404(
        BacktestTask.objects.select_related("configuration"),
        id=task_id,
        configuration__user=request.user,
    )
    if task.status != "completed":
        return HttpResponse("Backtest ist nicht abgeschlossen.", status=400)
    return _pdf_response(
        request,
        "trading/backtest_report.html",
        {"task": task, "config": task.configuration},
        f"backtest-{task.id}.pdf",
        disposition="inline",
    )


@login_required
@require_GET
def analyse_view(request):
    symbols = [symbol.strip().upper() for symbol in request.GET.getlist("symbols") if symbol]
    timeframe = request.GET.get("timeframe", "1h")
    allowed_timeframes = {"1m", "5m", "15m", "1h", "4h", "1d"}
    available_symbols = sorted(
        {
            symbol
            for config in Configuration.objects.filter(user=request.user)
            for symbol in _symbols(config)
        }
    )
    if not symbols:
        return render(
            request,
            "trading/analyse.html",
            {"available_symbols": available_symbols, "selected_timeframe": timeframe},
        )
    if timeframe not in allowed_timeframes or len(symbols) > 10:
        return render(
            request,
            "trading/analyse.html",
            {
                "error": "Ungültiger Zeitrahmen oder zu viele Symbole.",
                "available_symbols": available_symbols,
            },
        )

    async def analyze_all():
        import ccxt
        import ccxt.async_support as ccxt_async

        exchange = ccxt_async.binance({"enableRateLimit": True, "timeout": 15_000})

        async def analyze_symbol(symbol):
            try:
                limit = 30
                seconds = exchange.parse_timeframe(timeframe)
                since = exchange.milliseconds() - limit * seconds * 1000
                candles = await exchange.fetch_ohlcv(
                    symbol,
                    timeframe,
                    since=since,
                    limit=limit,
                )
                if len(candles) < 16:
                    return {"symbol": symbol, "error": "Nicht genügend Marktdaten."}
                closes = [candle[4] for candle in candles]
                short_now = sum(closes[-5:]) / 5
                long_now = sum(closes[-15:]) / 15
                short_previous = sum(closes[-6:-1]) / 5
                long_previous = sum(closes[-16:-1]) / 15
                signal = "Neutral"
                if short_previous <= long_previous and short_now > long_now:
                    signal = "Kaufen"
                elif short_previous >= long_previous and short_now < long_now:
                    signal = "Verkaufen"
                return {"symbol": symbol, "signal": signal}
            except ccxt.NetworkError as exc:
                return {"symbol": symbol, "error": f"Netzwerkfehler: {exc}"}
            except ccxt.ExchangeError as exc:
                return {"symbol": symbol, "error": f"Börsenfehler: {exc}"}
            except Exception as exc:
                logger.exception("Analyse für %s fehlgeschlagen", symbol)
                return {"symbol": symbol, "error": str(exc)}

        try:
            return await asyncio.gather(*(analyze_symbol(symbol) for symbol in symbols))
        finally:
            await exchange.close()

    results = async_to_sync(analyze_all)()
    return render(
        request,
        "trading/analyse.html",
        {
            "analysis_results": results,
            "selected_symbols": symbols,
            "selected_timeframe": timeframe,
            "available_symbols": available_symbols,
        },
    )

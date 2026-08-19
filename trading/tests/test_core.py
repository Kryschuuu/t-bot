from decimal import Decimal

from asgiref.sync import async_to_sync
from django.contrib.auth.models import User
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from trading.backtesting import Backtesting
from trading.forms import BacktestForm, ConfigurationForm
from trading.models import BacktestTask, Configuration, DataLog, TradingLog
from trading.tasks import run_backtest
from trading.trading_bot import TradingBot


class BacktestingTests(TestCase):
    def test_simulation_accepts_float_thresholds_and_accounts_for_both_fees(self):
        capital, report = Backtesting.simulate_trading_detailed(
            [Decimal(100), Decimal(101), Decimal(103), Decimal(110)],
            -100.0,
            -100.0,
            -100.0,
            {
                "start_capital": Decimal(100),
                "trade_amount": Decimal(10),
                "take_profit": Decimal(1),
                "stop_loss": Decimal(50),
                "fee_percentage": Decimal("0.1"),
            },
        )
        self.assertEqual(report["num_buys"], 1)
        self.assertEqual(report["num_sells"], 1)
        self.assertGreater(capital, Decimal(100))
        sell = next(trade for trade in report["trades"] if trade["type"] == "sell")
        self.assertGreater(sell["profit_nominal"], 0)


class FormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("form-user", password="a-secure-test-pass")

    def configuration_data(self, **overrides):
        data = {
            "name": "Test",
            "exchange": "binance",
            "market": "spot",
            "symbols": "btc/usdt, ETH/USDT,btc/usdt",
            "start_capital": "100",
            "trade_amount": "10",
            "sales_stop_threshold": "10",
            "take_profit": "1",
            "stop_loss": "1",
            "fee": "0.1",
            "api_key": "",
            "secret_key": "",
            "countdown": "0",
            "time_interval": "2",
            "div_DVA_prev_NDA_threshold_buy": "0",
            "deltadelta_threshold_buy": "0",
            "nda_threshold_buy": "0",
        }
        data.update(overrides)
        return data

    def test_configuration_normalizes_symbols(self):
        form = ConfigurationForm(self.configuration_data())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["symbols"], "BTC/USDT,ETH/USDT")

    def test_configuration_rejects_overspending(self):
        form = ConfigurationForm(
            self.configuration_data(start_capital="10", trade_amount="10", fee="1")
        )
        self.assertFalse(form.is_valid())
        self.assertIn("trade_amount", form.errors)

    def test_backtest_rejects_zero_step_and_excessive_range(self):
        data = {
            "acc_from": 0,
            "acc_to": 100,
            "acc_steps": 0,
            "nda_from": 0,
            "nda_to": 100,
            "nda_steps": 0.01,
            "deltadelta_from": 0,
            "deltadelta_to": 100,
            "deltadelta_steps": 0.01,
        }
        form = BacktestForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("acc_steps", form.errors)


@override_settings(PASSPHRASE_GATE_ENABLED=False, AUTOSTART_BOTS=False)
class ViewSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="owner-test-password")
        self.other = User.objects.create_user("other", password="other-test-password")
        self.config = Configuration.objects.create(
            user=self.user,
            name="Inactive config",
            symbols="BTC/USDT",
            countdown=0,
        )
        self.client.force_login(self.user)

    def test_inactive_configuration_is_visible_on_dashboard(self):
        response = self.client.get(reverse("dashboard"), {"config_id": self.config.id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inactive config")
        self.assertContains(response, "Deaktiviert")

    def test_state_changes_reject_get(self):
        for name in ("config_activate", "config_deactivate", "reset_log"):
            response = self.client.get(reverse(name, args=[self.config.id]))
            self.assertEqual(response.status_code, 405)
        response = self.client.get(reverse("manual_sell", args=[self.config.id]))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)

    def test_backtest_control_is_owner_scoped(self):
        foreign_config = Configuration.objects.create(
            user=self.other,
            name="Foreign",
            symbols="BTC/USDT",
        )
        task = BacktestTask.objects.create(
            configuration=foreign_config,
            symbol="BTC/USDT",
        )
        response = self.client.post(
            reverse("control_backtest", args=[task.id]),
            {"action": "cancel"},
        )
        self.assertEqual(response.status_code, 404)
        response = self.client.get(reverse("generate_backtest_pdf", args=[task.id]))
        self.assertEqual(response.status_code, 404)

    def test_data_api_rejects_unknown_symbol(self):
        response = self.client.get(
            reverse("data_logs_api"),
            {"config_id": self.config.id, "symbol": "ETH/USDT"},
        )
        self.assertEqual(response.status_code, 400)


class GateTests(TestCase):
    @override_settings(PASSPHRASE="correct", PASSPHRASE_GATE_ENABLED=True)
    def test_gate_does_not_redirect_to_external_next_url(self):
        response = self.client.post(
            reverse("passphrase_gate") + "?next=https://evil.example/",
            {"passphrase": "correct", "next": "https://evil.example/"},
        )
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)


@override_settings(AUTOSTART_BOTS=False)
class TradingBotTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user("bot-user", password="bot-test-password")
        self.config = Configuration.objects.create(
            user=self.user,
            name="Bot",
            symbols="BTC/USDT",
            start_capital=Decimal(100),
            trade_amount=Decimal(10),
            fee=Decimal("0.1"),
            countdown=0,
        )

    def test_buy_and_sell_keep_amount_and_include_buy_fee(self):
        bot = TradingBot(self.config)
        bot.price_buffer["BTC/USDT"] = [Decimal(100)]
        async_to_sync(bot.execute_trade)("BTC/USDT", "buy")
        buy = TradingLog.objects.get(action="buy")
        bot.price_buffer["BTC/USDT"] = [Decimal(110)]
        async_to_sync(bot.execute_trade)("BTC/USDT", "sell")
        sell = TradingLog.objects.get(action="sell")
        self.assertEqual(sell.amount, buy.amount)
        expected = sell.amount * (sell.price - buy.price) - buy.fee_amount - sell.fee_amount
        self.assertEqual(sell.pl_nominal, expected.quantize(Decimal("0.00000001")))
        self.assertEqual(sell.current_capital, self.config.start_capital + sell.pl_nominal)


@override_settings(AUTOSTART_BOTS=False)
class BacktestTaskTests(TestCase):
    def setUp(self):
        user = User.objects.create_user("backtest-user", password="backtest-password")
        self.config = Configuration.objects.create(
            user=user,
            name="Backtest",
            symbols="BTC/USDT",
            countdown=0,
        )
        for price in (100, 101, 103, 110):
            DataLog.objects.create(
                configuration=self.config,
                symbol="BTC/USDT",
                price=price,
                min_price=price,
                max_price=price,
            )

    def test_run_backtest_completes_and_serializes_decimals(self):
        params = {
            "acc_from": -100,
            "acc_to": -100,
            "acc_steps": 1,
            "nda_from": -100,
            "nda_to": -100,
            "nda_steps": 1,
            "deltadelta_from": -100,
            "deltadelta_to": -100,
            "deltadelta_steps": 1,
        }
        task = BacktestTask.objects.create(
            configuration=self.config,
            symbol="BTC/USDT",
            parameters=params,
        )
        run_backtest.run(self.config.id, params, ["BTC/USDT"], task.id)
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.progress, 100)
        self.assertIn("BTC/USDT", task.result["symbol_results"])

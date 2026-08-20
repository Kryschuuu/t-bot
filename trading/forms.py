import math
import re

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.models import User
from django.utils import timezone

from .market_data import MarketDataError, SymbolValidationError, validate_exchange_symbols
from .models import Configuration

_SYMBOL_RE = re.compile(r"^[A-Z0-9._-]+/[A-Z0-9._:-]+$")
_MAX_BACKTEST_COMBINATIONS = 20_000


class RegistrationForm(forms.ModelForm):
    password = forms.CharField(
        label="Passwort",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    confirm_password = forms.CharField(
        label="Passwort bestätigen",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = User
        fields = ["username", "email"]
        widgets = {
            "username": forms.TextInput(attrs={"autocomplete": "username"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        if password and password != cleaned_data.get("confirm_password"):
            self.add_error("confirm_password", "Passwörter stimmen nicht überein.")
        if password:
            try:
                password_validation.validate_password(password, self.instance)
            except forms.ValidationError as exc:
                self.add_error("password", exc)
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class LoginForm(forms.Form):
    username = forms.CharField(
        label="Benutzername",
        widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": True}),
    )
    password = forms.CharField(
        label="Passwort",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class ConfigurationForm(forms.ModelForm):
    class Meta:
        model = Configuration
        fields = [
            "name",
            "exchange",
            "market",
            "symbols",
            "start_capital",
            "trade_amount",
            "sales_stop_threshold",
            "take_profit",
            "stop_loss",
            "fee",
            "api_key",
            "secret_key",
            "countdown",
            "countdown_reset_indicators",
            "time_interval",
            "div_DVA_prev_NDA_threshold_buy",
            "deltadelta_threshold_buy",
            "nda_threshold_buy",
        ]
        widgets = {
            "symbols": forms.Textarea(attrs={"rows": 3, "placeholder": "BTC/USDT, ETH/USDT"}),
            "api_key": forms.PasswordInput(attrs={"autocomplete": "off"}),
            "secret_key": forms.PasswordInput(attrs={"autocomplete": "off"}),
            "countdown_reset_indicators": forms.CheckboxInput(),
        }
        help_texts = {
            "symbols": "Handelspaare durch Kommas trennen, z. B. BTC/USDT, ETH/USDT.",
            "sales_stop_threshold": "Gesamtverlustgrenze in Prozent; 0 deaktiviert sie.",
            "take_profit": "Take-Profit pro Position in Prozent.",
            "stop_loss": "Stop-Loss pro Position in Prozent.",
            "fee": "Simulierte Handelsgebühr je Order in Prozent.",
            "countdown": "Wartezeit nach Bot-Start in Minuten.",
            "time_interval": "Pause zwischen zwei Preiszyklen in Sekunden.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                css_class = "form-check-input"
            elif isinstance(field.widget, forms.Select):
                css_class = "form-select"
            else:
                css_class = "form-control"
            field.widget.attrs["class"] = " ".join(
                filter(None, (field.widget.attrs.get("class"), css_class))
            )
        if self.instance and self.instance.pk:
            self.fields["api_key"].widget.attrs["placeholder"] = "Unverändert lassen"
            self.fields["secret_key"].widget.attrs["placeholder"] = "Unverändert lassen"

    def full_clean(self):
        super().full_clean()
        for name in self.errors:
            if name in self.fields:
                widget = self.fields[name].widget
                widget.attrs["class"] = f"{widget.attrs.get('class', '')} is-invalid".strip()
                widget.attrs["aria-invalid"] = "true"

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if len(name) < 3:
            raise forms.ValidationError("Der Name muss mindestens 3 Zeichen lang sein.")
        return name

    def clean_symbols(self):
        raw_symbols = self.cleaned_data["symbols"]
        symbols = []
        for raw_symbol in raw_symbols.split(","):
            symbol = raw_symbol.strip().upper()
            if not symbol:
                continue
            if not _SYMBOL_RE.fullmatch(symbol):
                raise forms.ValidationError(
                    f"Ungültiges Handelspaar „{symbol}“. Erwartet wird z. B. BTC/USDT."
                )
            if symbol not in symbols:
                symbols.append(symbol)
        if not symbols:
            raise forms.ValidationError("Mindestens ein Handelspaar ist erforderlich.")
        if len(symbols) > 20:
            raise forms.ValidationError("Maximal 20 Handelspaare pro Konfiguration sind erlaubt.")
        normalized = ",".join(symbols)
        if len(normalized) > Configuration._meta.get_field("symbols").max_length:
            raise forms.ValidationError("Die Symbolliste ist zu lang.")
        return normalized

    def clean_api_key(self):
        value = self.cleaned_data.get("api_key")
        if not value and self.instance and self.instance.pk:
            return self.instance.api_key
        return value

    def clean_secret_key(self):
        value = self.cleaned_data.get("secret_key")
        if not value and self.instance and self.instance.pk:
            return self.instance.secret_key
        return value

    def clean(self):
        cleaned_data = super().clean()
        start_capital = cleaned_data.get("start_capital")
        trade_amount = cleaned_data.get("trade_amount")
        fee = cleaned_data.get("fee")
        api_key = cleaned_data.get("api_key")
        secret_key = cleaned_data.get("secret_key")
        interval = cleaned_data.get("time_interval")
        countdown = cleaned_data.get("countdown")
        loss_threshold = cleaned_data.get("sales_stop_threshold")

        if start_capital is not None and trade_amount is not None:
            fee_factor = 1 + ((fee or 0) / 100)
            if trade_amount * fee_factor > start_capital:
                self.add_error(
                    "trade_amount",
                    "Trade-Betrag einschließlich Kaufgebühr darf das Startkapital nicht überschreiten.",
                )
        if fee is not None and fee > 5:
            self.add_error("fee", "Eine simulierte Gebühr über 5 % ist nicht plausibel.")
        if bool(api_key) != bool(secret_key):
            message = "API-Key und Secret-Key müssen entweder beide gesetzt oder beide leer sein."
            self.add_error("api_key", message)
            self.add_error("secret_key", message)
        if interval is not None and interval > 300:
            self.add_error(
                "time_interval", "Das Zeitintervall darf höchstens 300 Sekunden betragen."
            )
        if countdown is not None and countdown > 10_080:
            self.add_error("countdown", "Der Countdown darf höchstens 7 Tage betragen.")
        if loss_threshold is not None and 0 < loss_threshold < 0.1:
            self.add_error(
                "sales_stop_threshold",
                "Die Gesamtverlustgrenze muss 0 (deaktiviert) oder mindestens 0,1 % sein.",
            )

        exchange = cleaned_data.get("exchange")
        market = cleaned_data.get("market")
        symbols_value = cleaned_data.get("symbols")
        if (
            exchange in {"bitmart", "bitunix"}
            and market == "spot"
            and interval is not None
            and interval < 5
        ):
            self.add_error(
                "time_interval",
                "Für BitMart/Bitunix Spot sind mindestens 5 Sekunden erforderlich, "
                "damit Einzel-Ticker sicher unter dem API-Limit bleiben.",
            )
        validation_fields = ("exchange", "market", "symbols")
        validation_blocked = any(field in self.errors for field in validation_fields)
        if exchange and market and symbols_value and not validation_blocked:
            symbols = [symbol for symbol in symbols_value.split(",") if symbol]
            try:
                validate_exchange_symbols(exchange, market, symbols)
            except SymbolValidationError as exc:
                self.add_error("symbols", str(exc))
            except (MarketDataError, ValueError) as exc:
                self.add_error(
                    None,
                    f"Die Exchange-Konfiguration konnte nicht verifiziert werden: {exc}. "
                    "Bitte Verbindung, Exchange, Markt und Symbole prüfen und erneut speichern.",
                )
        return cleaned_data


class DashboardConfigurationForm(forms.ModelForm):
    class Meta:
        model = Configuration
        fields = [
            "div_DVA_prev_NDA_threshold_buy",
            "deltadelta_threshold_buy",
            "nda_threshold_buy",
            "stop_loss",
            "take_profit",
        ]


class BacktestForm(forms.Form):
    acc_from = forms.FloatField(label="Von")
    acc_to = forms.FloatField(label="Bis")
    acc_steps = forms.FloatField(label="Schrittgröße", min_value=1e-12)
    nda_from = forms.FloatField(label="Von")
    nda_to = forms.FloatField(label="Bis")
    nda_steps = forms.FloatField(label="Schrittgröße", min_value=1e-12)
    deltadelta_from = forms.FloatField(label="Von")
    deltadelta_to = forms.FloatField(label="Bis")
    deltadelta_steps = forms.FloatField(label="Schrittgröße", min_value=1e-12)
    schedule_backtest = forms.BooleanField(label="Backtest planen?", required=False)
    scheduled_start_time = forms.DateTimeField(
        label="Geplante Startzeit",
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        scheduled = cleaned_data.get("schedule_backtest")
        start_time = cleaned_data.get("scheduled_start_time")
        if scheduled and not start_time:
            self.add_error("scheduled_start_time", "Bitte eine Startzeit angeben.")
        elif start_time and start_time <= timezone.now():
            self.add_error("scheduled_start_time", "Die Startzeit muss in der Zukunft liegen.")

        dimensions = []
        for prefix in ("acc", "nda", "deltadelta"):
            start = cleaned_data.get(f"{prefix}_from")
            end = cleaned_data.get(f"{prefix}_to")
            step = cleaned_data.get(f"{prefix}_steps")
            if start is None or end is None or step is None:
                continue
            if not all(math.isfinite(value) for value in (start, end, step)):
                self.add_error(f"{prefix}_from", "Nur endliche Zahlen sind erlaubt.")
                continue
            if start > end:
                self.add_error(f"{prefix}_to", "„Bis“ muss größer oder gleich „Von“ sein.")
                continue
            dimensions.append(math.floor((end - start) / step + 1e-9) + 1)

        if len(dimensions) == 3 and math.prod(dimensions) > _MAX_BACKTEST_COMBINATIONS:
            raise forms.ValidationError(
                f"Zu viele Kombinationen ({math.prod(dimensions):,}). "
                f"Maximal {_MAX_BACKTEST_COMBINATIONS:,} pro Symbol sind erlaubt."
            )
        return cleaned_data

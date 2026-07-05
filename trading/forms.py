from django import forms
from django.contrib.auth.models import User
from .models import Configuration
from django.utils import timezone
import logging

# Logging konfigurieren
logger = logging.getLogger(__name__)

class RegistrationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder': 'Passwort'}))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder': 'Passwort bestätigen'}))

    class Meta:
        model = User
        fields = ['username', 'email']
        help_texts = {
            'username': 'Geben Sie Ihren gewünschten Benutzernamen ein.',
            'email': 'Geben Sie Ihre E-Mail-Adresse ein.',
        }
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'Benutzername'}),
            'email': forms.EmailInput(attrs={'placeholder': 'E-Mail-Adresse'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm = cleaned_data.get("confirm_password")
        if password != confirm:
            raise forms.ValidationError("Passwörter stimmen nicht überein.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data["password"]
        user.set_password(password)
        if commit:
            user.save()
        return user

class LoginForm(forms.Form):
    username = forms.CharField(widget=forms.TextInput(attrs={'placeholder': 'Benutzername'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder': 'Passwort'}))

    def __init__(self, *args, **kwargs):
        super(LoginForm, self).__init__(*args, **kwargs)
        self.fields['username'].help_text = "Geben Sie Ihren Benutzernamen ein."
        self.fields['password'].help_text = "Geben Sie Ihr Passwort ein."

class ConfigurationForm(forms.ModelForm):
    class Meta:
        model = Configuration
        fields = ['exchange', 'market', 'symbols', 'start_capital', 'trade_amount',
                  'sales_stop_threshold', 'take_profit', 'stop_loss', 'fee', 'api_key', 'secret_key',
                  'countdown', 'countdown_reset_indicators', 'time_interval', 'div_DVA_prev_NDA_threshold_buy', 'deltadelta_threshold_buy', 'nda_threshold_buy']
        widgets = {
            'symbols': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Symbole durch Komma trennen (z.B. BTC, ETH, LTC)'}),
            'api_key': forms.PasswordInput(attrs={'placeholder': 'API Key eingeben'}),
            'secret_key': forms.PasswordInput(attrs={'placeholder': 'Secret Key eingeben'}),
            'countdown': forms.NumberInput(attrs={'placeholder': 'Countdown in Minuten'}),
            'countdown_reset_indicators': forms.NumberInput(attrs={'placeholder': 'Countdown in Sekunden'}),
            'time_interval': forms.NumberInput(attrs={'placeholder': 'Zeitintervall in Sekunden'}),
            'div_DVA_prev_NDA_threshold_buy': forms.NumberInput(attrs={'placeholder': 'Beschleunigung > Wert'}),
            'deltadelta_threshold_buy': forms.NumberInput(attrs={'placeholder': 'DeltaDelta > Wert'}),
            'nda_threshold_buy': forms.NumberInput(attrs={'placeholder': 'DeltaDelta > Wert'}),
        }
        help_texts = {
            'exchange': 'Wählen Sie die Krypto-Börse aus.',
            'markt': 'Wählen Sie den Markt aus spot oder futures.',
            'symbols': 'Geben Sie die Handelssymbole durch Komma getrennt ein.',
            'start_capital': 'Geben Sie das Startkapital ein.',
            'trade_amount': 'Geben Sie den Betrag pro Trade ein.',
            'sales_stop_threshold': 'Geben Sie den Verkaufsstop-Schwellenwert ein.',
            'take_profit': 'Geben Sie den Take-Profit-Prozentsatz ein.',
            'stop_loss': 'Geben Sie den Stop-Loss-Prozentsatz ein.',
            'fee': 'Geben Sie die prozentuale Handelsgebühr ein.',
            'api_key': 'Geben Sie Ihren API Key ein.',
            'secret_key': 'Geben Sie Ihren Secret Key ein.',
            'countdown': 'Erst wenn der Countdown ( in Minuten) abläuft werden order getätigt.',
            'countdown_reset_indicators': 'Reset (in Sekunden) für die Indikatoren nach einem Sell. Die Werte der Indikatoren werden genullt',
            'time_interval': 'Geben Sie das Zeitintervall für die Preisabfrage in Sekunden ein.',
            'div_DVA_prev_NDA_threshold_buy': 'Geben Sie den Beschleunigungs-Schwellenwert für Käufe ein.',
            'deltadelta_threshold_buy': 'Geben Sie den DeltaDelta-Schwellenwert für Käufe ein.',
            'nda_threshold_buy': 'Geben Sie den nda-Schwellenwert für Käufe ein.',
        }

class DashboardConfigurationForm(forms.ModelForm):
    class Meta:
        model = Configuration
        fields = ['div_DVA_prev_NDA_threshold_buy', 'deltadelta_threshold_buy', 'nda_threshold_buy', 'stop_loss', 'take_profit']


class BacktestForm(forms.Form):
    acc_from = forms.FloatField(label='Von', required=True)
    acc_to = forms.FloatField(label='Bis', required=True)
    acc_steps = forms.FloatField(label='Schrittgröße', required=True)

    nda_from = forms.FloatField(label='Von', required=True)
    nda_to = forms.FloatField(label='Bis', required=True)
    nda_steps = forms.FloatField(label='Schrittgröße', required=True)

    deltadelta_from = forms.FloatField(label='Von', required=True)
    deltadelta_to = forms.FloatField(label='Bis', required=True)
    deltadelta_steps = forms.FloatField(label='Schrittgröße', required=True)

    schedule_backtest = forms.BooleanField(label='Backtest planen?', required=False) # Neu: Checkbox für Planung
    scheduled_start_time = forms.DateTimeField(label='Geplante Startzeit', required=False, widget=forms.DateTimeInput(attrs={'type': 'datetime-local'})) # Neu: Feld für Startzeit

    def clean(self):
        cleaned_data = super().clean()
        schedule_backtest = cleaned_data.get('schedule_backtest')
        scheduled_start_time = cleaned_data.get('scheduled_start_time')

        if schedule_backtest and not scheduled_start_time:
            self.add_error('scheduled_start_time', 'Bitte geben Sie eine geplante Startzeit an, wenn Sie den Backtest planen möchten.')
        elif scheduled_start_time and scheduled_start_time <= timezone.now():
            self.add_error('scheduled_start_time', 'Die geplante Startzeit muss in der Zukunft liegen.')

        return cleaned_data

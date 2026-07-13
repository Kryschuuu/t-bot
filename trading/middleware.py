# trading/middleware.py
from django.shortcuts import redirect
from django.urls import reverse
from django.conf import settings

# Pfade, die IMMER ohne Passphrase erreichbar sein muessen - sonst kaeme
# niemand mehr auf die Seite, auf der man die Passphrase eingibt.
_EXEMPT_PREFIXES = (
    "/static/",
)


class PassphraseGateMiddleware:
    """Blockiert die komplette App, bis in dieser Browser-Session einmal die
    korrekte Passphrase eingegeben wurde (siehe trading/views.py::passphrase_gate_view).

    Greift VOR Registrierung/Login - ein Besucher ohne gueltige Passphrase
    sieht ausschliesslich die Landingpage mit Disclaimer + Passphrase-Feld,
    unabhaengig davon, welche URL ursprünglich aufgerufen wurde.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "PASSPHRASE_GATE_ENABLED", True):
            return self.get_response(request)

        exempt_path = (
            request.path == reverse("passphrase_gate")
            or any(request.path.startswith(p) for p in _EXEMPT_PREFIXES)
        )

        if not exempt_path and not request.session.get("passphrase_verified"):
            next_url = request.get_full_path()
            gate_url = reverse("passphrase_gate")
            if next_url and next_url != gate_url:
                gate_url = f"{gate_url}?next={next_url}"
            return redirect(gate_url)

        return self.get_response(request)

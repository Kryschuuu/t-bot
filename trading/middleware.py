from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class PassphraseGateMiddleware:
    """Schützt HTTP-Endpunkte bis zur Passphrase-Freigabe der Session."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "PASSPHRASE_GATE_ENABLED", True):
            return self.get_response(request)

        gate_path = reverse("passphrase_gate")
        health_path = reverse("health")
        static_url = settings.STATIC_URL or "/static/"
        exempt = (
            request.path == gate_path
            or request.path == health_path
            or request.path.startswith(static_url)
        )
        if exempt or request.session.get("passphrase_verified"):
            return self.get_response(request)

        query = urlencode({"next": request.get_full_path()})
        return redirect(f"{gate_path}?{query}")

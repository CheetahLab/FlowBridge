"""Tests fuer die Fehlerbehandlung von POST /api/command.

Hintergrund (16.08.2026, von Dirk im Feld getroffen): Nach einem Stromausfall
hatte sich der RIVER 2 Pro wegen Tiefentladung abgeschaltet. Die EcoFlow-Cloud
war erreichbar und beantwortete quota/all weiter aus ihrem Cache, konnte den
Steuerbefehl aber nicht zustellen. In der Oberflaeche stand daraufhin nur:

    500 Internal Server Error

Der Grund war die Ausnahmeliste des Endpunkts: Sie kannte CommandError und
EcoFlowAuthError, sonst nichts. Alles andere - EcoFlowApiError, DNS-Fehler,
Zeitueberschreitungen - fiel roh durch. FastAPI macht daraus einen 500 ohne
`detail`, und das Frontend zeigt bei fehlendem `detail` den nackten Statustext
(api.ts). Der Anwender erfaehrt also ausgerechnet dann nichts, wenn wirklich
etwas kaputt ist.

Diese Tests nageln fest, dass JEDE Ausnahme mit einem Text herauskommt, und
dass die Statuscodes die drei Faelle auseinanderhalten - 502 heisst "EcoFlow
sagt nein", 503 heisst "EcoFlow war gar nicht da". Ohne diese Trennung sucht
man beim naechsten Mal wieder an der falschen Stelle.
"""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import app  # noqa: E402
from commands_river2 import CommandError  # noqa: E402
from ecoflow_client import EcoFlowApiError, EcoFlowAuthError  # noqa: E402

SN = "TEST-SN-0001"


def _sende(monkeypatch, exc):
    """Laesst _execute_command mit `exc` scheitern und ruft den Endpunkt."""

    async def _fehlschlag(*_args, **_kwargs):
        raise exc

    monkeypatch.setattr(app, "_execute_command", _fehlschlag)
    req = app.CommandRequest(sn=SN, property="charge_power_watts", value="200")
    with pytest.raises(HTTPException) as info:
        asyncio.run(app.send_command(req))
    return info.value


def test_geraet_nicht_erreichbar_wird_502_mit_text(monkeypatch):
    """Der Fall vom 16.08.2026: EcoFlow antwortet, lehnt aber ab."""
    fehler = _sende(monkeypatch, EcoFlowApiError("EcoFlow meldet Fehler: device offline"))
    assert fehler.status_code == 502
    assert "device offline" in fehler.detail
    # Der Hinweis auf die wahrscheinliche Ursache ist der eigentliche Gewinn -
    # ohne ihn steht da eine EcoFlow-Fehlermeldung, mit der niemand etwas
    # anfangen kann.
    assert "Cloud" in fehler.detail


def test_netzfehler_wird_503_mit_text(monkeypatch):
    """Genau der DNS-Ausfall, den die NAS am 15.08.2026 neun Stunden hatte."""
    fehler = _sende(monkeypatch, OSError("[Errno -3] Temporary failure in name resolution"))
    assert fehler.status_code == 503
    assert "name resolution" in fehler.detail


def test_unerwartete_ausnahme_bleibt_kein_nackter_500(monkeypatch):
    """Der Kern des Ganzen: Es darf keine Ausnahme mehr ohne Text geben.

    Absichtlich ein Typ, an den niemand gedacht hat - der Endpunkt soll ihn
    nicht deshalb fangen, weil er in einer Liste steht, sondern weil er
    ueberhaupt nichts mehr durchlaesst."""
    fehler = _sende(monkeypatch, RuntimeError("irgendwas Unerwartetes"))
    assert fehler.status_code == 503
    assert "irgendwas Unerwartetes" in fehler.detail
    assert "RuntimeError" in fehler.detail  # Typ mit, sonst raet man beim Suchen


def test_ungueltiger_wert_bleibt_400(monkeypatch):
    """ValueError ist ein Bedienfehler, kein Ausfall - er darf nicht als 503
    durchgehen, sonst schickt man jemanden auf Netzwerksuche, obwohl nur eine
    Zahl ausserhalb des Bereichs lag."""
    fehler = _sende(monkeypatch, ValueError("Wert muss zwischen 100 und 940 liegen."))
    assert fehler.status_code == 400
    assert "940" in fehler.detail


def test_command_error_bleibt_400(monkeypatch):
    """Regression: Die beiden schon vorher behandelten Faelle bleiben, wie sie
    waren. Die neuen Zweige sitzen dahinter, nicht davor."""
    fehler = _sende(monkeypatch, CommandError("Für das Modell sind keine Befehle bekannt."))
    assert fehler.status_code == 400


def test_auth_fehler_bleibt_401(monkeypatch):
    fehler = _sende(monkeypatch, EcoFlowAuthError("Key abgelehnt (401)."))
    assert fehler.status_code == 401


def test_erfolg_bleibt_unveraendert(monkeypatch):
    """Gegenprobe - die Fehlerbehandlung darf den Normalfall nicht anfassen."""

    async def _ok(*_args, **_kwargs):
        return {"code": "0", "message": "Success"}

    monkeypatch.setattr(app, "_execute_command", _ok)
    req = app.CommandRequest(sn=SN, property="charge_power_watts", value="200")
    antwort = asyncio.run(app.send_command(req))
    assert antwort["ok"] is True
    assert antwort["data"]["message"] == "Success"

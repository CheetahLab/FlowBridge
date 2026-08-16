"""
Darstellungs-Vorgabe (/api/ui): Theme und Sprache dieser Installation.

Warum es das ueberhaupt gibt: Die Schalter im Kopf der Seite liegen im
localStorage und gelten deshalb je Browser. Am Handy, in einem zweiten
Browser oder nach dem Leeren des Verlaufs stand wieder Dunkel/Deutsch da -
egal, was jemand eingestellt hatte. Die Vorgabe hier ist der Startpunkt fuer
jeden Browser, der FlowBridge zum ersten Mal sieht.

Geprueft wird vor allem die PRUEFUNG der Werte: Landet ein Tippfehler in der
config.yaml, steht die Oberflaeche beim naechsten Start vor einem Theme, das
es nicht gibt - und niemand sieht, warum.

Aufgerufen wird die Endpunkt-Funktion direkt (wie in
test_setup_test_endpoint.py), nicht ueber HTTP: Hier geht es um die Pruefung
der Werte, nicht um den Zugriffsschutz - der hat eigene Tests.
"""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import app as app_modul  # noqa: E402
import config as config_modul  # noqa: E402


def _speichern(monkeypatch, theme, language):
    """Ruft den Endpunkt auf und gibt zurueck, was geschrieben WORDEN WAERE."""
    geschrieben: dict = {}
    monkeypatch.setattr(app_modul, "load_config", lambda: {"ui": {}})
    monkeypatch.setattr(app_modul, "write_config", lambda c: geschrieben.update(c))
    antwort = asyncio.run(
        app_modul.save_ui(app_modul.UiRequest(theme=theme, language=language))
    )
    return antwort, geschrieben


def test_vorgabe_wird_gespeichert(monkeypatch):
    antwort, geschrieben = _speichern(monkeypatch, "light", "en")

    assert antwort == {"ok": True}
    assert geschrieben["ui"] == {"theme": "light", "language": "en"}


@pytest.mark.parametrize(
    ("theme", "language"),
    [
        ("hell", "de"),      # deutscher Name statt "light"
        ("dark", "deutsch"),  # ausgeschrieben statt "de"
        ("", "de"),
        ("dark", ""),
    ],
)
def test_unbekannte_werte_werden_abgelehnt(monkeypatch, theme, language):
    """Ein falscher Wert darf gar nicht erst in die Datei kommen.

    Sonst faellt er erst beim naechsten Start auf - und dann sieht es aus,
    als sei die Oberflaeche kaputt, nicht die Konfiguration.
    """
    def nicht_schreiben(_c):
        raise AssertionError("Bei ungueltigen Werten darf nichts gespeichert werden")

    monkeypatch.setattr(app_modul, "write_config", nicht_schreiben)

    with pytest.raises(HTTPException) as fehler:
        asyncio.run(
            app_modul.save_ui(app_modul.UiRequest(theme=theme, language=language))
        )
    assert fehler.value.status_code == 400


def test_vorgabe_steht_in_der_konfiguration():
    """Ohne Eintrag in DEFAULT_CONFIG liefe die Oberflaeche in ein undefined,
    sobald jemand eine aeltere config.yaml mitbringt."""
    assert config_modul.DEFAULT_CONFIG["ui"] == {"language": "de", "theme": "dark"}

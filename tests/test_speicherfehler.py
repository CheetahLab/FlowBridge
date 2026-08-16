"""
Nicht beschreibbarer Datenordner - der haeufigste Stolperstein auf einer NAS.

Vorgeschichte: Der eingebundene Ordner gehoerte dem NAS-Benutzer, FlowBridge
laeuft als Benutzer 1000. Beim Start warf write_config() eine OSError, die
niemand fing; uvicorn beendete sich, Docker startete neu - endlos, und im
Browser war nichts zu sehen. Der Einstiegspunkt raeumt die Ursache inzwischen
aus; diese Tests sichern das Verhalten fuer den Fall, dass es doch einmal
nicht klappt.

Zwei Zusagen werden geprueft:
  1. FlowBridge startet trotzdem - statt in einer Schleife zu verschwinden.
  2. Der Grund steht OHNE Anmeldung in /api/auth/state - sonst saehe der
     Nutzer nur ein Anmeldefenster, das ihn niemals einlaesst.

WICHTIG: FLOWBRIDGE_CONFIG wird VOR dem Import von app gesetzt, sonst laedt
(und beschreibt!) der Test die echte config.yaml.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_tmp = Path(tempfile.mkdtemp(prefix="flowbridge-speicher-")) / "config.yaml"
os.environ["FLOWBRIDGE_CONFIG"] = str(_tmp)
os.environ.pop("FLOWBRIDGE_PASSWORD", None)

from fastapi.testclient import TestClient  # noqa: E402

import app as app_modul  # noqa: E402
import config as config_modul  # noqa: E402


@pytest.fixture
def gesperrt(monkeypatch):
    """Tut so, als sei der Datenordner nicht beschreibbar.

    Bewusst ueber die Schreibprobe statt ueber echte Dateirechte: Unter
    Windows laesst sich "gehoert einem anderen Benutzer" nicht nachstellen,
    und der Test soll ueberall dasselbe pruefen.
    """
    grund = "/config: Permission denied"
    monkeypatch.setattr(config_modul, "schreibprobe", lambda: grund)
    monkeypatch.setattr(app_modul, "config_schreibprobe", lambda: grund)
    return grund


def test_startet_trotz_gesperrtem_ordner(gesperrt):
    """Kein Absturz - genau das war die Dauerschleife."""
    with TestClient(app_modul.app) as client:
        assert client.get("/api/auth/state").status_code == 200


def test_grund_steht_ohne_anmeldung_im_zustand(gesperrt):
    with TestClient(app_modul.app) as client:
        zustand = client.get("/api/auth/state").json()
    assert zustand["storage_error"] == gesperrt


def test_umgebungspasswort_reisst_den_start_nicht_um(monkeypatch, gesperrt):
    """Der urspruengliche Ausloeser: OSError aus write_config im Start.

    Ohne das except OSError in _passwort_aus_umgebung_uebernehmen() faellt
    dieser Test mit genau der Meldung um, die auf der NAS im Protokoll stand.

    load_config wird ausdruecklich ueberschrieben: Alle Testmodule teilen
    sich ueber FLOWBRIDGE_CONFIG denselben Pfad, und ein anderes Modul hat
    dort laengst ein Passwort abgelegt. Ohne diesen Griff waere der Schreib-
    pfad gar nicht erreicht - der Test liefe gruen, ohne etwas zu pruefen.
    """
    versuche: list[dict] = []

    def schreiben_verweigern(config):
        versuche.append(config)
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(app_modul, "load_config", lambda: {})
    monkeypatch.setattr(app_modul, "write_config", schreiben_verweigern)
    monkeypatch.setattr(app_modul.auth, "umgebungs_passwort", lambda: "ein-gutes-Passwort")

    with TestClient(app_modul.app) as client:
        antwort = client.get("/api/auth/state")

    # Nachweis, dass der Schreibpfad wirklich durchlaufen wurde. Sonst
    # bewiese ein bestandener Test nur, dass nichts passiert ist.
    assert versuche, "write_config wurde gar nicht erst aufgerufen"
    assert antwort.status_code == 200


def test_ohne_sperre_bleibt_der_zustand_sauber():
    """Gegenprobe: Der Wert ist None, wenn alles in Ordnung ist."""
    with TestClient(app_modul.app) as client:
        assert client.get("/api/auth/state").json()["storage_error"] is None

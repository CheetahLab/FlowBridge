"""Tests fuer /api/setup/test - insbesondere den maskierten Secret-Key.

Hintergrund (12.08.2026, von Dirk im UI gefunden): In der
Einstellungen-Ansicht kommt der Secret-Key maskiert aus /api/config. Wer dort
nur "Verbindung testen" drueckt, ohne das Feld anzufassen, schickte den
Platzhalter mit - der ging ungeprueft an EcoFlow und fuehrte zu
"signature is wrong", obwohl die gespeicherten Zugangsdaten gueltig waren.
Der Speichern-Pfad hatte den Fall schon behandelt, der Test-Pfad nicht.
"""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import app  # noqa: E402
from config import MASK_PLACEHOLDER  # noqa: E402


class _FakeCert:
    url = "mqtt-e.ecoflow.com"
    port = 8883


@pytest.fixture
def erfasse_secret(monkeypatch):
    """Faengt ab, mit welchem Secret-Key der EcoFlowClient gebaut wird."""
    benutzt = {}

    class FakeClient:
        def __init__(self, access_key, secret_key, *_args, **_kwargs):
            benutzt["access_key"] = access_key
            benutzt["secret_key"] = secret_key

        async def get_mqtt_certificate(self):
            return _FakeCert()

    monkeypatch.setattr(app, "EcoFlowClient", FakeClient)
    return benutzt


def _config_mit_secret(monkeypatch, secret):
    monkeypatch.setattr(
        app,
        "load_config",
        lambda: {"ecoflow": {"access_key": "AK", "secret_key": secret, "devices": []},
                 "mqtt": {}, "ui": {}},
    )


def test_maskierter_secret_key_faellt_auf_gespeicherten_zurueck(monkeypatch, erfasse_secret):
    _config_mit_secret(monkeypatch, "ECHTES_SECRET")
    req = app.TestRequest(access_key="AK", secret_key=MASK_PLACEHOLDER)

    asyncio.run(app.test_credentials(req))

    assert erfasse_secret["secret_key"] == "ECHTES_SECRET"


def test_leerer_secret_key_faellt_auf_gespeicherten_zurueck(monkeypatch, erfasse_secret):
    _config_mit_secret(monkeypatch, "ECHTES_SECRET")
    req = app.TestRequest(access_key="AK", secret_key="")

    asyncio.run(app.test_credentials(req))

    assert erfasse_secret["secret_key"] == "ECHTES_SECRET"


def test_eingegebener_secret_key_wird_verwendet(monkeypatch, erfasse_secret):
    """Ein tatsaechlich eingetippter neuer Key darf NICHT ueberschrieben werden."""
    _config_mit_secret(monkeypatch, "ALTES_SECRET")
    req = app.TestRequest(access_key="AK", secret_key="NEUES_SECRET")

    asyncio.run(app.test_credentials(req))

    assert erfasse_secret["secret_key"] == "NEUES_SECRET"


def test_ohne_gespeicherten_und_ohne_eingegebenen_key_klare_fehlermeldung(monkeypatch, erfasse_secret):
    _config_mit_secret(monkeypatch, "")
    req = app.TestRequest(access_key="AK", secret_key=MASK_PLACEHOLDER)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(app.test_credentials(req))

    assert exc.value.status_code == 400


# ------------------------------------------------ Client-ID (13.08.2026)
def _setup_anfrage(client_id: str) -> app.SetupRequest:
    return app.SetupRequest(
        access_key="TESTaccessKEY",
        secret_key="TESTsecretKEY",
        mqtt_host="192.168.1.10",
        mqtt_client_id=client_id,
    )


def test_zu_kurze_client_id_wird_abgelehnt(monkeypatch, tmp_path):
    """Zehn Zeichen sind die Regel des EisBaer, nicht des MQTT-Standards.

    Bewusst SERVERseitig geprueft: Wer /api/setup direkt anspricht, umgeht
    das Formular - und merkte den zu kurzen Wert sonst erst beim Import
    drueben im EisBaer.
    """
    monkeypatch.setattr(app, "write_config", lambda _c: None)
    monkeypatch.setattr(app, "load_config", lambda: {
        "ecoflow": {"access_key": "", "secret_key": "", "devices": []},
        "mqtt": {}, "ui": {},
    })

    with pytest.raises(HTTPException) as fehler:
        asyncio.run(app.save_setup(_setup_anfrage("kurz")))
    assert fehler.value.status_code == 400


def test_leere_client_id_ist_erlaubt(monkeypatch):
    """Leer heisst "automatisch" - das ist der Normalfall, kein Fehler."""
    geschrieben = {}
    monkeypatch.setattr(app, "write_config", lambda c: geschrieben.update(c))
    monkeypatch.setattr(app, "load_config", lambda: {
        "ecoflow": {"access_key": "", "secret_key": "", "devices": []},
        "mqtt": {}, "ui": {},
    })

    assert asyncio.run(app.save_setup(_setup_anfrage("")))["ok"] is True
    assert geschrieben["mqtt"]["client_id"] == ""


def test_ausreichend_lange_client_id_wird_uebernommen(monkeypatch):
    geschrieben = {}
    monkeypatch.setattr(app, "write_config", lambda c: geschrieben.update(c))
    monkeypatch.setattr(app, "load_config", lambda: {
        "ecoflow": {"access_key": "", "secret_key": "", "devices": []},
        "mqtt": {}, "ui": {},
    })

    asyncio.run(app.save_setup(_setup_anfrage("  flowbridge-nas  ")))
    # Getrimmt gespeichert: Leerzeichen am Rand sind beim Kopieren die Regel
    # und wuerden die Kennung stillschweigend veraendern.
    assert geschrieben["mqtt"]["client_id"] == "flowbridge-nas"

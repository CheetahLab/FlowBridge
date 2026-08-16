"""
Beide MQTT-Verbindungen muessen sich nach einem Fehlstart selbst nachholen.

Vorgeschichte (14.08.2026, zweimal im Feld aufgetreten): `_ensure_connected`
speicherte die Signatur der Konfiguration am Ende IMMER - auch wenn ein
Verbindungsaufbau danebengegangen war. Beim naechsten Durchlauf griff der
Frueh-Ausstieg "schon mit dieser Konfiguration verbunden", und es wurde nie
wieder ein Versuch unternommen.

Beim Containerstart auf der NAS ist genau das der Normalfall: FlowBridge,
Mosquitto und das Netz kommen gleichzeitig hoch, wer zuerst da ist, ist
Zufall. Ergebnis war ein dauerhaftes "getrennt", das nur ein zweiter
Neustart behob - erst beim lokalen Broker, nach dessen Fix beim
EcoFlow-Broker.

WICHTIG: FLOWBRIDGE_CONFIG vor dem Import setzen, sonst laedt der Test die
echte config.yaml.
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_tmp = Path(tempfile.mkdtemp(prefix="flowbridge-verbindung-")) / "config.yaml"
os.environ["FLOWBRIDGE_CONFIG"] = str(_tmp)
os.environ.pop("FLOWBRIDGE_PASSWORD", None)

import app as app_modul  # noqa: E402

CONFIG = {
    "ecoflow": {"access_key": "AK", "secret_key": "SK", "devices": [{"sn": "SN1"}]},
    "mqtt": {"host": "127.0.0.1", "port": 1883},
}


class FakeBridge:
    def __init__(self, *_a, **_k):
        pass

    def connect(self):
        pass

    def subscribe_commands(self, _sn):
        pass

    def disconnect(self):
        pass


class FakeListener:
    def __init__(self, *_a, **_k):
        pass

    def connect(self):
        pass

    def subscribe_device(self, _sn):
        pass

    def disconnect(self):
        pass


@pytest.fixture(autouse=True)
def sauberer_zustand():
    app_modul._bridge = None
    app_modul._live_listener = None
    app_modul._connected_signature = None
    yield
    app_modul._bridge = None
    app_modul._live_listener = None
    app_modul._connected_signature = None
    app_modul._state.pop("SN1", None)
    app_modul._device_errors.pop("SN1", None)


def _ecoflow_client(fehlschlaege: list[bool]):
    """Client, dessen Zertifikatsabruf nach Plan scheitert."""
    class FakeClient:
        def __init__(self, *_a, **_k):
            pass

        async def get_mqtt_certificate(self):
            if fehlschlaege.pop(0):
                raise OSError("Name or service not known")
            return object()

    return FakeClient


def test_ecoflow_wird_nach_fehlstart_nachgeholt(monkeypatch):
    """Der Fall vom 14.08.2026: Netz beim Start noch nicht da."""
    monkeypatch.setattr(app_modul, "MqttBridge", FakeBridge)
    monkeypatch.setattr(app_modul, "EcoFlowMqttListener", FakeListener)
    monkeypatch.setattr(app_modul, "EcoFlowClient", _ecoflow_client([True, False]))

    asyncio.run(app_modul._ensure_connected(CONFIG))
    assert app_modul._live_listener is None, "erster Versuch scheitert planmaessig"
    assert app_modul._bridge is not None, "der lokale Broker steht davon unabhaengig"

    # Gleiche Konfiguration, also greift der Frueh-Ausstieg - genau hier
    # blieb es frueher fuer immer bei "getrennt".
    asyncio.run(app_modul._ensure_connected(CONFIG))
    assert app_modul._live_listener is not None


def test_lokaler_broker_wird_nach_fehlstart_nachgeholt(monkeypatch):
    versuche = {"n": 0}

    class MalKaputt:
        def __init__(self, *_a, **_k):
            versuche["n"] += 1
            if versuche["n"] == 1:
                raise OSError("Connection refused")

        def connect(self):
            pass

        def subscribe_commands(self, _sn):
            pass

        def disconnect(self):
            pass

    monkeypatch.setattr(app_modul, "MqttBridge", MalKaputt)
    monkeypatch.setattr(app_modul, "EcoFlowMqttListener", FakeListener)
    monkeypatch.setattr(app_modul, "EcoFlowClient", _ecoflow_client([False, False]))

    asyncio.run(app_modul._ensure_connected(CONFIG))
    assert app_modul._bridge is None

    asyncio.run(app_modul._ensure_connected(CONFIG))
    assert app_modul._bridge is not None


def test_schneller_takt_loest_keine_flut_von_rest_aufrufen_aus(monkeypatch):
    """Der Preis des schnellen Takts darf nicht die EcoFlow-API sein.

    Die Aufsichtsschleife laeuft seit 14.08.2026 alle 5 s, damit eine beim
    Start fehlgeschlagene Verbindung nicht eine halbe Minute fehlend bleibt.
    Der REST-Resync muss dabei im ALTEN Takt bleiben (poll_interval, 30 s) -
    sonst haetten wir die Aufrufe bei EcoFlow versechsfacht.
    """
    class FakeZeit:
        """Nur die Uhr wird gestellt - der Rest von `time` bleibt echt,
        sonst stolpert alles darueber, was nebenbei Zeitstempel schreibt."""

        jetzt = 0.0
        time = staticmethod(time.time)

        @classmethod
        def monotonic(cls):
            return cls.jetzt

    abrufe = {"n": 0}

    class ZaehlClient:
        def __init__(self, *_a, **_k):
            pass

        async def get_quota_all(self, _sn):
            abrufe["n"] += 1
            return {}

    async def schlafe(sekunden):
        FakeZeit.jetzt += sekunden
        if FakeZeit.jetzt >= 60:
            raise asyncio.CancelledError

    monkeypatch.setattr(app_modul, "time", FakeZeit)
    monkeypatch.setattr(app_modul, "load_config", lambda: {
        **CONFIG, "mqtt": {**CONFIG["mqtt"], "poll_interval_seconds": 30},
    })
    monkeypatch.setattr(app_modul, "EcoFlowClient", ZaehlClient)
    monkeypatch.setattr(app_modul, "_ensure_connected", _nichts_tun)
    monkeypatch.setattr(app_modul, "_fill_missing_models", _nichts_tun)
    monkeypatch.setattr(app_modul.asyncio, "sleep", schlafe)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app_modul._supervisor_loop())

    # 60 s / 5 s = 12 Durchgaenge, davon duerfen nur die bei 0 und 30 einen
    # Resync ausloesen.
    assert FakeZeit.jetzt >= 60
    assert abrufe["n"] == 2, f"erwartet 2 Resyncs in 60 s, waren {abrufe['n']}"


async def _nichts_tun(*_a, **_k):
    return None


def _ein_resync_mit_fehler(monkeypatch, fehler):
    """Laesst die Aufsichtsschleife genau einen Resync machen, der scheitert.

    Gibt zurueck, fuer welche Seriennummern _publish_state() dabei lief."""
    veroeffentlicht: list[str] = []

    class FehlerClient:
        def __init__(self, *_a, **_k):
            pass

        async def get_quota_all(self, _sn):
            raise fehler

    async def schlafe(_sekunden):
        raise asyncio.CancelledError  # nach dem ersten Durchgang aussteigen

    # Ohne bekannten Zustand veroeffentlicht die Schleife bewusst nichts -
    # es gaebe ja auch nichts zu melden.
    app_modul._state["SN1"] = {"sn": "SN1"}

    monkeypatch.setattr(app_modul, "load_config", lambda: CONFIG)
    monkeypatch.setattr(app_modul, "EcoFlowClient", FehlerClient)
    monkeypatch.setattr(app_modul, "_ensure_connected", _nichts_tun)
    monkeypatch.setattr(app_modul, "_fill_missing_models", _nichts_tun)
    monkeypatch.setattr(app_modul, "_publish_state", veroeffentlicht.append)
    monkeypatch.setattr(app_modul.asyncio, "sleep", schlafe)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(app_modul._supervisor_loop())
    return veroeffentlicht


@pytest.mark.parametrize(
    "fehler",
    [
        app_modul.EcoFlowAuthError("EcoFlow-Auth-Fehler: accessKey is invalid"),
        OSError("[Errno -3] Temporary failure in name resolution"),
    ],
    ids=["auth", "netz"],
)
def test_jeder_resync_fehler_veroeffentlicht_den_zustand(monkeypatch, fehler):
    """Beide Fehlerarten muessen den Zustand neu veroeffentlichen.

    Vorgeschichte (16.08.2026): Es gab zwei Zweige, und nur der fuer
    Netzfehler rief _publish_state(). Beim Wechsel der EcoFlow-Schluessel
    liefen sieben Minuten mit dem alten Paar - im Protokoll alle 30 s
    "accessKey is invalid", auf dem lokalen Broker unveraendert
    `available = online`. Und dabei waere es geblieben: _publish_state() ist
    die einzige Stelle, die OFFLINE_AFTER_SECONDS auswertet.

    Der Test laeuft ueber BEIDE Fehlerarten, damit sie nicht wieder
    auseinanderlaufen koennen - ein Test nur fuer den Auth-Fall haette den
    naechsten neuen Zweig genauso wenig bemerkt."""
    assert _ein_resync_mit_fehler(monkeypatch, fehler) == ["SN1"]


def test_resync_fehler_wird_als_geraetefehler_gemerkt(monkeypatch):
    """Gegenprobe: Der Fehlertext muss auch in /api/state ankommen.

    Sonst stuende in der Oberflaeche zwar "offline", aber ohne den Grund -
    und der Grund ist hier das Einzige, was weiterhilft."""
    _ein_resync_mit_fehler(monkeypatch, app_modul.EcoFlowAuthError("accessKey is invalid"))
    assert "accessKey is invalid" in app_modul._device_errors["SN1"]


def test_stehende_verbindung_wird_nicht_neu_aufgebaut(monkeypatch):
    """Gegenprobe: Sonst haetten wir aus dem Nachholen einen Dauer-Reconnect
    gemacht - alle paar Sekunden eine neue Verbindung, und die Abos waeren
    staendig weg."""
    gebaut = {"bridge": 0, "listener": 0}

    class ZaehlBridge(FakeBridge):
        def __init__(self, *a, **k):
            gebaut["bridge"] += 1

    class ZaehlListener(FakeListener):
        def __init__(self, *a, **k):
            gebaut["listener"] += 1

    monkeypatch.setattr(app_modul, "MqttBridge", ZaehlBridge)
    monkeypatch.setattr(app_modul, "EcoFlowMqttListener", ZaehlListener)
    monkeypatch.setattr(app_modul, "EcoFlowClient", _ecoflow_client([False, False, False]))

    for _ in range(3):
        asyncio.run(app_modul._ensure_connected(CONFIG))

    assert gebaut == {"bridge": 1, "listener": 1}

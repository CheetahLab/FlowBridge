"""Alter der Messwerte: Wie alt ist die Zahl, die im Dashboard steht?

Anlass (23.08.2026, Feldtest): Ladeleistung von 100 auf 200 W gestellt, das
Geraet regelte nachweislich hoch - AC-Eingang und Batterieleistung blieben
trotzdem auf den alten Zahlen stehen. Im Protokoll lagen zwischen zwei
invStatus-Pushes 10 Minuten 24 Sekunden, und die rund zwanzig REST-Abfragen
dazwischen lieferten alle denselben alten Wert: quota/all ist die Kopie des
letzten Push, keine eigene Messung.

Festgenagelt wird hier deshalb vor allem die Quellenregel - sie ist der
Unterschied zwischen einer brauchbaren und einer nutzlosen Altersanzeige.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import app  # noqa: E402
from mqtt_bridge import MqttBridge  # noqa: E402

SN = "TEST-ALTER-0001"
CFG = {
    "host": "127.0.0.1",
    "port": 1883,
    "client_id": "flowbridge-test",
    "base_topic": "flowbridge",
    "retain": True,
}


class FakeClient:
    """Ersetzt den paho-Client - nichts geht ins Netz."""

    def __init__(self):
        self.veroeffentlicht: list[tuple[str, str, bool]] = []

    def publish(self, topic, payload="", retain=False):
        self.veroeffentlicht.append((topic, payload, retain))


@pytest.fixture(autouse=True)
def sauber():
    for speicher in (app._quota_cache, app._field_times, app._field_sources, app._state, app._history):
        speicher.pop(SN, None)
    yield
    for speicher in (app._quota_cache, app._field_times, app._field_sources, app._state, app._history):
        speicher.pop(SN, None)


def _alt_stempeln(sn: str, sekunden: float) -> None:
    """Alle bekannten Rohfelder kuenstlich altern lassen."""
    zeiten = app._field_times.setdefault(sn, {})
    for key in zeiten:
        zeiten[key] = time.time() - sekunden


# ------------------------------------------------------------- Quellenregel

def test_push_macht_frisch_auch_bei_gleichem_wert():
    """Ein Push IST die Nachricht - auch 'immer noch 0 W' ist eine Aussage."""
    app._frische_merken(SN, {"inv.inputWatts": 0}, from_push=True)
    app._quota_cache[SN] = {"inv.inputWatts": 0}
    _alt_stempeln(SN, 300)

    app._frische_merken(SN, {"inv.inputWatts": 0}, from_push=True)

    assert app._field_times[SN]["inv.inputWatts"] > time.time() - 5


def test_rest_mit_gleichem_wert_macht_nicht_frisch():
    """Der Kern: quota/all spiegelt nur den letzten Push.

    Ohne diese Regel stuende die Altersanzeige alle 30 Sekunden wieder auf
    null, waehrend die Zahl daneben unveraendert alt bliebe.
    """
    app._frische_merken(SN, {"inv.inputWatts": 105}, from_push=True)
    app._quota_cache[SN] = {"inv.inputWatts": 105}
    _alt_stempeln(SN, 600)
    vorher = app._field_times[SN]["inv.inputWatts"]

    app._frische_merken(SN, {"inv.inputWatts": 105}, from_push=False)

    assert app._field_times[SN]["inv.inputWatts"] == vorher


def test_rest_mit_geaendertem_wert_macht_frisch():
    """Ein geaenderter Wert ist echte neue Information - etwa ein Push, den
    wir waehrend eines Verbindungsabbruchs verpasst haben."""
    app._frische_merken(SN, {"inv.inputWatts": 105}, from_push=True)
    app._quota_cache[SN] = {"inv.inputWatts": 105}
    _alt_stempeln(SN, 600)

    app._frische_merken(SN, {"inv.inputWatts": 205}, from_push=False)

    assert app._field_times[SN]["inv.inputWatts"] > time.time() - 5


def test_unbekanntes_feld_per_rest_gilt_als_frisch():
    """Beim Start liegt nur quota/all vor - dann ist der erste Wert alles,
    was es gibt, und darf nicht sofort als veraltet dastehen."""
    app._frische_merken(SN, {"inv.inputWatts": 105}, from_push=False)
    assert app._field_times[SN]["inv.inputWatts"] > time.time() - 5


# ----------------------------------------------------------------- Zuordnung

def test_alter_haengt_an_der_metrik_ueber_das_rohfeld():
    app._apply_quota_update(SN, {"inv.inputWatts": 105, "pd.soc": 4}, from_push=True)
    _alt_stempeln(SN, 400)
    app._apply_quota_update(SN, {"pd.soc": 5}, from_push=True)

    alter = app._messalter(SN)
    assert alter["ac_watts_in"] >= 400
    assert alter["soc_percent"] < 5


def test_sollwerte_altern_nicht():
    """Ladelimit & Co. aendern sich nur, wenn jemand sie aendert - ein
    'veraltet' waere dort Laerm ohne Aussage."""
    app._apply_quota_update(
        SN, {"bms_emsStatus.maxChargeSoc": 100, "mppt.cfgAcOutVol": 230}, from_push=True
    )
    alter = app._messalter(SN)
    assert "charge_limit_percent" not in alter
    assert "ac_output_voltage" not in alter


# ------------------------------------------------------------ Linienschreiber

def test_verlauf_zeichnet_veraltete_werte_nicht_weiter():
    """Sonst wird aus einer Meldeluecke eine schnurgerade Linie - aus
    'wir wissen es nicht' also 'es war konstant so'."""
    app._apply_quota_update(SN, {"inv.inputWatts": 105, "pd.soc": 4}, from_push=True)
    _alt_stempeln(SN, app.MESSWERT_ALTER_S + 60)
    app._history.pop(SN, None)
    app._publish_state(SN)

    punkt = app._history[SN][-1]
    assert "ac_watts_in" not in punkt
    assert "soc_percent" not in punkt


def test_verlauf_zeichnet_frische_werte():
    app._apply_quota_update(SN, {"inv.inputWatts": 205}, from_push=True)
    app._history.pop(SN, None)
    app._publish_state(SN)

    assert app._history[SN][-1]["ac_watts_in"] == 205


def test_status_traegt_das_alter_mit():
    """Auch fuer EisBaer und Home Assistant: derselbe Befund wie im Dashboard."""
    app._apply_quota_update(SN, {"inv.inputWatts": 205}, from_push=True)
    assert "ac_watts_in" in app._state[SN]["_alter_s"]


def test_alter_bekommt_kein_eigenes_einzelwert_topic():
    """Im state-JSON ja, als eigenes Topic nein.

    Sonst haette jeder Messwert ein zweites Topic daneben, dessen Inhalt sich
    im Sekundentakt aendert - retained, wohlgemerkt.
    """
    app._apply_quota_update(SN, {"inv.inputWatts": 205}, from_push=True)
    status = app._state[SN]
    assert "ac_watts_in" in status["_alter_s"]

    bridge = MqttBridge(CFG)
    bridge._client = FakeClient()
    bridge.publish_state(SN, status, status.get("_modules"))

    topics = [topic for topic, _payload, _retain in bridge._client.veroeffentlicht]
    assert f"flowbridge/{SN}/status/ac_watts_in" in topics
    assert not any("_alter_s" in topic for topic in topics)

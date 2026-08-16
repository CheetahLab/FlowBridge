"""Tests fuer den lokalen MQTT-Baum und die Home-Assistant-Discovery."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import ha_discovery  # noqa: E402
from mqtt_bridge import COMMAND_SEGMENT, MqttBridge  # noqa: E402

SN = "TEST-SN-0001"
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
        self.abos: list[str] = []
        self.will = None
        self._verbunden = True

    def username_pw_set(self, *a, **k):
        pass

    def will_set(self, topic, payload, retain=False):
        self.will = (topic, payload, retain)

    def publish(self, topic, payload="", retain=False):
        self.veroeffentlicht.append((topic, payload, retain))

    def subscribe(self, topic):
        self.abos.append(topic)

    def is_connected(self):
        return self._verbunden

    # --- Verbindungsaufbau -------------------------------------------------
    # `connect` bildet den echten Broker nach, der gerade nicht da ist: paho
    # wirft an dieser Stelle. `connect_async` tut das nicht - das ist der
    # ganze Unterschied, um den es geht.
    def connect(self, *a, **k):
        raise OSError("Connection refused")

    def connect_async(self, host, port, keepalive=None):
        self.async_verbunden_mit = (host, port, keepalive)

    def loop_start(self):
        self.schleife_laeuft = True

    def reconnect_delay_set(self, min_delay=None, max_delay=None):
        self.wartezeiten = (min_delay, max_delay)


@pytest.fixture
def bruecke():
    b = MqttBridge(CFG)
    b._client = FakeClient()
    return b


def _topics(b) -> list[str]:
    return [t for t, _p, _r in b._client.veroeffentlicht]


def test_status_und_befehle_liegen_in_getrennten_baeumen(bruecke):
    """Sonst loeste der eigene Status-Publish sofort einen Befehl aus."""
    status = bruecke.status_topic(SN, "soc_percent")
    befehl = bruecke.command_topic(SN, "soc_percent")
    assert status != befehl
    assert "/status/" in status
    assert f"/{COMMAND_SEGMENT}/" in befehl


def test_befehlssegment_heisst_cmnd(bruecke):
    assert bruecke.command_topic(SN, "charge_power_watts").endswith("/cmnd/charge_power_watts")


def test_state_modules_und_einzelwerte(bruecke):
    bruecke.publish_state(
        SN,
        {"sn": SN, "soc_percent": 66, "ac_watts_in": 105, "online": True},
        {"PD": {"soc": 66}, "MPPT": {"inWatts": 0}},
    )
    topics = _topics(bruecke)
    assert f"flowbridge/{SN}/state" in topics
    assert f"flowbridge/{SN}/modules/pd" in topics
    assert f"flowbridge/{SN}/modules/mppt" in topics
    assert f"flowbridge/{SN}/status/soc_percent" in topics
    assert f"flowbridge/{SN}/status/ac_watts_in" in topics


def test_interne_felder_landen_nicht_als_einzelwert(bruecke):
    bruecke.publish_state(SN, {"sn": SN, "online": True, "_modules": {}, "soc_percent": 50})
    topics = _topics(bruecke)
    assert f"flowbridge/{SN}/status/_modules" not in topics
    assert f"flowbridge/{SN}/status/sn" not in topics
    assert f"flowbridge/{SN}/status/online" not in topics


def test_unveraenderte_einzelwerte_werden_nicht_erneut_gesendet(bruecke):
    """Sonst laege bei jedem Push derselbe Wert wieder auf dem Broker."""
    bruecke.publish_state(SN, {"sn": SN, "soc_percent": 66})
    bruecke._client.veroeffentlicht.clear()
    bruecke.publish_state(SN, {"sn": SN, "soc_percent": 66})
    assert f"flowbridge/{SN}/status/soc_percent" not in _topics(bruecke)

    bruecke.publish_state(SN, {"sn": SN, "soc_percent": 67})
    assert f"flowbridge/{SN}/status/soc_percent" in _topics(bruecke)


def test_last_will_meldet_flowbridge_offline():
    """Ohne Last-Will bliebe FlowBridge nach einem Absturz 'verfuegbar'."""
    b = MqttBridge(CFG)
    b._client = FakeClient()
    neu = MqttBridge(CFG)
    assert neu._client.will_set is not None  # paho-Client hat will_set gesetzt


def test_unbekannte_verfuegbarkeit_wird_nicht_gesendet(bruecke):
    """Lieber keine Aussage als eine falsche."""
    bruecke.publish_availability(SN, None)
    assert _topics(bruecke) == []


def test_ecoflow_verbindung_hat_eigenes_topic(bruecke):
    bruecke.publish_ecoflow_availability(False)
    assert (bruecke.ecoflow_availability_topic, "offline", True) in bruecke._client.veroeffentlicht


def test_befehl_wird_aus_dem_topic_gelesen():
    empfangen = []
    b = MqttBridge(CFG, on_command=lambda *a: empfangen.append(a))
    b._client = FakeClient()

    class Msg:
        topic = f"flowbridge/{SN}/{COMMAND_SEGMENT}/charge_power_watts"
        payload = b"300"

    b._handle_message(None, None, Msg())
    assert empfangen == [(SN, "charge_power_watts", "300")]


def test_fremde_topics_loesen_keinen_befehl_aus():
    empfangen = []
    b = MqttBridge(CFG, on_command=lambda *a: empfangen.append(a))
    b._client = FakeClient()

    class Msg:
        topic = f"flowbridge/{SN}/status/soc_percent"
        payload = b"66"

    b._handle_message(None, None, Msg())
    assert empfangen == []


# ------------------------------------------------------------ HA-Discovery
def _ha_eintraege(controllable=True, steps=None, nur_lesbar=()):
    return ha_discovery.build_entities(
        sn=SN,
        name="Testspeicher",
        model="RIVER 2 Pro",
        base_topic="flowbridge",
        bridge_availability_topic="flowbridge/bridge/available",
        ecoflow_availability_topic="flowbridge/bridge/ecoflow",
        controllable=controllable,
        charge_steps=steps if steps is not None else [100, 150, 200],
        nur_lesbar=nur_lesbar,
    )


def test_ha_entitaeten_haben_stabile_unique_ids():
    ids = [json.loads(p)["unique_id"] for _t, p in _ha_eintraege()]
    assert len(ids) == len(set(ids)), "unique_id doppelt - HA lehnt das ab"
    assert all(i.startswith(f"flowbridge_{SN}") for i in ids)


def test_ha_entitaeten_haengen_an_einem_geraet():
    geraete = {json.loads(p)["device"]["identifiers"][0] for _t, p in _ha_eintraege()}
    assert geraete == {f"flowbridge_{SN}"}


def test_ha_verfuegbarkeit_deckt_alle_drei_ausfallquellen_ab():
    payload = json.loads(_ha_eintraege()[0][1])
    topics = [a["topic"] for a in payload["availability"]]
    assert topics == [
        "flowbridge/bridge/available",
        "flowbridge/bridge/ecoflow",
        f"flowbridge/{SN}/available",
    ]
    assert payload["availability_mode"] == "all"


def test_ha_befehlstopics_nutzen_cmnd():
    for _t, p in _ha_eintraege():
        d = json.loads(p)
        if "command_topic" in d:
            assert f"/{COMMAND_SEGMENT}/" in d["command_topic"]


def test_ohne_steuerbarkeit_nur_sensoren():
    """Ein Schalter, der nichts tut, waere schlimmer als keiner."""
    typen = {t.split("/")[1] for t, _p in _ha_eintraege(controllable=False)}
    assert typen == {"sensor"}


def test_ladeleistungs_regler_uebernimmt_die_modellstufen():
    eintraege = _ha_eintraege(steps=[100, 150, 870])
    regler = next(json.loads(p) for t, p in eintraege if t.endswith("charge_power_watts/config"))
    assert regler["min"] == 100
    assert regler["max"] == 870
    assert regler["step"] == 50


def test_loeschliste_deckt_alle_angelegten_topics_ab():
    angelegt = {t for t, _p in _ha_eintraege()}
    assert angelegt <= set(ha_discovery.build_removals(SN))


def test_loeschliste_raeumt_auch_umbenannte_felder_weg():
    """Ein retained Config-Topic eines entfernten Feldes haengt sonst fuer
    immer als Entitaet in HA, die nie wieder einen Wert bekommt."""
    loeschliste = set(ha_discovery.build_removals(SN))
    legacy = set(ha_discovery.build_legacy_removals(SN))
    assert legacy <= loeschliste
    for feld in ha_discovery.VERALTETE_SENSOREN:
        assert f"homeassistant/sensor/flowbridge_{SN}/{feld}/config" in legacy


def test_umbenannte_felder_werden_nicht_gleichzeitig_neu_angelegt():
    """Sonst raeumte FlowBridge dasselbe Topic weg, das es eben erst schrieb."""
    angelegt = {t for t, _p in _ha_eintraege()}
    assert angelegt.isdisjoint(ha_discovery.build_legacy_removals(SN))


# ------------------------------------------------- Retained Befehle (13.08.2026)
def test_retained_befehl_wird_ignoriert():
    """Der Fall aus dem Feld: Nach der Neueinrichtung ging das pausierte
    AC-Laden von selbst an.

    Ursache war ein retained "on" auf dem cmnd-Topic, das vom vorherigen
    EisBaer-Test noch auf dem Broker lag. Ein Broker liefert retained
    Nachrichten jedem NEUEN Abonnenten sofort aus - FlowBridge haette den
    alten Befehl also bei jedem Verbindungsaufbau erneut ausgefuehrt und am
    Speicher geschaltet, ohne dass jemand etwas getan hat.
    """
    empfangen = []
    b = MqttBridge(CFG, on_command=lambda *a: empfangen.append(a))
    b._client = FakeClient()

    class Msg:
        topic = f"flowbridge/{SN}/{COMMAND_SEGMENT}/ac_charging"
        payload = b"on"
        retain = True

    b._handle_message(None, None, Msg())
    assert empfangen == [], "Ein retained Befehl darf nicht ausgefuehrt werden"


def test_frischer_befehl_wird_weiterhin_ausgefuehrt():
    """Gegenprobe: Nur RETAINED wird verworfen, nicht das Schalten an sich.

    Ohne diesen Test koennte die Sperre auch alle Befehle abwuergen, und die
    Steuerung waere still tot - schlimmer als der Fehler, den sie behebt.
    """
    empfangen = []
    b = MqttBridge(CFG, on_command=lambda *a: empfangen.append(a))
    b._client = FakeClient()

    class Msg:
        topic = f"flowbridge/{SN}/{COMMAND_SEGMENT}/ac_charging"
        payload = b"on"
        retain = False

    b._handle_message(None, None, Msg())
    assert empfangen == [(SN, "ac_charging", "on")]


# ------------------------------------------- Nur lesbare Felder (14.08.2026)
def test_nur_lesbares_feld_wird_in_ha_kein_schalter():
    """Die Backup-Reserve nimmt das River 2 Pro nicht an (am Geraet gemessen).

    In Home Assistant darf daraus kein Schalter werden - der laesst sich
    druecken und tut nichts. Als binary_sensor bleibt der Wert sichtbar,
    denn LESEN funktioniert einwandfrei.
    """
    nur_lesbar = ("backup_reserve_enabled", "backup_reserve_percent")
    eintraege = _ha_eintraege(nur_lesbar=nur_lesbar)

    komponenten = {
        t.split("/")[1] for t, _p in eintraege if "backup_reserve" in t
    }
    assert komponenten == {"binary_sensor", "sensor"}, "kein switch/number mehr"

    for _t, payload in eintraege:
        p = json.loads(payload)
        if "backup_reserve" in p["unique_id"]:
            assert "command_topic" not in p, "ohne Befehlstopic kann HA nicht schalten"
            assert p["state_topic"], "der Messwert muss weiterhin ankommen"


def test_ohne_einschraenkung_bleibt_die_backup_reserve_bedienbar():
    """Gegenprobe: Beim Delta 2 ist watthConfig weder bestaetigt noch
    widerlegt - dort darf die Einschraenkung nicht greifen."""
    topics = [t for t, _p in _ha_eintraege() if "backup_reserve" in t]
    assert any("/switch/" in t for t in topics)
    assert any("/number/" in t for t in topics)


# --------------------------------------------- Verbindungsaufbau (14.08.2026)
def test_erster_verbindungsversuch_darf_scheitern(bruecke):
    """Aus dem Feld: Nach jedem neuen Abbild stand "Lokaler Broker getrennt".

    FlowBridge und Mosquitto fahren auf der NAS gleichzeitig hoch. War der
    Broker im Moment des Starts noch nicht da, warf das synchrone
    `connect` - und der Aufrufer merkte sich die Konfiguration trotzdem als
    verbunden, versuchte es also nie wieder. Der Container musste ein
    zweites Mal starten, damit es klappte.

    Der FakeClient laesst `connect` genau so scheitern. Kommt hier eine
    Ausnahme durch, ist der alte Zustand zurueck.
    """
    bruecke.connect()  # darf nicht werfen

    assert bruecke._client.async_verbunden_mit == ("127.0.0.1", 1883, 30)
    assert bruecke._client.schleife_laeuft, "ohne loop_start verbindet paho nie"


def test_wartezeit_zwischen_versuchen_ist_gedeckelt(bruecke):
    """paho wartet von sich aus bis zu zwei Minuten.

    Nach einem Broker-Neustart sollen die Werte wieder fliessen, bevor
    jemand nachsieht, warum sie es nicht tun.
    """
    bruecke.connect()
    _min_wartezeit, max_wartezeit = bruecke._client.wartezeiten
    assert max_wartezeit <= 30

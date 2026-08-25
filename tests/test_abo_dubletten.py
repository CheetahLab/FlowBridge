"""
Nach einer Abo-Erneuerung darf jede Nachricht GENAU EINMAL ankommen.

Vorgeschichte (25.08.2026, im Feld gemessen): Die erste planmaessige
Erneuerung nach 12 h lief sauber - 457 ms, keine verpasste Nachricht. Ab
diesem Moment kam aber jede Nachricht doppelt: 799 Nutzlasten zweimal,
jeweils im selben Millisekundenwert. Zwei getrennte Sitzungen treffen nicht
799-mal dieselbe Millisekunde; es war ein Lieferweg mit zwei Abonnements auf
demselben Topic.

Zwei Ursachen kamen dafuer in Frage, beide sind hier festgenagelt:

1. `disconnect()` hielt erst den Netzwerk-Thread an und meldete dann ab -
   also nie. Der Broker liess die alte Sitzung offen stehen und legte sie
   beim Neuverbinden unter derselben Client-ID mit der neuen zusammen,
   ihr Abonnement inbegriffen.
2. Zum `subscribe` fuehren zwei Wege: `subscribe_device()` aus dem
   asyncio-Loop und `_handle_connect()` aus dem paho-Netzwerk-Thread. Faellt
   der Verbindungszustand dazwischen um, laufen beide - und manche Broker
   liefern dann doppelt aus.

Der Test kennt keinen echten Broker. Er prueft, was FlowBridge selbst in der
Hand hat: die Reihenfolge der Abbau-Schritte und die Zahl der abgesetzten
subscribe-Aufrufe.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ecoflow_client import MqttCertificate  # noqa: E402
import ecoflow_mqtt  # noqa: E402


class FakePahoClient:
    """Merkt sich, was in welcher Reihenfolge gerufen wurde."""

    def __init__(self, *_a, **_k):
        self.ablauf: list[str] = []
        self.abos: list[str] = []
        self._verbunden = False
        self.on_message = None
        self.on_connect = None
        self.on_disconnect = None

    # --- von FlowBridge benutzt ---
    def username_pw_set(self, *_a, **_k):
        pass

    def tls_set(self, *_a, **_k):
        pass

    def reconnect_delay_set(self, *_a, **_k):
        pass

    def connect_async(self, *_a, **_k):
        self.ablauf.append("connect_async")

    def loop_start(self):
        self.ablauf.append("loop_start")

    def loop_stop(self):
        self.ablauf.append("loop_stop")

    def disconnect(self):
        self.ablauf.append("disconnect")
        self._verbunden = False

    def is_connected(self):
        return self._verbunden

    def subscribe(self, topic):
        self.abos.append(topic)

    # --- Testhilfe ---
    def verbindung_steht(self):
        self._verbunden = True


@pytest.fixture
def listener(monkeypatch):
    erzeugte: list[FakePahoClient] = []

    def fake_client(*a, **k):
        c = FakePahoClient()
        erzeugte.append(c)
        return c

    monkeypatch.setattr(ecoflow_mqtt.mqtt, "Client", fake_client)
    cert = MqttCertificate(
        url="broker.example", port=8883, protocol="mqtts",
        account="ACC1234567890", password="PW",
    )
    hoerer = ecoflow_mqtt.EcoFlowMqttListener(cert, on_quota=lambda *_: None)
    return hoerer, erzeugte[0]


def test_disconnect_meldet_ab_bevor_der_thread_endet(listener):
    """Umgekehrt geht das DISCONNECT-Paket nie raus - genau der Feldfehler."""
    hoerer, paho = listener
    hoerer.disconnect()
    assert paho.ablauf == ["disconnect", "loop_stop"]


def test_subscribe_device_und_connect_doppeln_sich_nicht(listener):
    """Beide Wege zusammen ergeben trotzdem EIN Abonnement je Topic."""
    hoerer, paho = listener
    hoerer.connect()
    paho.verbindung_steht()

    # Weg 1: Geraet wird angemeldet, waehrend die Verbindung schon steht.
    hoerer.subscribe_device("SN1")
    # Weg 2: das CONNACK trifft (verspaetet) ein und loest _handle_connect aus.
    hoerer._handle_connect(paho, None, None, 0)

    assert sorted(paho.abos) == [
        "/open/ACC1234567890/SN1/quota",
        "/open/ACC1234567890/SN1/status",
    ]


def test_nach_verbindungsabbruch_wird_wieder_abonniert(listener):
    """Die Sperre darf ein echtes Neu-Abonnieren nicht verhindern."""
    hoerer, paho = listener
    hoerer.connect()
    paho.verbindung_steht()
    hoerer.subscribe_device("SN1")
    assert len(paho.abos) == 2

    # Verbindung bricht weg, paho verbindet neu.
    hoerer._handle_disconnect(paho, None, None, 1)
    hoerer._handle_connect(paho, None, None, 0)

    assert len(paho.abos) == 4, "nach einem Abbruch muss neu abonniert werden"


def test_zweites_connack_ohne_abbruch_doppelt_nicht(listener):
    """Ein zweites CONNACK ohne zwischenzeitlichen Abbruch fuegt nichts hinzu."""
    hoerer, paho = listener
    hoerer.connect()
    paho.verbindung_steht()
    hoerer.subscribe_device("SN1")
    vorher = len(paho.abos)
    assert vorher == 2

    hoerer._handle_connect(paho, None, None, 0)
    assert len(paho.abos) == vorher


def test_abgelehnte_verbindung_abonniert_nicht(listener):
    """reason_code != 0 heisst: keine Sitzung, also auch kein subscribe."""
    hoerer, paho = listener
    hoerer.subscribe_device("SN1")   # noch nicht verbunden -> nur vormerken
    hoerer._handle_connect(paho, None, None, 5)
    assert paho.abos == []

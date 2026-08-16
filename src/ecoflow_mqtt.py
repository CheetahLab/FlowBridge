"""
Live-Anbindung an den EcoFlow-eigenen MQTT-Broker fuer Echtzeit-Updates.

REST-Polling (ecoflow_client.get_quota_all) ist zuverlaessig, aber traege -
in der Praxis (12.08.2026 beobachtet) kann es >1 Minute dauern, bis eine
Aenderung dort sichtbar wird. Der MQTT-Push vom Geraet an die App ist dagegen
nahezu in Echtzeit. FlowBridge nutzt REST weiterhin fuer den initialen
Vollzustand und fuer Set-Commands, aber Live-Updates kommen ab jetzt primaer
ueber diese MQTT-Verbindung; die REST-Poll-Schleife bleibt als traeger
Sicherheitsnetz (falls die MQTT-Verbindung kurz haengt oder ein Feld nicht
gepusht wird).

Nachrichtenformat laut Dev-Portal-Doku: jede quota-Message traegt EINEN
Modul-Ausschnitt (typeCode) mit un-praefigierten Feldnamen, z.B.
{"typeCode": "pdStatus", "params": {"wattsOutSum": 0, ...}}. Um sie in
dieselbe Notation wie quota/all zu bringen (z.B. "pd.wattsOutSum"), wird der
Praefix aus typeCode abgeleitet.
"""
from __future__ import annotations

import json
import logging
import ssl
from typing import Callable

import paho.mqtt.client as mqtt

from config import instanz_id
from ecoflow_client import MqttCertificate

logger = logging.getLogger(__name__)

_TYPECODE_PREFIX = {
    "pdStatus": "pd.",
    "bmsStatus": "bms_bmsStatus.",
    "emsStatus": "bms_emsStatus.",
    "mpptStatus": "mppt.",
    "invStatus": "inv.",
}

# (sn, praefigierte Teil-Quota) -> None. Wird aus dem paho-Netzwerk-Thread
# aufgerufen (loop_start), nicht aus dem asyncio-Event-Loop.
QuotaCallback = Callable[[str, dict], None]
# (sn, online) -> None, aus dem /status-Topic.
StatusCallback = Callable[[str, bool], None]


class EcoFlowMqttListener:
    """Ein Client pro EcoFlow-Account (certificateAccount), mehrere Geraete gleichzeitig."""

    def __init__(
        self, cert: MqttCertificate, on_quota: QuotaCallback, on_status: StatusCallback | None = None
    ) -> None:
        self._cert = cert
        self._on_quota = on_quota
        self._on_status = on_status
        self._subscribed_sns: set[str] = set()
        # Client-ID: Account-Fragment fuer die Zuordnung, dazu die Kennung
        # DIESER Installation.
        #
        # Der Zusatz ist nicht kosmetisch: Ohne ihn trugen zwei FlowBridges am
        # selben EcoFlow-Konto exakt dieselbe ID - etwa eine auf der NAS und
        # eine zum Entwickeln. Der Broker wirft bei gleicher ID den aelteren
        # Client hinaus, also haetten sich die beiden im Sekundentakt
        # gegenseitig abgemeldet. Genau der Fall, der bei zwei Instanzen am
        # selben Speicher auftritt.
        #
        # Account-Anteil auf 10 Zeichen gekuerzt, damit die ID trotz Zusatz
        # nicht laenger wird als bisher.
        self._client = mqtt.Client(
            client_id=f"flowbridge-{cert.account[-10:]}-{instanz_id()}",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self._client.username_pw_set(cert.account, cert.password)
        if cert.protocol == "mqtts":
            self._client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        self._client.on_message = self._handle_message
        self._client.on_disconnect = self._handle_disconnect
        self._client.on_connect = self._handle_connect

    def connect(self) -> None:
        """Wie MqttBridge.connect: Der erste Versuch darf danebengehen.

        `connect_async` wirft nicht, `loop_start` baut die Verbindung im
        Hintergrund auf und stellt sie nach jedem Abbruch wieder her - ein
        Mechanismus fuer Erstverbindung und Reconnect statt nur fuer den
        zweiten Fall.

        Hier zaehlt das doppelt: Diese Verbindung geht ueber das Internet
        zu EcoFlow, ist also stoerungsanfaelliger als der Broker im eigenen
        Netz. Am 14.08.2026 stand nach einem Abbild-Wechsel auf der NAS
        "EcoFlow-Broker getrennt", waehrend der lokale Broker (der den Fix
        schon hatte) laengst verbunden war.
        """
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.connect_async(self._cert.url, self._cert.port, keepalive=30)
        self._client.loop_start()

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def is_connected(self) -> bool:
        """Aktueller Verbindungszustand zum EcoFlow-Broker (fuer die Statusanzeige)."""
        return self._client.is_connected()

    def subscribe_device(self, sn: str) -> None:
        # WICHTIG: subscribe() darf erst NACH einem erfolgreichen on_connect
        # gerufen werden - vorher (z.B. direkt nach connect(), waehrend
        # loop_start() den Handshake noch im Hintergrund macht) schlaegt es
        # mit MQTT_ERR_NO_CONN fehl und wird NICHT automatisch nachgeholt.
        # Deshalb hier merken und in _handle_connect (erneut) abonnieren -
        # das deckt auch Reconnects nach Verbindungsabbruch ab.
        self._subscribed_sns.add(sn)
        if self._client.is_connected():
            self._do_subscribe(sn)

    def _do_subscribe(self, sn: str) -> None:
        self._client.subscribe(f"/open/{self._cert.account}/{sn}/quota")
        self._client.subscribe(f"/open/{self._cert.account}/{sn}/status")

    def _handle_connect(self, _client, _userdata, _flags, reason_code, _properties=None) -> None:
        if reason_code != 0:
            logger.error("EcoFlow-MQTT-Verbindung abgelehnt (Code %s).", reason_code)
            return
        logger.info("EcoFlow-MQTT verbunden, abonniere %s Geraet(e).", len(self._subscribed_sns))
        for sn in self._subscribed_sns:
            self._do_subscribe(sn)

    def _handle_disconnect(self, _client, _userdata, _flags, reason_code, _properties=None) -> None:
        if reason_code != 0:
            logger.warning("EcoFlow-MQTT-Verbindung getrennt (Code %s) - paho versucht Reconnect.", reason_code)

    def _handle_message(self, _client, _userdata, msg) -> None:
        logger.debug("EcoFlow-MQTT-Nachricht auf %s: %s", msg.topic, msg.payload[:300])
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            logger.warning("Ungueltige EcoFlow-MQTT-Payload auf %s: %s", msg.topic, exc)
            return

        # Topic: /open/{account}/{sn}/quota  oder  /open/{account}/{sn}/status
        parts = msg.topic.split("/")
        if len(parts) < 4:
            return
        sn = parts[3]

        if msg.topic.endswith("/status"):
            # Reines EVENT-Topic: feuert nur beim Wechsel online<->offline, nicht
            # periodisch (12.08.2026 verifiziert: 150s abonniert bei durchgehend
            # online-Geraet = 0 Nachrichten). Ein Ausbleiben heisst also NICHT
            # offline - siehe Staleness-Fallback in app.py.
            status = payload.get("params", {}).get("status")
            if status is not None and self._on_status:
                logger.info("Geraet %s meldet Status %s", sn, status)
                self._on_status(sn, bool(status))
            return

        type_code = payload.get("typeCode", "")
        prefix = _TYPECODE_PREFIX.get(type_code)
        params = payload.get("params")
        if not prefix or not isinstance(params, dict):
            return

        prefixed = {f"{prefix}{key}": value for key, value in params.items()}
        self._on_quota(sn, prefixed)

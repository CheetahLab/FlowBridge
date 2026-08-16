"""
Anbindung an den lokalen MQTT-Broker (EisBaer / Mosquitto / Home Assistant / ...).

Kennt nur neutrale Status-Dicts (aus device.normalize_quota) - keine
EcoFlow-Spezifika.

Topic-Schema (base_topic ist konfigurierbar, Default "flowbridge"):

  {base}/bridge/available          online|offline   Last-Will von FlowBridge selbst
  {base}/{sn}/available            online|offline   Erreichbarkeit des Geraets
  {base}/{sn}/state                JSON             alle normalisierten Werte
  {base}/{sn}/modules/{pd|bms|ems|inv|mppt}
                                   JSON             Rohwerte je EcoFlow-Modul
  {base}/{sn}/status/{feld}        Einzelwert       je Messwert ein Topic
  {base}/{sn}/cmnd/{property}      <- eingehend     Steuerbefehle
  {base}/bridge/ecoflow            online|offline   Verbindung zur EcoFlow-Cloud

Bewusste Entscheidungen:

- cmnd/ und status/ liegen in GETRENNTEN Unterbaeumen. Laegen sie zusammen,
  wuerde der eigene Status-Publish sofort wieder als Befehl zurueckkommen.
- Einzelwerte werden nur bei AENDERUNG gesendet. Sonst laegen bei jedem
  Push (alle paar Sekunden) dutzende identische Werte auf dem Broker.
- Alles retained: ein frisch verbundener Client (EisBaer, HA) hat den Stand
  sofort, statt bis zur naechsten Aenderung leere Kanaele zu sehen.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

import paho.mqtt.client as mqtt

from config import standard_client_id

logger = logging.getLogger(__name__)

# (sn, property, wert) -> None. Kommt aus dem paho-Netzwerk-Thread.
CommandCallback = Callable[[str, str, str], None]

ONLINE = "online"
OFFLINE = "offline"

# Topic-Segment fuer eingehende Befehle. "cmnd" wie bei Tasmota - dieselbe
# Schreibweise, die Dirks uebrige MQTT-Landschaft verwendet.
COMMAND_SEGMENT = "cmnd"


class MqttBridge:
    def __init__(
        self,
        mqtt_config: dict,
        on_command: CommandCallback | None = None,
        on_connected: Callable[[], None] | None = None,
    ) -> None:
        self._cfg = mqtt_config
        self._on_command = on_command
        # Wird NACH erfolgreichem Verbinden gerufen. Wichtig: vorher gesendete
        # Nachrichten verwirft paho stillschweigend (MQTT_ERR_NO_CONN) - genau
        # daran sind die Discovery-Topics zunaechst gescheitert.
        self._on_connected = on_connected
        self._base = mqtt_config.get("base_topic", "flowbridge")
        self._retain = bool(mqtt_config.get("retain", True))
        self._abonnierte_sns: set[str] = set()
        # Letzter gesendeter Einzelwert je Topic - fuer den Aenderungsvergleich.
        self._zuletzt: dict[str, str] = {}

        self._client = mqtt.Client(
            # Leer heisst "automatisch". Bewusst kein fester Vorgabewert:
            # Zwei FlowBridges am selben Broker traegen sonst dieselbe
            # Kennung, und MQTT wirft bei gleicher Kennung den aelteren
            # Client hinaus - beide melden sich dann im Wechsel ab, ohne dass
            # es nach der eigentlichen Ursache aussieht.
            client_id=(mqtt_config.get("client_id") or "").strip() or standard_client_id(),
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        if mqtt_config.get("username"):
            self._client.username_pw_set(mqtt_config["username"], mqtt_config.get("password") or "")
        self._client.on_message = self._handle_message
        self._client.on_connect = self._handle_connect
        # Last-Will: meldet FlowBridge als offline, wenn die Verbindung
        # unsauber abbricht (Absturz, Stromausfall) - ohne das wuerde HA das
        # Geraet dauerhaft als verfuegbar anzeigen.
        self._client.will_set(self.bridge_availability_topic, OFFLINE, retain=True)

    # ---------------------------------------------------------------- Topics
    @property
    def bridge_availability_topic(self) -> str:
        return f"{self._base}/bridge/available"

    @property
    def ecoflow_availability_topic(self) -> str:
        """Zustand der Verbindung zur EcoFlow-Cloud.

        Eigenes Topic, weil das ein DRITTER, unabhaengiger Ausfall ist:
        FlowBridge kann laufen und der lokale Broker erreichbar sein,
        waehrend die Cloud weg ist - dann sind alle Werte eingefroren, ohne
        dass es einem MQTT-Client sonst irgendwie auffiele.
        """
        return f"{self._base}/bridge/ecoflow"

    def availability_topic(self, sn: str) -> str:
        return f"{self._base}/{sn}/available"

    def state_topic(self, sn: str) -> str:
        return f"{self._base}/{sn}/state"

    def module_topic(self, sn: str, modul: str) -> str:
        return f"{self._base}/{sn}/modules/{modul.lower()}"

    def status_topic(self, sn: str, feld: str) -> str:
        return f"{self._base}/{sn}/status/{feld}"

    def command_topic(self, sn: str, property_name: str) -> str:
        return f"{self._base}/{sn}/{COMMAND_SEGMENT}/{property_name}"

    # ------------------------------------------------------------ Verbindung
    def connect(self) -> None:
        """Verbindung aufbauen - und offen halten, auch wenn der erste Versuch
        daneben geht.

        Bewusst `connect_async` statt `connect`: Das synchrone `connect`
        wirft, wenn der Broker in genau diesem Moment nicht antwortet, und
        damit war die Verbindung frueher endgueltig verloren - der Aufrufer
        merkte sich die Konfiguration trotzdem als "verbunden" und versuchte
        es nie wieder.

        Genau das passiert beim Start im Container regelmaessig: FlowBridge
        und Mosquitto fahren gleichzeitig hoch, und wer zuerst da ist, ist
        Zufall. Beobachtet am 14.08.2026 auf der NAS - nach jedem neuen
        Abbild stand "Lokaler Broker getrennt", bis der Container ein zweites
        Mal startete.

        `connect_async` wirft nicht; `loop_start` baut die Verbindung im
        Hintergrund auf und stellt sie danach auch nach jedem Abbruch wieder
        her. Ein einziger Mechanismus fuer Erstverbindung und Reconnect -
        vorher war nur der zweite Fall abgedeckt.
        """
        # Nicht die paho-Vorgabe (bis 120 s): Nach einem Broker-Neustart
        # sollen die Werte wieder fliessen, bevor jemand nachsieht, warum sie
        # es nicht tun.
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.connect_async(self._cfg["host"], int(self._cfg["port"]), keepalive=30)
        self._client.loop_start()

    def disconnect(self) -> None:
        # Sauberes Abmelden: ausdruecklich offline melden, bevor die
        # Verbindung endet - das Last-Will greift nur bei Abbruch.
        try:
            self._client.publish(self.bridge_availability_topic, OFFLINE, retain=True)
        except Exception:
            pass
        self._client.loop_stop()
        self._client.disconnect()

    def is_connected(self) -> bool:
        return self._client.is_connected()

    def _handle_connect(self, _client, _userdata, _flags, reason_code, _properties=None) -> None:
        if reason_code != 0:
            logger.error("Lokaler Broker hat die Verbindung abgelehnt (Code %s).", reason_code)
            return
        self._client.publish(self.bridge_availability_topic, ONLINE, retain=True)
        # Nach einem Reconnect neu abonnieren - Subscriptions ueberleben den
        # Verbindungsabbruch nicht (gleicher Fallstrick wie beim EcoFlow-Broker).
        for sn in self._abonnierte_sns:
            self._client.subscribe(self.command_topic(sn, "+"))
        # Beim Reconnect wieder alles senden duerfen, auch unveraenderte Werte.
        self._zuletzt.clear()
        if self._on_connected:
            try:
                self._on_connected()
            except Exception as exc:
                logger.warning("Nacharbeit nach Verbindungsaufbau fehlgeschlagen: %s", exc)

    # -------------------------------------------------------------- Publish
    def publish_state(self, sn: str, status: dict, modules: dict[str, dict] | None = None) -> None:
        """Vollstaendiger Status + Modul-JSONs + Einzelwerte."""
        self._client.publish(
            self.state_topic(sn), json.dumps(status, ensure_ascii=False), retain=self._retain
        )

        for modul, felder in (modules or {}).items():
            self._client.publish(
                self.module_topic(sn, modul),
                json.dumps(felder, ensure_ascii=False),
                retain=self._retain,
            )

        for feld, wert in status.items():
            # Interne Felder gehoeren nicht als Einzelwert auf den Broker.
            if feld.startswith("_") or feld in ("sn", "online"):
                continue
            if isinstance(wert, bool):
                text = "true" if wert else "false"
            elif wert is None:
                continue
            else:
                text = str(wert)
            self._publish_bei_aenderung(self.status_topic(sn, feld), text)

    def _publish_bei_aenderung(self, topic: str, wert: str) -> None:
        if self._zuletzt.get(topic) == wert:
            return
        self._zuletzt[topic] = wert
        self._client.publish(topic, wert, retain=self._retain)

    def publish_ecoflow_availability(self, verbunden: bool) -> None:
        self._publish_bei_aenderung(
            self.ecoflow_availability_topic, ONLINE if verbunden else OFFLINE
        )

    def publish_availability(self, sn: str, online: bool | None) -> None:
        """online/offline je Geraet. Unbekannt (None) wird NICHT gesendet -
        lieber gar keine Aussage als eine falsche."""
        if online is None:
            return
        self._publish_bei_aenderung(self.availability_topic(sn), ONLINE if online else OFFLINE)

    def publish_raw(self, topic: str, payload: str, retain: bool = True) -> None:
        """Fuer Topics ausserhalb des eigenen Baums (Home-Assistant-Discovery)."""
        self._client.publish(topic, payload, retain=retain)

    # ------------------------------------------------------------- Subscribe
    def subscribe_commands(self, sn: str) -> None:
        self._abonnierte_sns.add(sn)
        if self._client.is_connected():
            self._client.subscribe(self.command_topic(sn, "+"))

    def _handle_message(self, _client, _userdata, msg) -> None:
        if self._on_command is None:
            return
        teile = msg.topic.split("/")
        # .../{sn}/cmnd/{property}
        if len(teile) < 3 or teile[-2] != COMMAND_SEGMENT:
            return
        sn = teile[-3]
        property_name = teile[-1]
        wert = msg.payload.decode("utf-8", errors="replace").strip()

        # Retained Befehle werden NICHT ausgefuehrt.
        #
        # Ein Broker liefert retained Nachrichten jedem neuen Abonnenten sofort
        # aus. Liegt auf einem cmnd-Topic noch ein alter Befehl, fuehrt
        # FlowBridge ihn bei JEDEM Verbindungsaufbau erneut aus - und schaltet
        # damit ungefragt am Speicher. Genau das ist am 13.08.2026 passiert:
        # Nach der Neueinrichtung ging das pausierte AC-Laden von selbst an,
        # weil vom EisBaer-Test noch ein retained "on" auf dem Broker lag.
        #
        # Ein Befehl ist ein Ereignis, kein Zustand. Wer ihn retained sendet,
        # hat ihn dauerhaft scharf gestellt.
        if getattr(msg, "retain", False):
            logger.warning(
                "Retained Befehl auf %s IGNORIERT (Wert: %s). Ein Befehl darf nicht "
                "retained gesendet werden - er wuerde sonst bei jedem Neustart "
                "erneut schalten. Loeschen mit: mosquitto_pub -t '%s' -r -n",
                msg.topic,
                wert,
                msg.topic,
            )
            return

        logger.info("MQTT-Befehl: %s %s = %s", sn, property_name, wert)
        try:
            self._on_command(sn, property_name, wert)
        except Exception as exc:  # nie den Netzwerk-Thread sterben lassen
            logger.warning("MQTT-Befehl %s/%s fehlgeschlagen: %s", sn, property_name, exc)

    def veroeffentlichte_topics(self) -> list[str]:
        """Einzelwert-Topics, die tatsaechlich schon gesendet wurden.

        Fuer das Diagnose-Paket: zeigt, was beim Anwender wirklich auf dem
        Broker liegt - inklusive der Felder, die sein Modell gar nicht
        liefert und die deshalb fehlen.
        """
        return list(self._zuletzt)

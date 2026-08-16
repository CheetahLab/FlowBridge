"""
FlowBridge – FastAPI-Fundament.

Aufbau: Diese Datei kapselt die Aufsichtsschleife als Background-Task in der
uvicorn-Lifespan. EcoFlow-Zugangsdaten und Broker-IP kommen aus dem Setup-UI
(POST /api/setup), nicht ausschliesslich aus einer vorbefuellten config.yaml –
das Frontend fuehrt bei fehlender oder ungueltiger Config durch den
Ersteinrichtungs-Dialog.
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.responses import Response as RawResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import auth
import diagnostics
import exporters
import ha_discovery
import inventar
import models
import version
from commands_river2 import CommandError
from config import (
    MASK_PLACEHOLDER,
    MIN_CLIENT_ID_LAENGE,
    config_path,
    load_config,
    mask_secrets,
    read_setpoints,
    standard_client_id,
    write_config,
    write_setpoint,
)
from config import schreibprobe as config_schreibprobe
from device import MIN_FLUSS_W, normalize_quota
from ecoflow_client import EcoFlowApiError, EcoFlowAuthError, EcoFlowClient
from ecoflow_mqtt import EcoFlowMqttListener
from mqtt_bridge import MqttBridge

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Diagnose laeuft ab dem ersten Moment mit (Ringpuffer im Speicher), damit ein
# Fehler auch dann noch nachvollziehbar ist, wenn erst NACH ihm eingeschaltet
# wird. Die Protokolldatei liegt neben der config.yaml - dasselbe Verzeichnis
# ist im Container ohnehin schon gemountet.
_diagnose = diagnostics.Diagnose(load_config, config_path().parent / "flowbridge.log")
_diagnose.einhaengen()

# Laeuft neben der Diagnose, nicht in ihr: Die Diagnose sucht einen konkreten
# Fehler und rotiert nach wenigen MB weg. Das Inventar soll ueber Monate
# mitlaufen und bleibt dabei wenige Kilobyte gross.
_inventar = inventar.Feldinventar(config_path().parent / "feldinventar.json")

_state: dict[str, dict] = {}  # sn -> letzter normalisierter Status
_quota_cache: dict[str, dict] = {}  # sn -> rohe, praefigierte Quota-Felder (REST + Live-Push gemerged)
_last_seen: dict[str, float] = {}  # sn -> monotonic-Zeitstempel des letzten Datenempfangs
_reported_offline: set[str] = set()  # sn, fuer die /status ausdruecklich offline gemeldet hat
# Grund im Klartext, falls der Datenordner nicht beschreibbar ist - sonst None.
# Wird beim Start gesetzt und ueber /api/auth/state auch OHNE Anmeldung
# ausgeliefert: Wer sich nicht anmelden kann, weil nichts gespeichert werden
# kann, muss den Grund trotzdem sehen duerfen.
_speicher_fehler: str | None = None
_device_errors: dict[str, str] = {}  # sn -> letzter REST-Fehler (z.B. falsche SN, fremdes Konto)
# sn -> zuletzt VON FLOWBRIDGE gesetzte AC-Ladeleistung. EcoFlow gibt diesen
# Sollwert nirgends zurueck (weder quota/all noch Push, ausgiebig geprueft),
# deshalb ist das nur "was wir zuletzt geschickt haben" - nicht zwingend der
# echte Geraetezustand, falls jemand parallel die App benutzt. Im UI
# entsprechend gekennzeichnet und nach Neustart wieder leer.
_charge_power_set: dict[str, int] = {}
# sn -> zuletzt von FlowBridge gesetzter Lade-/Pause-Zustand. Wie oben: nicht
# auslesbar, also nur "was wir zuletzt geschickt haben".
_ac_charging_set: dict[str, bool] = {}
# sn -> monotonic-Zeitpunkt, an dem WIR diesen Zustand zuletzt gesetzt haben.
# Nur fuer die Schonfrist in _pause_gegen_messung_pruefen (s. dort).
_ac_charging_gesetzt_um: dict[str, float] = {}

# Wie lange nach einem eigenen Lade-/Pause-Befehl die Messung NICHT gegen den
# gemerkten Zustand gehalten wird.
#
# Der Grund ist Physik, nicht Vorsicht: Zwischen "Befehl abgeschickt" und
# "Messung zeigt die Wirkung" liegt Zeit. Der Speicher muss die Ladung erst
# herunterfahren, und die neue Messung muss als Push ankommen.
#
# Ohne Schonfrist verwarf FlowBridge die Pause im selben Aufruf, in dem es sie
# setzte: _execute_command merkt den Zustand und ruft sofort _publish_state(),
# das prueft gegen den Messwert von VOR dem Befehl - der zeigt naturgemaess
# noch Ladung. Am 16.08.2026 von Dirk gefunden, im Protokoll dreimal sauber
# belegt mit 5, 7 und 8 Millisekunden Abstand zwischen Befehl und Verwurf.
#
# Eine Minute ist grosszuegig: Das Gegenbeispiel, fuer das die Pruefung
# ueberhaupt existiert (jemand schaltet in der EcoFlow-App), ist ein
# Dauerzustand - der wird eine Minute spaeter genauso erkannt.
PAUSE_SCHONFRIST_S = 60

# Eigene Verlaufsaufzeichnung: EcoFlow bietet den Historien-Endpoint
# (/iot-open/sign/device/quota/data) laut Portal-Doku nur fuer Power Ocean,
# STREAM und smartHomePanelII an - fuer Powerstations gibt es ihn nicht.
# Deshalb hier ein einfacher Ringpuffer im Speicher. Bewusst NICHT persistent:
# nach einem Neustart faengt die Kurve neu an (fuer Langzeitauswertung ist der
# lokale MQTT-Broker samt Datenbank der richtige Ort, nicht FlowBridge).
HISTORY_INTERVAL_SECONDS = 15
HISTORY_MAX_POINTS = 1440  # bei 15s ~6 Stunden
HISTORY_FIELDS = (
    "soc_percent",
    "ac_watts_in",
    "dc_watts_in",
    "battery_watts_in",
    "watts_out",
    "ac_watts_out",
)
_history: dict[str, list[dict]] = {}


def _record_history(sn: str, status: dict) -> None:
    punkte = _history.setdefault(sn, [])
    jetzt = time.time()
    if punkte and (jetzt - punkte[-1]["t"]) < HISTORY_INTERVAL_SECONDS:
        return  # nicht bei jedem Push einen Punkt anlegen
    punkt = {"t": jetzt}
    for feld in HISTORY_FIELDS:
        wert = status.get(feld)
        if wert is not None:
            punkt[feld] = wert
    punkte.append(punkt)
    if len(punkte) > HISTORY_MAX_POINTS:
        del punkte[: len(punkte) - HISTORY_MAX_POINTS]
_bridge: MqttBridge | None = None
_live_listener: EcoFlowMqttListener | None = None
_supervisor_task: asyncio.Task | None = None

# Signatur der zuletzt verbundenen Konfiguration - aendert sie sich (neue
# Keys, andere Geraete, andere Broker-IP), wird neu verbunden statt einfach
# weiterzulaufen.
_connected_signature: tuple | None = None
# Der asyncio-Loop des Servers. MQTT-Befehle treffen im paho-Netzwerk-Thread
# ein, apply_command ist aber async - ohne diese Referenz liesse sich die
# Coroutine von dort aus nicht starten.
_loop: asyncio.AbstractEventLoop | None = None


# Ab hier gilt der Push-Fluss nicht mehr als frisch. Der Push kommt normal
# alle paar Sekunden - drei Minuten Stille heisst: keine Aussage mehr moeglich
# (NICHT "offline", s. _is_online).
STALE_AFTER_SECONDS = 180

# ... und ab hier ist die Stille dann doch ein Beleg.
#
# Ohne diese Obergrenze blieb "unbekannt" fuer immer stehen, und
# publish_availability() sendete dabei NICHTS - das retained `available`
# behielt also den letzten Stand von vor dem Ausfall.
#
# Am 16.08.2026 aufgeflogen: Nach einem Stromausfall hatte sich der RIVER 2
# Pro wegen Tiefentladung abgeschaltet (soc 40 % -> 7 %, AC-Ausgang aus).
# 22 Stunden lang stand auf dem lokalen Broker weiterhin
#   flowbridge/<sn>/available = online
# Der REST-Resync lief die ganze Zeit erfolgreich weiter und lieferte den
# eingefrorenen Cloud-Cache - byte-identische Werte, im Minutentakt frisch
# gestempelt. Wer im EisBaer auf `available` schaut, sah durchgehend gruen.
#
# Die Grenze muss deutlich ueber den bekannten Push-Luecken liegen: gemessen
# wurden 2,5 und 8,6 Minuten Pause bei laufendem Geraet (14.08.2026). Eine
# Stunde laesst dafuer reichlich Luft und ist immer noch drei Groessenordnungen
# unter dem, was hier passiert ist.
OFFLINE_AFTER_SECONDS = 3600

# Takt der Aufsichtsschleife: So oft wird geprueft, ob beide MQTT-Verbindungen
# stehen. Bewusst deutlich schneller als der REST-Resync (poll_interval,
# Vorgabe 30 s) - eine fehlende Verbindung soll nicht eine halbe Minute
# fehlend BLEIBEN, nur weil der Resync so lange schlaeft. Genau das war beim
# Containerstart auf der NAS zu sehen.
#
# Kostet nichts: Steht alles, kehrt _ensure_connected() sofort zurueck.
AUFSICHT_TAKT_S = 5

# Abstand der Update-Pruefung. Zusaetzlich wird beim Start geprueft - das ist
# der wichtigere der beiden Zeitpunkte.
#
# Vorher hatte ich "einmal taeglich" vorgeschlagen. Dirks Einwand: "Wenn wir
# wie heute neun Builds machen, bekommst du das nicht mit." Er hat recht -
# nicht weil neun Fassungen am Tag der Regelfall waeren, sondern weil ein Fix,
# der um halb zehn erscheint, nicht bis zum naechsten Morgen unsichtbar
# bleiben darf.
#
# Sechs Stunden sind vier Abrufe am Tag statt einem. Der Start-Check deckt
# den Rest ab: Wer aktualisiert oder neu startet, weiss sofort, woran er ist.
UPDATE_TAKT_S = 6 * 60 * 60


def _is_online(sn: str) -> bool | None:
    """Online-Zustand aus zwei Quellen: ausdrueckliche /status-Meldung + Push-Fluss.

    Rueckgabe bewusst dreiwertig:
      True  - Geraet meldet sich
      False - Geraet ist nachweislich weg
      None  - unbekannt (kein Push-Kanal verfuegbar, also keine Aussage moeglich)

    Das /status-Topic feuert NUR bei Wechseln (verifiziert 12.08.2026), es kann
    also gar nie eine Meldung kommen - als alleinige Quelle reicht es nicht,
    deshalb zusaetzlich der Staleness-Fallback ueber den Push-Fluss. Umgekehrt
    bringt eine ausdrueckliche Offline-Meldung den Zustand sofort auf offline,
    statt STALE_AFTER_SECONDS abzuwarten.

    Nur Push-Nachrichten zaehlen als Lebenszeichen - siehe _apply_quota_update.

    STILLE IST KEIN BELEG FUER "WEG" (korrigiert 14.08.2026)
    --------------------------------------------------------
    Frueher galt: kein Push seit STALE_AFTER_SECONDS -> offline. Das behauptete
    mehr, als die Daten hergaben. Gemessen an diesem Tag: Der EcoFlow-Push
    setzt von sich aus immer wieder aus - beobachtet wurden Luecken von 2,5
    und 8,6 Minuten, bei einem normalen Abstand von 2-4 Sekunden. Waehrend
    einer solchen Luecke war ein zweiter, durchgehend verbundener Mitleser
    ebenso still, und es gab keinen Verbindungsabbruch: Die Pause kommt von
    EcoFlow, das Geraet ist die ganze Zeit da. FlowBridge meldete trotzdem
    "Speicher offline".

    Es gibt aber eine belastbare Quelle: das /status-Topic. Am 12.08.2026 bei
    WLAN-Entzug live geprueft - dort kam korrekt status 0. Ein wirklich
    verschwundenes Geraet meldet sich also ab.

    Deshalb jetzt:
      False (offline) - bei ausdruecklicher Abmeldung ueber /status ODER wenn
                        die Stille OFFLINE_AFTER_SECONDS ueberschreitet
      None  (unbekannt) - dazwischen; publish_availability sendet dann NICHTS,
                          der letzte bekannte Stand bleibt stehen

    ABER SIE IST NICHT UNBEGRENZT KEIN BELEG (ergaenzt 16.08.2026)
    --------------------------------------------------------------
    Die Regel oben stimmt fuer Minuten und war fuer Minuten gedacht. Ohne
    Obergrenze galt sie aber auch fuer Tage: Ein Geraet, das sich wegen
    Tiefentladung abgeschaltet hatte, blieb 22 Stunden lang auf "unbekannt"
    stehen - und weil "unbekannt" nichts publisht, meldete der lokale Broker
    die ganze Zeit den letzten bekannten Stand: online. Details an
    OFFLINE_AFTER_SECONDS.

    Ein Geraet, das sich abschaltet, kann sich nicht mehr abmelden. Genau
    dieser Fall - der einzige, in dem die /status-Quelle prinzipbedingt
    schweigt - fiel vorher durch beide Netze.
    """
    if _live_listener is None:
        return None  # ohne Push-Kanal keine belastbare Aussage - nicht "offline" behaupten
    if sn in _reported_offline:
        return False  # das Geraet hat sich selbst abgemeldet - das zaehlt
    last = _last_seen.get(sn)
    if last is None:
        return None  # Kanal steht, aber noch nie ein Push gesehen -> noch keine Aussage
    stille = time.monotonic() - last
    if stille < STALE_AFTER_SECONDS:
        return True
    if stille >= OFFLINE_AFTER_SECONDS:
        return False  # so lange schweigt kein laufendes Geraet
    return None  # still, aber nicht abgemeldet -> wir wissen es schlicht nicht


def _stille_sekunden(sn: str) -> float | None:
    """Wie lange kein Push mehr kam. None = seit dem Start noch nie einer.

    Bewusst NICHT Teil von `status`: MqttBridge.publish_state() macht aus jedem
    Feld dort ein eigenes status/-Topic, und ein Wert, der sich jede Sekunde
    aendert, waere als Topic nur Rauschen - und taeuchte ausserdem im
    EisBaer-Export als neuer Kanal auf. Die Zahl gehoert in die Oberflaeche,
    nicht auf den Broker; fuer den Broker gibt es `available`.
    """
    last = _last_seen.get(sn)
    if last is None:
        return None
    return time.monotonic() - last


def _apply_quota_update(sn: str, partial_or_full: dict, *, from_push: bool = True) -> None:
    """Gemeinsamer Pfad fuer REST-Resync UND Live-MQTT-Push (siehe ecoflow_mqtt.py).

    `from_push` unterscheidet die beiden Quellen und ist NICHT kosmetisch:
    Nur eine MQTT-Push-Nachricht ist ein echter Lebensnachweis des Geraets.
    quota/all liefert dagegen auch dann weiter Werte (HTTP 200, plausible
    Zahlen), wenn das Geraet gar nicht mehr verbunden ist - EcoFlow beantwortet
    den Call aus dem Cloud-Cache. Wuerde der REST-Resync als Lebenszeichen
    zaehlen, wuerde er eine korrekte Offline-Meldung nach spaetestens einem
    Poll-Intervall wieder ueberschreiben (12.08.2026 live beobachtet: Geraet
    per WLAN-Entzug offline, /status meldete korrekt 0, der naechste
    REST-Resync setzte es faelschlich zurueck auf online).

    Wird auch aus dem paho-Netzwerk-Thread aufgerufen (nicht nur aus dem
    asyncio-Event-Loop) - Dict-Zuweisungen und MqttBridge.publish_state()
    sind dafuer threadsicher genug (GIL bzw. paho-eigene Thread-Sicherheit).
    """
    _quota_cache.setdefault(sn, {}).update(partial_or_full)
    # Hier laufen BEIDE Kanaele zusammen - der einzige Ort, an dem sich Push
    # und REST mit derselben Zeile erfassen lassen.
    _inventar.beobachte(sn, partial_or_full, "push" if from_push else "rest")
    if from_push:
        _last_seen[sn] = time.monotonic()
        _reported_offline.discard(sn)  # echte Push-Nachricht -> es lebt
    _publish_state(sn)


def _pause_gegen_messung_pruefen(sn: str, status: dict) -> None:
    """Verwirft die gemerkte Ladepause, wenn der Speicher nachweislich laedt.

    Hintergrund (14.08.2026, von Dirk im Feld gefunden): `chgPauseFlag` ist
    NICHT lesbar - es taucht in keinem der 29 gelieferten Felder auf.
    FlowBridge zeigt deshalb den Pausenzustand an, den es sich zuletzt selbst
    gesetzt hat. Aendert etwas anderes die Ladung, bekommt es das nie mit.

    Und das passiert im Alltag: Wer in der EcoFlow-App die Backup-Reserve
    umschaltet, startet damit das Laden - die Reserve IST eine Ladesteuerung.
    Live mitgeschnitten: watchIsConfig 1->0, drei Sekunden spaeter nimmt die
    Batterie 41 W und der AC-Eingang liefert 128 W, waehrend FlowBridge
    weiterhin "pausiert" anzeigte. Laut Doku faellt die Pause ohnehin auch
    beim Aus- und Einstecken des Netzkabels weg.

    Messung schlaegt Gedaechtnis. Der Nachweis braucht BEIDES:
      * AC-Eingang liefert etwas  - sonst waere es Solar, und die Pause
        betrifft nur das Laden aus dem Netz
      * die Batterie nimmt wirklich Strom auf - sonst waere es Durchleitung
        (Netz versorgt einen Verbraucher, Batterie unbeteiligt), und genau
        dieser Fall hat uns schon einmal in die Irre gefuehrt

    ... UND EINE MESSUNG, DIE DEN BEFEHL KENNT (ergaenzt 16.08.2026)
    ----------------------------------------------------------------
    Der Satz oben stimmt nur, wenn die Messung juenger ist als der Befehl.
    War sie es nicht, widerlegte sie nichts - sie beschrieb die Welt von
    davor. Genau das passierte: `_execute_command` merkt den neuen Zustand
    und ruft direkt `_publish_state()`, das hier landet, mit dem Messwert von
    VOR dem Befehl. Der zeigt naturgemaess noch Ladung, denn der Speicher
    fuhr sie erst herunter.

    Ergebnis fuer den Bedienenden: Er drueckt Pause, und der Schalter springt
    nach ein paar Sekunden zurueck auf "laeuft" - dreimal im Protokoll
    belegt, mit 5, 7 und 8 Millisekunden zwischen Befehl und Verwurf.

    Deshalb PAUSE_SCHONFRIST_S. Die Pruefung verliert dadurch nichts: Wofuer
    sie da ist - jemand schaltet in der EcoFlow-App - ist ein Dauerzustand
    und wird eine Minute spaeter genauso erkannt.
    """
    if _ac_charging_set.get(sn) is not False:
        return  # nichts gemerkt oder "laeuft" gemerkt - kein Widerspruch
    # Schonfrist: Direkt nach einem eigenen Befehl beschreibt die Messung noch
    # den Zustand DAVOR. Sie kann den Befehl also gar nicht widerlegen - sie
    # hat ihn noch nicht gesehen. Ohne diese Zeile verwarf sich die Pause
    # selbst, acht Millisekunden nachdem sie gesetzt wurde.
    gesetzt_um = _ac_charging_gesetzt_um.get(sn)
    if gesetzt_um is not None and (time.monotonic() - gesetzt_um) < PAUSE_SCHONFRIST_S:
        return
    ac_ein = status.get("ac_watts_in") or 0
    batterie_ein = status.get("battery_watts_in") or 0
    if ac_ein > 0 and batterie_ein > MIN_FLUSS_W:
        logger.info(
            "Gemerkte Ladepause fuer %s verworfen: Batterie nimmt %s W bei %s W "
            "AC-Eingang - die Pause gilt am Geraet nicht mehr.",
            sn, batterie_ein, ac_ein,
        )
        _ac_charging_set.pop(sn, None)
        _ac_charging_gesetzt_um.pop(sn, None)  # mit dem Zustand faellt der Zeitpunkt
        try:
            # None statt False: "wir wissen es nicht mehr". _restore_setpoints
            # uebernimmt nur echte Booleans, der Wert faellt also sauber weg.
            write_setpoint(sn, "ac_charging_enabled", None)
        except OSError as exc:
            # Laeuft im paho-Netzwerk-Thread - ein nicht beschreibbarer
            # Datenordner darf den nicht umbringen.
            logger.warning("Gemerkte Ladepause nicht loeschbar (%s): %s", sn, exc)


def _publish_state(sn: str) -> None:
    """Normalisierten Status neu berechnen, ablegen und lokal publishen."""
    status = normalize_quota(sn, _quota_cache.get(sn, {}))
    status["online"] = _is_online(sn)
    status["last_update"] = datetime.now(timezone.utc).isoformat()
    if sn in _charge_power_set:
        status["charge_power_watts_set"] = _charge_power_set[sn]
    _pause_gegen_messung_pruefen(sn, status)
    if sn in _ac_charging_set:
        status["ac_charging_enabled_set"] = _ac_charging_set[sn]
    _state[sn] = status
    _record_history(sn, status)
    if _bridge:
        try:
            _bridge.publish_state(sn, status, status.get("_modules"))
            _bridge.publish_availability(sn, status["online"])
        except Exception as exc:
            logger.warning("Publish zum lokalen Broker fehlgeschlagen (%s): %s", sn, exc)


def _apply_status_update(sn: str, online: bool) -> None:
    """Callback fuers /status-Topic (nur bei Wechseln, s. ecoflow_mqtt.py)."""
    if online:
        _reported_offline.discard(sn)
    else:
        _reported_offline.add(sn)
    logger.info("Geraet %s ist jetzt %s", sn, "online" if online else "OFFLINE")
    _publish_state(sn)


def _publish_ha_discovery(config: dict) -> None:
    """Home-Assistant-Discovery-Topics senden (retained), sofern aktiviert.

    Abschaltbar, weil sie sonst auch auf Brokern landen, an denen gar kein
    Home Assistant haengt - dort waeren es nur ein paar Dutzend retained
    Topics ohne Nutzen. Beim Abschalten werden sie wieder entfernt.
    """
    if _bridge is None:
        return
    ha = config.get("homeassistant") or {}
    prefix = ha.get("discovery_prefix", "homeassistant")
    aktiv = bool(ha.get("discovery", True))

    for geraet in config["ecoflow"].get("devices", []):
        sn = geraet["sn"]
        if not aktiv:
            # Leerer Payload loescht die Entitaet in HA.
            for topic in ha_discovery.build_removals(sn, prefix):
                _bridge.publish_raw(topic, "")
            continue
        # Auch bei AKTIVER Discovery: umbenannte Felder wegraeumen, sonst
        # steht die alte Entitaet dauerhaft neben der neuen in HA.
        for topic in ha_discovery.build_legacy_removals(sn, prefix):
            _bridge.publish_raw(topic, "")
        modell = geraet.get("model")
        for topic, payload in ha_discovery.build_entities(
            sn=sn,
            name=geraet.get("name") or sn,
            model=modell,
            base_topic=config["mqtt"].get("base_topic", "flowbridge"),
            bridge_availability_topic=_bridge.bridge_availability_topic,
            ecoflow_availability_topic=_bridge.ecoflow_availability_topic,
            controllable=models.is_controllable(modell),
            charge_steps=models.charge_watts_steps(modell),
            discovery_prefix=prefix,
            nur_lesbar=models.nur_lesbar(modell),
        ):
            _bridge.publish_raw(topic, payload)
    if aktiv:
        logger.info("Home-Assistant-Discovery veroeffentlicht (Praefix '%s').", prefix)


# Statusfelder, die FlowBridge frueher einmal veroeffentlicht hat. Ihre
# status/-Topics sind retained: ohne aktives Leeren liegt dort fuer immer der
# letzte Wert und sieht in EisBaer wie ein lebender Kanal aus.
_VERALTETE_STATUSFELDER = (
    "remain_time_min",
    # Hiess bis 14.08.2026 so, als nur die Herkunft bekannt war (watthConfig/
    # isConfig), nicht die Bedeutung. Heisst jetzt backup_reserve_enabled.
    "energy_management_enabled",
)


def _clear_veraltete_topics(config: dict) -> None:
    if _bridge is None:
        return
    for geraet in config["ecoflow"].get("devices", []):
        for feld in _VERALTETE_STATUSFELDER:
            _bridge.publish_raw(_bridge.status_topic(geraet["sn"], feld), "")


def _nach_verbindungsaufbau() -> None:
    """Laeuft im paho-Thread, sobald der lokale Broker verbunden ist."""
    config = load_config()
    _clear_veraltete_topics(config)
    _publish_ha_discovery(config)


def _verbinde_lokal(mqtt_cfg: dict, sns: tuple[str, ...]) -> None:
    global _bridge
    try:
        # Discovery erst NACH dem Verbinden senden - vorher verwirft paho
        # die Nachrichten stillschweigend. Als Callback deckt es zugleich
        # den Reconnect ab (retained Topics wieder auffrischen).
        _bridge = MqttBridge(
            mqtt_cfg,
            on_command=_handle_mqtt_command,
            on_connected=_nach_verbindungsaufbau,
        )
        _bridge.connect()
        for sn in sns:
            _bridge.subscribe_commands(sn)
    except Exception as exc:
        # Ein Broker, der gerade nicht antwortet, landet hier NICHT mehr -
        # das holt paho selbst nach (siehe MqttBridge.connect). Hier bleibt
        # nur, was dauerhaft kaputt ist: unbrauchbarer Port, ungueltige
        # Kennung.
        logger.warning("Lokale MQTT-Verbindung nicht aufbaubar: %s", exc)
        _bridge = None


async def _verbinde_ecoflow(eco: dict, sns: tuple[str, ...]) -> None:
    global _live_listener
    try:
        client = EcoFlowClient(eco["access_key"], eco["secret_key"])
        # Der Zertifikatsabruf ist der zerbrechliche Teil: ein REST-Aufruf
        # ins Internet, direkt beim Start des Containers. Hat die NAS ihre
        # Netzwerkverbindung in dem Moment noch nicht, schlaegt er fehl -
        # und ohne Zertifikat gibt es keine MQTT-Verbindung, die paho von
        # sich aus nachholen koennte. Deshalb wird der ganze Block beim
        # naechsten Durchlauf erneut versucht (siehe _ensure_connected).
        cert = await client.get_mqtt_certificate()
        _live_listener = EcoFlowMqttListener(
            cert, on_quota=_apply_quota_update, on_status=_apply_status_update
        )
        _live_listener.connect()
        for sn in sns:
            _live_listener.subscribe_device(sn)
        logger.info("EcoFlow-Live-MQTT verbunden (%s Geraete abonniert).", len(sns))
    except Exception as exc:
        logger.warning("EcoFlow-Live-MQTT-Verbindung fehlgeschlagen (nur REST-Resync aktiv): %s", exc)
        _live_listener = None


async def _ensure_connected(config: dict) -> None:
    """Beide MQTT-Verbindungen herstellen und hergestellt HALTEN.

    Zwei getrennte Aufgaben in einer Funktion:

    1. Aendern sich Zugangsdaten, Geraeteliste oder Broker-Adresse, wird
       alles abgebaut und neu aufgebaut.
    2. Fehlt eine der beiden Verbindungen, wird sie nachgeholt - auch wenn
       sich an der Konfiguration nichts geaendert hat.

    Punkt 2 fehlte bis 14.08.2026, und das war ein echter Fehler: Die
    Signatur wurde am Ende IMMER gespeichert, auch wenn ein Verbindungsaufbau
    danebengegangen war. Der Frueh-Ausstieg oben griff dann bei jedem
    weiteren Durchlauf, und es wurde nie wieder ein Versuch unternommen. Ein
    Zeitproblem von Sekunden beim Containerstart - beide steigen gleichzeitig
    hoch, das Netz ist noch nicht da - wurde so zu einem Dauerzustand, den
    nur ein zweiter Neustart behob.

    Erst zeigte sich das am lokalen Broker, nach dem Fix am EcoFlow-Broker
    erneut: Dort ist es sogar wahrscheinlicher, weil der Zertifikatsabruf
    ueber das Internet geht.
    """
    global _bridge, _live_listener, _connected_signature

    eco = config["ecoflow"]
    mqtt_cfg = config["mqtt"]
    sns = tuple(sorted(d["sn"] for d in eco["devices"]))
    signature = (eco["access_key"], eco["secret_key"], sns, mqtt_cfg.get("host"), mqtt_cfg.get("port"))

    if signature != _connected_signature:
        logger.info("Konfiguration geaendert - verbinde lokalen Broker + EcoFlow-Live-MQTT neu.")
        if _live_listener:
            _live_listener.disconnect()
            _live_listener = None
        if _bridge:
            _bridge.disconnect()
            _bridge = None
        _connected_signature = signature

    # Was fehlt, wird (erneut) versucht. Deckt den Erststart genauso ab wie
    # den Nachzuegler nach einem misslungenen Versuch.
    if _bridge is None and mqtt_cfg.get("host"):
        _verbinde_lokal(mqtt_cfg, sns)
    if _live_listener is None:
        await _verbinde_ecoflow(eco, sns)


async def _fill_missing_models(config: dict, client: EcoFlowClient) -> None:
    """Modellnamen fuer Geraete nachtragen, die noch keinen gespeichert haben.

    Noetig fuer Konfigurationen, die vor der Modell-Erkennung angelegt wurden:
    ohne Modell gilt ein Geraet als nicht steuerbar (models.py), die Bedienung
    waere also ploetzlich verschwunden. Statt das dem Nutzer aufzubuerden,
    holt FlowBridge den Namen einmalig selbst und schreibt ihn in die Config.
    """
    geraete = config["ecoflow"].get("devices", [])
    fehlend = [d for d in geraete if not d.get("model")]
    if not fehlend:
        return
    try:
        bekannt = {g.get("sn"): g.get("productName", "") for g in await client.list_devices()}
    except Exception as exc:
        logger.warning("Modellnamen konnten nicht nachgetragen werden: %s", exc)
        return

    geaendert = False
    for d in fehlend:
        modell = bekannt.get(d["sn"])
        if modell:
            d["model"] = modell
            geaendert = True
            logger.info("Modell fuer %s nachgetragen: %s", d["sn"], modell)
    if geaendert:
        gespeichert = load_config()
        gespeichert["ecoflow"]["devices"] = geraete
        write_config(gespeichert)


async def _supervisor_loop() -> None:
    """Haelt beide MQTT-Verbindungen und macht in groesseren Abstaenden einen
    REST-Resync (quota/all) als Sicherheitsnetz.

    ZWEI Takte, bewusst getrennt:

    * Verbindungen pruefen: alle AUFSICHT_TAKT_S. Billig - steht alles, tut
      _ensure_connected() nichts.
    * REST-Resync: alle poll_interval_seconds (Vorgabe 30). Das sind echte
      Aufrufe bei EcoFlow, die will man nicht im Sekundentakt.

    Vorher lief beides im selben, langsamen Takt. Beim Containerstart auf der
    NAS kostete das messbar Zeit: Zertifikatsabruf scheitert, weil das Netz
    noch nicht steht - danach passierte eine halbe Minute lang nichts, und in
    der Oberflaeche stand so lange "EcoFlow-Broker getrennt". Am 14.08.2026
    von Dirk nachgestellt: nach dem Warten wurde es von selbst gruen. Der
    Fehler war also nicht mehr das Ausbleiben des zweiten Versuchs, sondern
    nur noch, wie lange er auf sich warten liess.
    """
    naechster_resync = 0.0
    naechste_update_pruefung = 0.0  # 0 = sofort beim ersten Durchgang
    while True:
        config = load_config()

        # Update-Pruefung mitlaufen lassen, aber im eigenen, viel langsameren
        # Takt. Vor den Zugangsdaten-Check, damit sie auch dann laeuft, wenn
        # EcoFlow noch gar nicht eingerichtet ist - wer beim Einrichten
        # steckenbleibt, hat vielleicht genau deshalb eine alte Fassung.
        if time.monotonic() >= naechste_update_pruefung:
            naechste_update_pruefung = time.monotonic() + UPDATE_TAKT_S
            try:
                await version.pruefe_jetzt(config)
            except Exception as exc:
                logger.warning("Update-Pruefung uebersprungen: %s", exc)
        eco = config["ecoflow"]
        if not eco.get("access_key") or not eco.get("secret_key") or not eco.get("devices"):
            await asyncio.sleep(10)
            continue

        await _ensure_connected(config)

        # Zustand der Cloud-Verbindung veroeffentlichen - dritte, unabhaengige
        # Ausfallquelle neben FlowBridge selbst und dem Geraet. Sendet nur bei
        # Aenderung, darf also im schnellen Takt mitlaufen.
        if _bridge:
            try:
                _bridge.publish_ecoflow_availability(
                    _live_listener is not None and _live_listener.is_connected()
                )
            except Exception as exc:
                logger.warning("EcoFlow-Verfuegbarkeit nicht publiziert: %s", exc)

        if time.monotonic() >= naechster_resync:
            naechster_resync = time.monotonic() + int(
                config["mqtt"].get("poll_interval_seconds", 30)
            )
            client = EcoFlowClient(eco["access_key"], eco["secret_key"])
            await _fill_missing_models(config, client)

            for device in eco["devices"]:
                sn = device["sn"]
                try:
                    quota = await client.get_quota_all(sn)
                    # from_push=False: REST ist kein Lebensnachweis (s. _apply_quota_update)
                    _device_errors.pop(sn, None)
                    _apply_quota_update(sn, quota, from_push=False)
                except Exception as exc:
                    # EIN Zweig fuer alle Fehler. Es waren zwei, und sie sind
                    # auseinandergelaufen: Der Auth-Fall protokollierte nur und
                    # veroeffentlichte den Zustand NICHT.
                    #
                    # Am 16.08.2026 live vorgefuehrt. Nach dem Wechsel der
                    # EcoFlow-Schluessel lief FlowBridge sieben Minuten mit dem
                    # alten Paar: im Protokoll alle 30 s "accessKey is invalid",
                    # auf dem lokalen Broker unveraendert
                    #   flowbridge/<sn>/available = online
                    # Und das waere so geblieben - _publish_state() ist die
                    # einzige Stelle, die OFFLINE_AFTER_SECONDS auswertet, und
                    # sie lief auf diesem Pfad nie. Die Obergrenze von heute
                    # frueh rechnete richtig und kam nie zum Zug.
                    #
                    # Der Unterschied zwischen den Faellen ist allein der
                    # Protokollrang: Ein ungueltiger Schluessel bleibt ohne
                    # Zutun bestehen (ERROR), ein Netzfehler vergeht meist von
                    # selbst (WARNING). Alles Weitere ist identisch - und steht
                    # deshalb nur noch einmal da.
                    if isinstance(exc, EcoFlowAuthError):
                        logger.error("EcoFlow-Auth fehlgeschlagen fuer %s: %s", sn, exc)
                    else:
                        logger.warning("REST-Resync-Fehler fuer %s: %s", sn, exc)
                    _device_errors[sn] = str(exc)
                    # Kein frisches Datum -> online-Flag ggf. auf stale kippen lassen.
                    if sn in _state:
                        _publish_state(sn)

        await asyncio.sleep(AUFSICHT_TAKT_S)


def _restore_setpoints() -> None:
    """Gemerkte Sollwerte aus der config.yaml in den Speicher holen.

    Diese Werte werden bewusst NICHT ans Geraet geschickt - FlowBridge zeigt
    nur wieder an, was es zuletzt selbst gesetzt hat. Ungefragt Befehle beim
    Start abzusetzen koennte einer laufenden Regelung (z.B. im EisBaer) in die
    Quere kommen.

    Wichtig bleibt die Einschraenkung: EcoFlow liefert diese Sollwerte nicht
    zurueck. Wurde in der EcoFlow-App etwas verstellt, oder ging die Pause
    durch Aus- und Einstecken des Netzkabels verloren, zeigt FlowBridge einen
    ueberholten Wert an.
    """
    for sn, werte in read_setpoints().items():
        watt = werte.get("charge_power_watts")
        if isinstance(watt, int):
            _charge_power_set[sn] = watt
        laden = werte.get("ac_charging_enabled")
        if isinstance(laden, bool):
            _ac_charging_set[sn] = laden
    if _charge_power_set or _ac_charging_set:
        logger.info(
            "Gemerkte Sollwerte geladen: %s Ladeleistung(en), %s Lade-Zustand/Zustaende",
            len(_charge_power_set),
            len(_ac_charging_set),
        )


def _passwort_aus_umgebung_uebernehmen() -> None:
    """FLOWBRIDGE_PASSWORD beim ersten Start uebernehmen.

    Schliesst im Container das Zeitfenster, in dem FlowBridge zwar laeuft, aber
    noch gar kein Passwort vergeben ist - in diesem Fenster koennte sonst jeder
    im Netz das erste Passwort setzen. Ein bereits gesetztes Passwort wird
    NICHT ueberschrieben, sonst liesse es sich per Umgebungsvariable
    zuruecksetzen.
    """
    passwort = auth.umgebungs_passwort()
    if not passwort:
        return
    config = load_config()
    if auth.ist_eingerichtet(config):
        return
    try:
        write_config(auth.setze_passwort(config, passwort))
        logger.info("Zugriffsschutz aus FLOWBRIDGE_PASSWORD uebernommen.")
    except auth.AuthError as exc:
        logger.error("FLOWBRIDGE_PASSWORD unbrauchbar: %s", exc)
    except OSError as exc:
        # Genau hier fiel der Start frueher um: Die OSError blieb ungefangen,
        # uvicorn beendete sich, Docker startete neu - endlos, und im Browser
        # war davon nichts zu sehen. _speicher_pruefen() hat den Grund an
        # dieser Stelle laengst gemeldet; abbrechen darf er den Start nicht.
        logger.error("Passwort aus FLOWBRIDGE_PASSWORD nicht speicherbar: %s", exc)


def _speicher_pruefen() -> None:
    """Beschreibbarkeit des Datenordners pruefen und laut melden.

    Laut heisst hier woertlich: Wer das im Container-Protokoll ueberliest,
    sucht sonst an der falschen Stelle. Die Meldung nennt deshalb den Grund
    UND den Befehl, der ihn behebt.
    """
    global _speicher_fehler
    _speicher_fehler = config_schreibprobe()
    if not _speicher_fehler:
        return
    logger.error("=" * 66)
    logger.error("FlowBridge kann seine Daten nicht speichern.")
    logger.error("  %s", _speicher_fehler)
    logger.error("")
    logger.error("Der eingebundene Ordner gehoert einem anderen Benutzer.")
    logger.error("Auf einer Synology behebt das einmalig, per SSH:")
    logger.error("  sudo chown -R 1000:1000 /volume1/docker/flowbridge/data")
    logger.error("")
    logger.error("FlowBridge laeuft weiter, damit diese Meldung lesbar ist -")
    logger.error("speichern laesst sich bis dahin aber nichts.")
    logger.error("=" * 66)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _supervisor_task, _loop
    _loop = asyncio.get_running_loop()  # fuer MQTT-Befehle aus dem paho-Thread
    _speicher_pruefen()
    _passwort_aus_umgebung_uebernehmen()
    # Der Diagnose-Schalter muss den Neustart ueberleben: sonst schaltet
    # jemand ihn ein, und nach dem naechsten Container-Neustart waere
    # ausgerechnet der interessante Zeitraum nicht protokolliert.
    if (load_config().get("diagnostics") or {}).get("enabled"):
        _diagnose.einschalten()
    # Dasselbe fuers Inventar: Es soll ueber Wochen laufen, ein
    # Container-Update darf es nicht stillschweigend abschalten.
    if (load_config().get("analysis") or {}).get("enabled"):
        _inventar.einschalten()
    _restore_setpoints()
    _supervisor_task = asyncio.create_task(_supervisor_loop())
    yield
    if _supervisor_task:
        _supervisor_task.cancel()
    if _live_listener:
        _live_listener.disconnect()
    if _bridge:
        _bridge.disconnect()


app = FastAPI(title="FlowBridge", lifespan=lifespan)

# Ohne Anmeldung erreichbar. Bewusst kurz gehalten und exakt aufgezaehlt -
# alles andere unter /api ist geschlossen.
_OFFENE_PFADE = {"/api/auth/state", "/api/auth/login", "/api/auth/password"}

_fehlversuche = auth.Fehlversuche()


def _ist_angemeldet(request: Request, config: dict) -> bool:
    a = auth.auth_config(config)
    return auth.token_gueltig(
        request.cookies.get(auth.SESSION_COOKIE, ""), a.get("session_secret", "")
    )


@app.middleware("http")
async def zugriffsschutz(request: Request, call_next):
    """Schuetzt die gesamte HTTP-Schnittstelle.

    Absichtlich als Middleware und NICHT als Abhaengigkeit je Route: eine
    Route, an der die Abhaengigkeit vergessen wird, waere still offen. Hier
    ist der Standard "geschlossen", und Ausnahmen stehen an einer Stelle.

    Die Oberflaeche selbst (HTML/JS) bleibt frei zugaenglich - sie enthaelt
    keine Daten, sondern holt sie sich ueber genau diese Schnittstelle.
    """
    pfad = request.url.path
    if not pfad.startswith("/api/") or pfad in _OFFENE_PFADE:
        # Ist bereits ein Passwort gesetzt, darf /api/auth/password NICHT mehr
        # offen sein - sonst koennte es jeder ohne Anmeldung neu setzen.
        if pfad == "/api/auth/password":
            config = load_config()
            if auth.ist_eingerichtet(config) and not _ist_angemeldet(request, config):
                return JSONResponse({"detail": "Nicht angemeldet."}, status_code=401)
        return await call_next(request)

    config = load_config()
    if not auth.ist_eingerichtet(config):
        return JSONResponse(
            {"detail": "Zugriffsschutz ist noch nicht eingerichtet.",
             "setup_required": True},
            status_code=401,
        )
    if not _ist_angemeldet(request, config):
        return JSONResponse({"detail": "Nicht angemeldet."}, status_code=401)
    return await call_next(request)


class DeviceEntry(BaseModel):
    sn: str
    name: str = ""
    model: str = ""  # productName aus der EcoFlow-Geraeteliste


class SetupRequest(BaseModel):
    access_key: str
    secret_key: str
    mqtt_host: str
    mqtt_port: int = 1883
    # Leer = automatisch (flowbridge-<instanz>). Eigene Kennungen braucht,
    # wer mehrere FlowBridges an einem Broker betreibt.
    mqtt_client_id: str = ""
    mqtt_username: str = ""
    mqtt_password: str = ""
    devices: list[DeviceEntry] = []
    language: str = "de"
    theme: str = "dark"


class TestRequest(BaseModel):
    access_key: str
    secret_key: str
    sn: str = ""  # optional: zusaetzlich ein konkretes Geraet pruefen


@app.post("/api/setup/test")
async def test_credentials(req: TestRequest) -> dict:
    """Verbindungstest fuer die Setup-Maske: nur Erreichbarkeit/Gueltigkeit pruefen, nichts speichern."""
    # In der Einstellungen-Ansicht kommt der Secret-Key maskiert aus
    # /api/config zurueck. Wird er unveraendert gelassen, schickt das Frontend
    # den Platzhalter mit - der ging vorher ungeprueft an EcoFlow und fuehrte
    # zu "signature is wrong", obwohl die gespeicherten Zugangsdaten gueltig
    # sind. Deshalb hier (wie in save_setup) auf den gespeicherten Wert
    # zurueckfallen.
    secret_key = req.secret_key
    if not secret_key or secret_key == MASK_PLACEHOLDER:
        secret_key = load_config()["ecoflow"].get("secret_key", "")
        if not secret_key:
            raise HTTPException(
                status_code=400, detail="Kein Secret-Key vorhanden – bitte eintragen."
            )

    client = EcoFlowClient(req.access_key, secret_key)
    try:
        cert = await client.get_mqtt_certificate()
    except EcoFlowAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    result = {"ok": True, "ecoflow_broker": f"{cert.url}:{cert.port}"}
    if req.sn:
        try:
            quota = await client.get_quota_all(req.sn)
        except EcoFlowAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except EcoFlowApiError as exc:
            raise HTTPException(
                status_code=400, detail=f"Gerät '{req.sn}' nicht erreichbar: {exc}"
            ) from exc
        result["device_fields"] = len(quota)
    return result


@app.post("/api/setup/discover")
async def discover_devices(req: TestRequest) -> dict:
    """Geraete des Kontos auflisten - erspart das Abtippen von Seriennummern.

    Liefert auch productName, damit das Modell nicht ausgewaehlt (und damit
    falsch ausgewaehlt) werden muss. Ob FlowBridge ein Modell auch steuern
    kann, steht als "controllable" dabei.
    """
    secret_key = req.secret_key
    if not secret_key or secret_key == MASK_PLACEHOLDER:
        secret_key = load_config()["ecoflow"].get("secret_key", "")
        if not secret_key:
            raise HTTPException(status_code=400, detail="Kein Secret-Key vorhanden.")

    client = EcoFlowClient(req.access_key, secret_key)
    try:
        geraete = await client.list_devices()
    except EcoFlowAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except EcoFlowApiError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "devices": [
            {
                "sn": g.get("sn", ""),
                "model": g.get("productName", ""),
                "online": bool(g.get("online")),
                "controllable": models.is_controllable(g.get("productName")),
                "support_level": models.support_level(g.get("productName")),
            }
            for g in geraete
        ]
    }


@app.post("/api/setup")
async def save_setup(req: SetupRequest) -> dict:
    config = load_config()
    config["ecoflow"]["access_key"] = req.access_key
    # Maskierter Platzhalter kommt zurueck, wenn das Frontend ein bereits
    # gesetztes Secret unveraendert mitschickt (Settings-Ansicht) - dann den
    # echten, gespeicherten Wert behalten statt ihn zu ueberschreiben.
    if req.secret_key and req.secret_key != MASK_PLACEHOLDER:
        config["ecoflow"]["secret_key"] = req.secret_key
    config["ecoflow"]["devices"] = [d.model_dump() for d in req.devices]
    config["mqtt"]["host"] = req.mqtt_host
    config["mqtt"]["port"] = req.mqtt_port
    # Auch serverseitig pruefen, nicht nur im Formular: Die Zehn-Zeichen-Regel
    # kommt vom EisBaer, und wer /api/setup direkt anspricht, umginge das
    # Formular sonst und merkte es erst beim Import drueben.
    client_id = req.mqtt_client_id.strip()
    if client_id and len(client_id) < MIN_CLIENT_ID_LAENGE:
        raise HTTPException(
            status_code=400,
            detail=f"Die Client-ID braucht mindestens {MIN_CLIENT_ID_LAENGE} Zeichen.",
        )
    config["mqtt"]["client_id"] = client_id
    config["mqtt"]["username"] = req.mqtt_username
    if req.mqtt_password and req.mqtt_password != MASK_PLACEHOLDER:
        config["mqtt"]["password"] = req.mqtt_password
    config["ui"]["language"] = req.language
    config["ui"]["theme"] = req.theme
    write_config(config)
    return {"ok": True}


ERLAUBTE_THEMES = ("dark", "light")
ERLAUBTE_SPRACHEN = ("de", "en")


class UiRequest(BaseModel):
    theme: str
    language: str


@app.post("/api/ui")
async def save_ui(req: UiRequest) -> dict:
    """Darstellungs-Vorgabe dieser Installation.

    Getrennt von /api/setup, obwohl das dieselben zwei Felder mitschreibt:
    Dort sind sie ein Nebenprodukt des Speicherns (das Formular schickt mit,
    was der Kopf der Seite gerade zeigt), hier sind sie eine ausdrueckliche
    Entscheidung. Wer nur das Aussehen umstellen will, soll nicht das ganze
    Einrichtungsformular abschicken muessen - dabei koennte er ungewollt
    etwas anderes mitspeichern.

    Die Werte werden gegen feste Listen geprueft: Ein Tippfehler landete
    sonst in der config.yaml, und die Oberflaeche stuende beim naechsten
    Start vor einem Theme, das es nicht gibt.
    """
    if req.theme not in ERLAUBTE_THEMES:
        raise HTTPException(status_code=400, detail=f"Unbekanntes Theme: {req.theme}")
    if req.language not in ERLAUBTE_SPRACHEN:
        raise HTTPException(status_code=400, detail=f"Unbekannte Sprache: {req.language}")
    config = load_config()
    config["ui"]["theme"] = req.theme
    config["ui"]["language"] = req.language
    write_config(config)
    logger.info("Darstellungs-Vorgabe gesetzt: %s / %s", req.theme, req.language)
    return {"ok": True}


class UpdateEinstellung(BaseModel):
    enabled: bool


@app.post("/api/update")
async def save_update(req: UpdateEinstellung) -> dict:
    """Hintergrundpruefung ein- oder ausschalten.

    Eigener Endpunkt aus demselben Grund wie /api/ui: eine ausdrueckliche
    Entscheidung, kein Nebenprodukt des Einrichtungsformulars. Und diese hier
    ist eine Datenschutz-Entscheidung - sie gehoert an eine Stelle, an der
    daneben steht, was dabei abgerufen wird.

    Ausschalten heisst nicht "nie wieder": Der Knopf "Jetzt pruefen" bleibt
    und fragt trotzdem (siehe /api/version/check). Ein Klick ist eine
    Handlung, kein stiller Abruf - das ist der ganze Unterschied.
    """
    config = load_config()
    config.setdefault("update", {})["enabled"] = req.enabled
    write_config(config)
    logger.info("Update-Pruefung %s", "eingeschaltet" if req.enabled else "abgeschaltet")
    if req.enabled:
        # Sofort nachsehen statt bis zum naechsten Takt zu warten - sonst
        # stuende nach dem Einschalten bis zu sechs Stunden "nicht geprueft".
        await version.pruefe_jetzt(config)
    return {"ok": True}


@app.get("/api/config")
async def get_config() -> dict:
    config = mask_secrets(load_config())
    # Was FlowBridge verwendet, wenn das Feld leer bleibt. Die Oberflaeche
    # zeigt es als Platzhalter - sonst raet man, was "automatisch" bedeutet.
    config["mqtt"] = {**config["mqtt"], "client_id_auto": standard_client_id()}
    # Je Geraet die passenden Rasterstufen und die Steuerbarkeit mitliefern -
    # modellabhaengig, damit ein Delta nicht den 870-W-Regler des River 2 sieht.
    config["ecoflow"] = {
        **config["ecoflow"],
        "devices": [
            {
                **d,
                "controllable": models.is_controllable(d.get("model")),
                "support_level": models.support_level(d.get("model")),
                "charge_watts_steps": models.charge_watts_steps(d.get("model")),
                # Felder, die das Modell meldet, aber nicht annimmt - die
                # Oberflaeche zeigt sie dann an, statt sie anzubieten.
                "readonly_fields": list(models.nur_lesbar(d.get("model"))),
            }
            for d in config["ecoflow"].get("devices", [])
        ],
    }
    return config


@app.get("/api/state")
async def get_state() -> dict:
    """Jedes KONFIGURIERTE Geraet taucht auf - auch eines, das nie Daten liefert.

    Sonst haengt so ein Geraet im UI dauerhaft auf "lade ..." und der Grund
    (falsche SN, fremdes EcoFlow-Konto, o.ae.) bleibt unsichtbar, obwohl er
    hier laengst bekannt ist. Das faellt erst bei mehreren Geraeten auf.

    _state selbst wird bewusst NICHT mit Platzhaltern befuellt - sonst wuerden
    leere Zustaende an den lokalen Broker gepublisht.
    """
    result: dict[str, dict] = {}
    for device in load_config()["ecoflow"].get("devices", []):
        sn = device["sn"]
        entry = dict(_state.get(sn) or {"sn": sn, "online": None})
        if sn in _device_errors:
            entry["error"] = _device_errors[sn]
        # Damit die Oberflaeche "seit 22 h kein Lebenszeichen" schreiben kann
        # statt nur "unbekannt" - der Unterschied zwischen einer Push-Luecke
        # und einem abgeschalteten Geraet ist genau diese Zahl.
        stille = _stille_sekunden(sn)
        if stille is not None:
            entry["silence_seconds"] = int(stille)
        result[sn] = entry
    # Geraete, die (noch) in der Config fehlen, aber Daten haben, nicht verlieren.
    for sn, status in _state.items():
        result.setdefault(sn, status)
    return result


@app.post("/api/refresh/{sn}")
async def refresh_device(sn: str) -> dict:
    """Sofortige Statusabfrage per REST, ohne aufs Poll-Intervall zu warten.

    Nuetzlich vor allem, wenn die MQTT-Push-Verbindung klemmt - im Normalfall
    ist der Push ohnehin schneller. Zaehlt bewusst NICHT als Lebenszeichen
    (from_push=False): quota/all wird aus dem Cloud-Cache beantwortet und
    saehe auch bei getrenntem Geraet erfolgreich aus.
    """
    config = load_config()
    eco = config["ecoflow"]
    if not eco.get("access_key") or not eco.get("secret_key"):
        raise HTTPException(status_code=400, detail="EcoFlow-Zugangsdaten fehlen.")

    client = EcoFlowClient(eco["access_key"], eco["secret_key"])
    try:
        quota = await client.get_quota_all(sn)
    except EcoFlowAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except EcoFlowApiError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _device_errors.pop(sn, None)
    _apply_quota_update(sn, quota, from_push=False)
    return {"ok": True, "fields": len(quota)}


@app.get("/api/history/{sn}")
async def get_history(sn: str, minutes: int = 60) -> dict:
    """Aufgezeichneter Verlauf eines Geraets fuer die Chart-Kachel.

    `minutes` begrenzt den Ausschnitt; mehr als der Ringpuffer haelt
    (HISTORY_MAX_POINTS) gibt es nicht.
    """
    grenze = time.time() - max(1, minutes) * 60
    punkte = [p for p in _history.get(sn, []) if p["t"] >= grenze]
    return {
        "sn": sn,
        "interval_seconds": HISTORY_INTERVAL_SECONDS,
        "fields": list(HISTORY_FIELDS),
        "points": punkte,
    }


class LoginRequest(BaseModel):
    password: str


class PasswordRequest(BaseModel):
    password: str
    current_password: str | None = None


def _herkunft(request: Request) -> str:
    return request.client.host if request.client else "unbekannt"


def _setze_cookie(response: Response, config: dict) -> None:
    a = auth.auth_config(config)
    stunden = int(a.get("session_hours") or auth.DEFAULT_SESSION_HOURS)
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.create_token(a["session_secret"], stunden),
        max_age=stunden * 3600,
        httponly=True,   # kein Zugriff aus JavaScript
        samesite="lax",  # kein Mitschicken bei Anfragen von fremden Seiten
    )


@app.get("/api/auth/state")
async def auth_state(request: Request) -> dict:
    """Sagt der Oberflaeche, welchen Bildschirm sie zeigen muss."""
    config = load_config()
    eingerichtet = auth.ist_eingerichtet(config)
    return {
        "configured": eingerichtet,
        "authenticated": eingerichtet and _ist_angemeldet(request, config),
        "min_length": auth.MIN_PASSWORT_LAENGE,
        # Bewusst an diesem offenen Endpunkt: Solange nichts gespeichert
        # werden kann, kommt niemand ueber die Anmeldung hinaus - der Grund
        # muss also vor der Anmeldung sichtbar sein.
        "storage_error": _speicher_fehler,
    }


@app.post("/api/auth/login")
async def auth_login(req: LoginRequest, request: Request, response: Response) -> dict:
    config = load_config()
    if not auth.ist_eingerichtet(config):
        raise HTTPException(status_code=400, detail="Es ist noch kein Passwort gesetzt.")

    herkunft = _herkunft(request)
    try:
        _fehlversuche.pruefe(herkunft)
    except auth.AuthError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    a = auth.auth_config(config)
    if not auth.verify_password(req.password, a["password_salt"], a["password_hash"]):
        _fehlversuche.fehlschlag(herkunft)
        # Bewusst dieselbe Meldung fuer jeden Fehlgrund.
        raise HTTPException(status_code=401, detail="Passwort falsch.")

    _fehlversuche.erfolg(herkunft)
    _setze_cookie(response, config)
    return {"ok": True}


@app.post("/api/auth/logout")
async def auth_logout(response: Response) -> dict:
    response.delete_cookie(auth.SESSION_COOKIE)
    return {"ok": True}


@app.post("/api/auth/password")
async def auth_set_password(
    req: PasswordRequest, request: Request, response: Response
) -> dict:
    """Passwort erstmalig setzen oder aendern.

    Beim Aendern ist das aktuelle Passwort Pflicht - eine uebernommene Sitzung
    allein soll nicht genuegen, um jemanden dauerhaft auszusperren.
    """
    config = load_config()
    if auth.ist_eingerichtet(config):
        a = auth.auth_config(config)
        if not req.current_password or not auth.verify_password(
            req.current_password, a["password_salt"], a["password_hash"]
        ):
            raise HTTPException(status_code=401, detail="Aktuelles Passwort falsch.")
    try:
        neu = auth.setze_passwort(config, req.password)
    except auth.AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_config(neu)
    # Neues Sitzungsgeheimnis: alle anderen Sitzungen sind damit ungueltig.
    _setze_cookie(response, neu)
    logger.info("Zugriffsschutz-Passwort gesetzt bzw. geaendert.")
    return {"ok": True}


class DiagnoseRequest(BaseModel):
    enabled: bool


def _diagnose_zustand() -> dict:
    return {
        "enabled": _diagnose.aktiv,
        "size_bytes": _diagnose.groesse_bytes(),
        "path": str(config_path().parent / "flowbridge.log"),
        "buffered_lines": len(_diagnose.ring_zeilen()),
        # Fuer den Betreff der Mail, mit der jemand das Paket schickt. Hier
        # mitgeliefert statt ueber einen zweiten Aufruf: Die Oberflaeche holt
        # diesen Zustand ohnehin, und eine Einsendung ohne Versionsnummer ist
        # nur die halbe Information (siehe Kopfzeile der Protokolldatei).
        "version": version.get_version(),
    }


@app.get("/api/diagnostics")
async def diagnose_zustand() -> dict:
    return _diagnose_zustand()


@app.post("/api/diagnostics")
async def diagnose_schalten(req: DiagnoseRequest) -> dict:
    config = load_config()
    config["diagnostics"] = {**(config.get("diagnostics") or {}), "enabled": req.enabled}
    write_config(config)
    if req.enabled:
        _diagnose.einschalten()
    else:
        _diagnose.ausschalten()
    return _diagnose_zustand()


@app.delete("/api/diagnostics")
async def diagnose_loeschen() -> dict:
    _diagnose.loeschen()
    return _diagnose_zustand()


@app.get("/api/diagnostics/download")
async def diagnose_herunterladen() -> RawResponse:
    """Alles, was zur Ferndiagnose noetig ist - in einer Datei.

    Saemtliche Bestandteile sind geschwaerzt bzw. maskiert: diese Datei geht
    per E-Mail durchs Internet (siehe diagnostics.py).
    """
    config = load_config()
    health = await get_health()

    # Was EcoFlow SELBST ueber die Geraete sagt - nicht nur, was hier
    # konfiguriert ist. Weicht beides voneinander ab, greifen die Befehle des
    # falschen Modells und das Geraet verwirft sie stillschweigend. Ohne
    # diesen Abgleich sucht man den Fehler ueberall sonst.
    gemeldet: dict[str, str] = {}
    eco = config.get("ecoflow") or {}
    if eco.get("access_key") and eco.get("secret_key"):
        try:
            client = EcoFlowClient(eco["access_key"], eco["secret_key"])
            for d in await client.list_devices():
                if d.get("sn"):
                    gemeldet[d["sn"]] = d.get("productName") or ""
        except Exception as exc:
            # Kein Grund, deswegen das ganze Paket scheitern zu lassen - dass
            # die Abfrage nicht geht, ist selbst ein Befund.
            logger.warning("Geraeteliste fuer die Diagnose nicht abrufbar: %s", exc)

    geraete = []
    for geraet in config["ecoflow"].get("devices", []):
        sn = geraet["sn"]
        modell = geraet.get("model")
        geraete.append({
            "sn": sn,
            "model": modell,
            "product_name": gemeldet.get(sn),
            "support_level": models.support_level(modell),
            "controllable": models.is_controllable(modell),
            "charge_steps": models.charge_watts_steps(modell),
            "online": _state.get(sn, {}).get("online"),
            "felder": len(_quota_cache.get(sn, {})),
            "error": _device_errors.get(sn),
        })

    bericht = diagnostics.baue_bericht(
        version=version.get_version(),
        update_status=version.check_update(config).status,
        health=health,
        geraete=geraete,
        laufzeit_s=_diagnose.laufzeit_sekunden(),
        datei_protokoll=_diagnose.aktiv,
    )

    topics = "(kein lokaler Broker verbunden)"
    if _bridge:
        zeilen = [_bridge.bridge_availability_topic, _bridge.ecoflow_availability_topic]
        for geraet in config["ecoflow"].get("devices", []):
            sn = geraet["sn"]
            zeilen += [
                _bridge.availability_topic(sn),
                _bridge.state_topic(sn),
                _bridge.command_topic(sn, "<eigenschaft>"),
            ]
        zeilen += sorted(_bridge.veroeffentlichte_topics())
        topics = "\n".join(zeilen)

    rohdaten = _diagnose.paket(
        bericht=bericht,
        config_maskiert=yaml.safe_dump(
            mask_secrets(config), allow_unicode=True, sort_keys=False
        ),
        topics=topics,
    )
    stempel = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return RawResponse(
        content=rohdaten,
        media_type="application/zip",
        headers={
            "Content-Disposition":
                f'attachment; filename="flowbridge-diagnose-{stempel}.zip"'
        },
    )


# ------------------------------------------------------------- Feldinventar
class AnalyseRequest(BaseModel):
    enabled: bool


@app.get("/api/analysis")
async def analyse_zustand() -> dict:
    # Version hier ergaenzt und nicht in inventar.zustand(): Das Inventar
    # verwaltet Felder, nicht die Fassung von FlowBridge. Gebraucht wird sie
    # nur fuer den Mail-Betreff in der Oberflaeche.
    return {**_inventar.zustand(), "version": version.get_version()}


@app.post("/api/analysis")
async def analyse_schalten(req: AnalyseRequest) -> dict:
    config = load_config()
    config["analysis"] = {**(config.get("analysis") or {}), "enabled": req.enabled}
    write_config(config)
    if req.enabled:
        _inventar.einschalten()
    else:
        _inventar.ausschalten()
    return _inventar.zustand()


@app.delete("/api/analysis")
async def analyse_zuruecksetzen() -> dict:
    _inventar.zuruecksetzen()
    return _inventar.zustand()


@app.get("/api/analysis/download")
async def analyse_herunterladen() -> RawResponse:
    """Das Inventar als JSON - mit Platzhaltern statt Seriennummern.

    Hier stehen Feldnamen und Messwerte, keine Zugangsdaten; zu schwaerzen
    gibt es daran nichts. Die Seriennummer stand aber als Schluessel unter
    "geraete" - und diese Datei ist genau die, die Mitwirkende HERSCHICKEN
    sollen.

    Bis 16.08.2026 stand hier die Begruendung, sie bleibe lesbar, weil sich
    sonst nichts zuordnen liesse. Derselbe Denkfehler wie in diagnostics.py:
    Fuer die Auswertung braucht es unterscheidbar, nicht identifizierbar. Ich
    hatte ihn dort korrigiert und nicht gesucht, wo er sonst noch steht -
    gefunden hat ihn Dirk, indem er in die Datei schaute.

    GILT NUR FUER DIESEN WEG: Wer sich die feldinventar.json direkt aus dem
    Datenordner kopiert, hat die Seriennummer weiterhin darin. Dort ist sie
    der Schluessel, unter dem gebucht wird, und muss es bleiben - sonst
    verloere das Inventar ueber einen Neustart hinweg die Zuordnung.
    """
    config = load_config()
    platzhalter = diagnostics.geraete_platzhalter(config)
    modelle = {
        platzhalter[g["sn"]]: (g.get("model") or "unbekannt")
        for g in config["ecoflow"].get("devices", [])
        if g.get("sn") in platzhalter
    }
    stempel = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return RawResponse(
        content=_inventar.als_json(platzhalter, modelle),
        media_type="application/json",
        headers={
            "Content-Disposition":
                f'attachment; filename="flowbridge-feldinventar-{stempel}.json"'
        },
    )


def _export_teile(mit_modulen: bool) -> tuple[list, list]:
    """Kanaele und Profile ueber alle konfigurierten Geraete."""
    config = load_config()
    base = config["mqtt"].get("base_topic", "flowbridge")
    kanaele: list = []
    profile: list = []
    gesehen: set[str] = set()
    for geraet in config["ecoflow"].get("devices", []):
        sn = geraet["sn"]
        status = _state.get(sn) or {}
        modell = geraet.get("model")
        kanaele += exporters.baue_kanaele(
            sn, geraet.get("name") or sn, status, base, modell,
            models.is_controllable(modell), mit_modulen,
            nur_lesbar=models.nur_lesbar(modell),
        )
        # Profile sind shape-basiert: zwei gleiche Modelle teilen sie sich,
        # deshalb nur einmal ins XML.
        for profil_id, wurzel in exporters.baue_profile(status, modell, mit_modulen):
            if profil_id not in gesehen:
                gesehen.add(profil_id)
                profile.append((profil_id, wurzel))
    return kanaele, profile


def _datei(inhalt, dateiname: str, typ: str) -> RawResponse:
    return RawResponse(
        content=inhalt.encode("utf-8") if isinstance(inhalt, str) else inhalt,
        media_type=typ,
        headers={"Content-Disposition": f'attachment; filename="{dateiname}"'},
    )


def _zusatz(mit_modulen: bool) -> str:
    """Modul-Variante im Dateinamen kenntlich machen - sonst liegen beim
    Anwender zwei gleichnamige Dateien im Download-Ordner."""
    return "-mit-modulen" if mit_modulen else ""


@app.get("/api/export/generic")
async def export_generisch(modules: bool = False) -> RawResponse:
    """Schlichte Topic-Liste zum Nachschlagen - fuer jeden MQTT-Client."""
    kanaele, _ = _export_teile(modules)
    return _datei(
        exporters.generische_csv(kanaele),
        f"flowbridge-topics{_zusatz(modules)}.csv",
        "text/csv; charset=utf-8",
    )


@app.get("/api/export/eisbaer/channels")
async def export_eisbaer_kanaele(modules: bool = False) -> RawResponse:
    """Kanaleditor-CSV. ACHTUNG: erst das XML importieren, dann diese Datei -
    sie verweist auf ProfileIds, die dann schon existieren muessen."""
    kanaele, _ = _export_teile(modules)
    return _datei(
        exporters.eisbaer_csv(kanaele),
        f"flowbridge-kanaleditor{_zusatz(modules)}.csv",
        "text/csv; charset=utf-8",
    )


@app.get("/api/export/eisbaer/profiles")
async def export_eisbaer_profile(modules: bool = False) -> RawResponse:
    """Payloadeditor-XML fuer die JSON-Topics."""
    _, profile = _export_teile(modules)
    return _datei(
        exporters.eisbaer_xml(profile),
        f"flowbridge-payloadeditor{_zusatz(modules)}.xml",
        "application/xml; charset=utf-8",
    )


@app.get("/api/export/eisbaer/zip")
async def export_eisbaer_zip(modules: bool = False) -> RawResponse:
    """Beide EisBaer-Dateien samt Kurzanleitung in einem Archiv."""
    kanaele, profile = _export_teile(modules)
    return _datei(
        exporters.eisbaer_zip(kanaele, profile),
        f"flowbridge-eisbaer{_zusatz(modules)}.zip",
        "application/zip",
    )


@app.get("/api/version")
async def get_version_info() -> dict:
    """Laufende Version + Zustand der Update-Pruefung.

    Eigener Endpunkt statt Anhaengsel an /api/health: die Version aendert sich
    nur beim Neustart, waehrend health im 5-Sekunden-Takt abgefragt wird.
    """
    return {
        "version": version.get_version(),
        "update": version.check_update(load_config()).as_dict(),
    }


@app.post("/api/version/check")
async def update_pruefen() -> dict:
    """Jetzt nachsehen, ohne auf den Takt zu warten.

    Der Knopf dazu ist mehr als Bequemlichkeit: Wer die Pruefung abgeschaltet
    hat, kommt so trotzdem einmal an die Auskunft, ohne sie dauerhaft
    einzuschalten. Deshalb prueft dieser Weg auch dann - er ist eine
    ausdrueckliche Handlung, kein Hintergrundabruf.
    """
    config = load_config()
    bereich = dict(config.get("update") or {})
    bereich["enabled"] = True  # nur fuer DIESEN einen Aufruf
    return (await version.pruefe_jetzt({**config, "update": bereich})).as_dict()


@app.get("/api/health")
async def get_health() -> dict:
    """Die drei Verbindungen, die auseinanderfallen koennen - jede einzeln sichtbar.

    Wichtig ist die Trennung: der EcoFlow-Broker kann stehen, waehrend das
    Geraet selbst weg ist (dann kommen nur keine Push-Nachrichten mehr), und
    der lokale Broker ist voellig unabhaengig von beidem.
    """
    config = load_config()
    devices = config["ecoflow"].get("devices", [])
    return {
        "ecoflow_broker": {
            "configured": bool(config["ecoflow"].get("access_key")),
            "connected": _live_listener is not None and _live_listener.is_connected(),
        },
        "local_broker": {
            "configured": bool(config["mqtt"].get("host")),
            "connected": _bridge is not None and _bridge.is_connected(),
            "host": config["mqtt"].get("host", ""),
        },
        "devices": {
            "configured": len(devices),
            "online": sum(1 for d in devices if _state.get(d["sn"], {}).get("online") is True),
            "offline": sum(1 for d in devices if _state.get(d["sn"], {}).get("online") is False),
            # Weder online noch nachweislich offline: nie Daten gesehen, falsche SN,
            # Push-Kanal noch nicht da. Muss getrennt zaehlbar sein, sonst wirkt
            # "1 von 3 online" faelschlich wie ein gruener Gesamtzustand.
            "unknown": sum(
                1 for d in devices if _state.get(d["sn"], {}).get("online") is None
            ),
        },
    }


class CommandRequest(BaseModel):
    sn: str
    property: str
    value: str


async def _execute_command(sn: str, property_name: str, value: str) -> dict:
    """Gemeinsamer Befehlspfad fuer Web-UI UND MQTT.

    Bewusst eine Funktion: sonst wuerden die beiden Wege mit der Zeit
    auseinanderlaufen (Validierung, Modell-Weiche, Merken der Sollwerte).
    Wirft CommandError / EcoFlowAuthError / ValueError - der jeweilige
    Aufrufer uebersetzt das in HTTP bzw. eine Log-Zeile.
    """
    config = load_config()
    eco = config["ecoflow"]
    if not eco.get("access_key") or not eco.get("secret_key"):
        raise CommandError("EcoFlow-Zugangsdaten fehlen – erst Setup abschliessen.")

    # Nur Modelle steuern, deren Befehle bekannt sind - sonst kaeme eine
    # "Success"-Antwort ohne jede Wirkung (siehe models.py).
    modell = next((d.get("model") for d in eco.get("devices", []) if d["sn"] == sn), None)
    modul = models.command_module(modell)
    if modul is None:
        raise CommandError(
            f"Für das Modell '{modell or 'unbekannt'}' sind keine Steuerbefehle bekannt."
        )

    client = EcoFlowClient(eco["access_key"], eco["secret_key"])

    # Manche Befehle muessen ein VOLLSTAENDIGES Param-Set schicken und nehmen
    # die ungeaenderten Felder aus dem zuletzt gelesenen Stand (s.
    # commands_river2._ac_out_cfg). Direkt nach dem Start ist der noch leer -
    # der erste Push braucht ein paar Sekunden. Frueher gingen dann geratene
    # Vorgabewerte mit hinaus und verstellten X-Boost, Spannung und Frequenz
    # ungefragt; heute bricht der Befehlsbauer lieber ab.
    #
    # Damit daraus kein "dann warte halt" wird, holen wir den Stand hier
    # einmalig per REST nach. Nur wenn wirklich nichts da ist - im Normalfall
    # kostet das keinen zusaetzlichen Aufruf.
    if sn not in _state:
        try:
            # setdefault().update() wie in der Aufsichtsschleife (s. dort):
            # der Zwischenspeicher wird ergaenzt, nicht ersetzt - sonst ginge
            # ein Push verloren, der zwischendurch hereinkam.
            _quota_cache.setdefault(sn, {}).update(await client.get_quota_all(sn))
            _publish_state(sn)
            logger.info("Zustand fuer %s vor dem Befehl per REST nachgeholt.", sn)
        except Exception as exc:
            # Bewusst ALLE Fehler, nicht nur die der EcoFlow-Schnittstelle:
            # Dieses Nachholen ist eine Bequemlichkeit. Befehle ohne
            # vollstaendiges Param-Set (12-V-Ausgang, Ladelimit, Ladepause)
            # brauchen den Stand gar nicht und muessen weiter funktionieren,
            # auch wenn hier irgendetwas Unerwartetes schiefgeht. Die Befehle,
            # die ihn brauchen, melden sich gleich selbst mit Klartext.
            logger.warning("Zustand fuer %s nicht nachholbar: %s", sn, exc)

    data = await modul.apply_command(client, sn, property_name, value, _state.get(sn))

    # Diese beiden Sollwerte melden manche Modelle nicht zurueck - selbst
    # merken und dauerhaft ablegen (s. _charge_power_set).
    if property_name == "charge_power_watts":
        _charge_power_set[sn] = int(value)
        write_setpoint(sn, "charge_power_watts", int(value))
        _publish_state(sn)
    elif property_name == "ac_charging_enabled":
        an = value.strip().lower() == "on"
        _ac_charging_set[sn] = an
        # Zeitpunkt VOR dem _publish_state setzen - sonst laeuft die Pruefung
        # dort ohne Schonfrist und verwirft den eben gesetzten Zustand.
        _ac_charging_gesetzt_um[sn] = time.monotonic()
        write_setpoint(sn, "ac_charging_enabled", an)
        _publish_state(sn)
    return data


def _handle_mqtt_command(sn: str, property_name: str, value: str) -> None:
    """Befehl vom lokalen Broker (EisBaer, HA, ...).

    Laeuft im paho-Netzwerk-Thread, _execute_command ist async - deshalb der
    Umweg ueber den asyncio-Loop des Servers. Fehler landen NUR im Log: auf
    dem MQTT-Weg gibt es niemanden, dem man eine Fehlermeldung zurueckgeben
    koennte, und der Netzwerk-Thread darf daran nicht sterben.
    """
    if _loop is None:
        logger.warning("MQTT-Befehl verworfen: Server noch nicht bereit.")
        return

    async def _lauf() -> None:
        try:
            await _execute_command(sn, property_name, value)
            logger.info("MQTT-Befehl ausgefuehrt: %s %s = %s", sn, property_name, value)
        except (CommandError, EcoFlowAuthError, EcoFlowApiError, ValueError) as exc:
            logger.warning("MQTT-Befehl abgelehnt (%s %s = %s): %s", sn, property_name, value, exc)
        except Exception as exc:
            logger.exception("MQTT-Befehl fehlgeschlagen (%s %s): %s", sn, property_name, exc)

    asyncio.run_coroutine_threadsafe(_lauf(), _loop)


@app.post("/api/command")
async def send_command(req: CommandRequest) -> dict:
    """Steuerbefehl uebers Web-UI absetzen - derselbe Pfad wie ueber MQTT.

    JEDER Fehler bekommt hier einen Text. Vorher standen nur CommandError und
    EcoFlowAuthError in der Liste, alles andere fiel roh durch und wurde zu
    "500 Internal Server Error" - das Frontend zeigt bei fehlendem `detail`
    genau diesen Statustext an (api.ts).

    Am 16.08.2026 im Feld getroffen: Nach einem Stromausfall hatte sich der
    Speicher wegen Tiefentladung abgeschaltet. Die Cloud war erreichbar und
    lieferte auf quota/all brav ihren Cache weiter, konnte den Befehl aber
    nicht zustellen -> EcoFlowApiError -> "500 Internal Server Error", ohne
    einen Hinweis darauf, dass schlicht das Geraet fehlte.

    Die Trennung der drei Faelle ist keine Kosmetik, sie sagt jeweils etwas
    anderes darueber aus, WO es klemmt:
      502 - EcoFlow hat geantwortet, aber ablehnend (meist: Geraet weg)
      503 - EcoFlow war gar nicht erreichbar (DNS, Netz, Zeitueberschreitung)
      400 - der Befehl selbst war ungueltig
    """
    try:
        data = await _execute_command(req.sn, req.property, req.value)
    except CommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EcoFlowAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        # Ungueltiger Wert (Bereich, Format) - der Aufrufer kann das beheben.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EcoFlowApiError as exc:
        logger.warning("Befehl von EcoFlow abgelehnt (%s %s): %s", req.sn, req.property, exc)
        raise HTTPException(
            status_code=502,
            detail=(
                f"EcoFlow hat den Befehl nicht angenommen: {exc} – "
                "meist ist der Speicher gerade nicht mit der Cloud verbunden."
            ),
        ) from exc
    except Exception as exc:
        # Netzfehler und alles Unerwartete. Mit Traceback ins Protokoll, damit
        # das Diagnose-Paket den Fall traegt - nach aussen nur der Klartext.
        logger.exception("Befehl fehlgeschlagen (%s %s): %s", req.sn, req.property, exc)
        raise HTTPException(
            status_code=503,
            detail=(
                f"EcoFlow war nicht erreichbar: {exc.__class__.__name__}: {exc} – "
                "Netzverbindung der FlowBridge prüfen."
            ),
        ) from exc
    return {"ok": True, "data": data}


frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

"""
Diagnose-Paket: Protokoll und Zustand zum Verschicken.

Zweck: Wenn FlowBridge bei jemand anderem nicht tut, was es soll, ist die
Beschreibung meist "geht nicht". Dieses Paket liefert das, was man wirklich
braucht - Version, maskierte Konfiguration, Zustand der drei Verbindungen,
Feldzahl je Geraet und das Protokoll.

DIE KERNSACHE IST DIE SCHWAERZUNG, nicht das Protokollieren.

Diese Datei geht per E-Mail durchs Internet. Stuenden dort Access- und
Secret-Key drin, haette der Absender damit die Kontrolle ueber seinen Speicher
verschickt. Die Signierung fasst die Schluessel an, ein ausfuehrliches
Protokoll ueber HTTP-Aufrufe haette sie also sofort drin.

Deshalb sitzt die Schwaerzung im **Formatter** und nicht an den Aufrufstellen:
Wer eine neue Protokollzeile schreibt, kann sie nicht vergessen. Freiwillige
Disziplin haelt an so einer Stelle nicht.

Zwei Wege, damit einer den anderen auffaengt:

1. Woertlich: die aktuell konfigurierten Geheimnisse werden gesucht und ersetzt.
   Trifft immer, egal in welcher Schreibweise sie in der Zeile stehen.
2. Nach Muster: alles, was aussieht wie ein Schluessel, ein Passwort oder eine
   Signatur, wird ebenfalls unkenntlich gemacht. Faengt auch das ab, was in
   der Konfiguration gar nicht (mehr) steht - etwa ein falsch eingetippter
   Schluessel aus einem fehlgeschlagenen Verbindungstest.

Seriennummer und Kontokennung werden nicht unkenntlich gemacht, sondern
UMBENANNT: "<GERAET-1>", "<KONTO>". Der Unterschied ist wichtig - ein
durchgaengiges [geschwaerzt] machte aus zwei Geraeten eines und waere fuer die
Auswertung wertlos.

Bis 16.08.2026 stand hier, die Seriennummer bleibe bewusst stehen, weil sich
ohne sie "kaum etwas analysieren" lasse. Das verwechselte IDENTIFIZIERBAR mit
UNTERSCHEIDBAR. Gebraucht wird nur Letzteres: Geraete auseinanderhalten und
Zeilen einander zuordnen. Welches Stueck Blech dahintersteht, weiss der
Absender - der Empfaenger braucht es nicht, und die Zuordnung Platzhalter ->
Modell steht ohnehin im Bericht.

Dass es lohnt, zeigt die Messung an einem echten Protokoll (3813 Zeilen):
Seriennummer 3735 mal, Kontokennung 1256 mal. Praktisch jede Zeile.
"""
from __future__ import annotations

import io
import logging
import logging.handlers
import platform
import re
import sys
import time
import zipfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import version

logger = logging.getLogger(__name__)

GESCHWAERZT = "[geschwaerzt]"

# Letzte Zeilen, die IMMER mitlaufen - auch wenn das Datei-Protokoll aus ist.
# Sonst hilft der Schalter nicht: Wer den Fehler sieht, schaltet erst danach
# ein, und dann kommt der Fehler eine Stunde nicht wieder.
RING_ZEILEN = 800

# Wie weit das Protokoll zurueckreicht. Umgeschaltet wird nach GROESSE, nicht
# nach Zeit - die Reichweite ergibt sich also aus der Schreibrate (gemessen
# ~4 KB/min ohne das Rauschen der Fremdbibliotheken, siehe FREMDE_LOGGER).
#
# Und sie saegt: Direkt nach einer Umschaltung ist die neueste Datei leer, es
# bleiben nur die aelteren Staende. Verlassen kann man sich deshalb nur auf
# (MAX_DATEIEN - 1) x MAX_DATEI_BYTES.
#
# Stand bis 14.08.2026 auf 3 x 2 MB = garantiert nur ~17 h. Zu knapp: Die
# Push-Aussetzer, denen wir nachgehen, kommen alle paar Stunden, und wer
# einen am Morgen bemerkt, hat die Nacht davor schon verloren. Jetzt 5 x 5 MB
# = garantiert ~85 h, guenstigstenfalls ~105 h - ein Wochenende passt hinein.
#
# Kosten: 25 MB auf der Platte. Das ZIP bleibt versendbar, Text komprimiert
# rund 10:1 - also wenige MB per E-Mail, auch wenn alle fuenf Dateien voll
# sind. Deutlich groesser sollte es deshalb nicht werden.
MAX_DATEI_BYTES = 5 * 1024 * 1024  # 5 MB je Datei
MAX_DATEIEN = 5  # ... plus vier aeltere Staende

# Fremdbibliotheken, die auf DEBUG zuschuetten. Gemessen am 14.08.2026:
# In einem 17-Minuten-Protokoll stammten 70 % der Datei (162 von 231 KB) von
# httpcore - eine Handvoll "connect_tcp.started"-Zeilen je REST-Aufruf.
# Damit reichte das Protokoll nur ~7,5 Stunden zurueck; ohne das Rauschen
# rund einen Tag. Wer einem Aussetzer nachgeht, der alle paar Stunden kommt,
# braucht genau diesen Vorlauf.
FREMDE_LOGGER = ("httpcore", "httpx", "urllib3", "asyncio")

# Schluessel in der Konfiguration, deren Werte woertlich zu schwaerzen sind.
_GEHEIME_FELDER = (
    ("ecoflow", "access_key"),
    ("ecoflow", "secret_key"),
    ("mqtt", "password"),
    ("auth", "password_hash"),
    ("auth", "password_salt"),
    ("auth", "session_secret"),
)

# Zweites Netz: alles, was AUSSIEHT wie ein Geheimnis.
_MUSTER = (
    re.compile(r"(?i)\b(access[_-]?key\W{0,4})([A-Za-z0-9\-_]{8,})"),
    re.compile(r"(?i)\b(secret[_-]?key\W{0,4})([A-Za-z0-9\-_]{8,})"),
    re.compile(r"(?i)\b(pass(?:word|wort)\W{0,4})(\S{3,})"),
    re.compile(r"(?i)\b(sign\W{0,4})([A-Za-z0-9]{16,})"),
    # Bis zum Zeilenende, nicht nur das naechste Wort: bei
    # "Authorization: Bearer <token>" waere sonst genau das Token stehen
    # geblieben und nur "Bearer" geschwaerzt worden.
    re.compile(r"(?im)\b(authorization\s*[:=]\s*)(.*)$"),
    re.compile(r"(?i)(flowbridge_session=)(\S+)"),
    re.compile(r"(?i)\b(nonce\W{0,4})(\d{4,})"),
)

# MQTT-Kennung des EcoFlow-Kontos, wie sie in jedem Topic-Pfad steht:
#   /open/open-<32 Hexzeichen>/<sn>/quota
# Hier bewusst NICHT als echtes Beispiel ausgeschrieben: Diese Datei geht auf
# GitHub, und die Kennung ist genau das, was der Formatter unten aus jedem
# Protokoll heraushaelt. Sie in den Quelltext zu schreiben, der sie schuetzt,
# waere ein Widerspruch - und es ist am 16.08.2026 beinahe passiert.
# Kein Schluessel, aber kontobezogen - und in einer Datei, die per E-Mail
# verschickt wird, hat sie nichts verloren. 32 Hexzeichen sind eng genug,
# dass das Muster nichts anderes trifft.
_KONTO_KENNUNG = re.compile(r"\bopen-[0-9a-f]{32}\b", re.IGNORECASE)


def _geheimnisse(config: dict) -> list[str]:
    werte: list[str] = []
    for bereich, feld in _GEHEIME_FELDER:
        wert = (config.get(bereich) or {}).get(feld)
        # Sehr kurze Werte nicht woertlich ersetzen - "1" oder "ab" kaeme in
        # jeder zweiten Zeile vor und machte das Protokoll unlesbar.
        if isinstance(wert, str) and len(wert) >= 6:
            werte.append(wert)
    # Laengste zuerst: sonst zerschneidet ein kurzer Treffer einen laengeren.
    return sorted(werte, key=len, reverse=True)


def geraete_platzhalter(config: dict) -> dict[str, str]:
    """sn -> "<GERAET-1>", in der Reihenfolge aus der Konfiguration.

    Die Reihenfolge ist die Zusage: Sie bleibt ueber Neustarts gleich und
    ueber alle fuenf Protokolldateien hinweg, sonst waere ein Verlauf ueber
    mehrere Dateien nicht mehr zusammenzusetzen."""
    geraete = (config.get("ecoflow") or {}).get("devices") or []
    zuordnung: dict[str, str] = {}
    for nummer, geraet in enumerate(geraete, start=1):
        sn = (geraet or {}).get("sn")
        if isinstance(sn, str) and sn:
            zuordnung.setdefault(sn, f"<GERAET-{nummer}>")
    return zuordnung


def benenne_um(text: str, config: dict) -> str:
    """Kennungen durch Platzhalter ersetzen. IDEMPOTENT.

    Getrennt von schwaerze(), weil es zweimal gebraucht wird: einmal als Teil
    der vollen Schwaerzung, und einmal allein fuer Protokolldateien, die schon
    durch den Formatter gelaufen sind. Die Muster von schwaerze() ein zweites
    Mal darueberzuziehen wuerde die bereits ersetzten Stellen erneut treffen
    ("[[geschwaerzt]]"); das Umbenennen dagegen kann man beliebig oft
    anwenden - "<GERAET-1>" enthaelt keine Seriennummer mehr.

    Genau das braucht es fuer Protokolldateien aus der Zeit VOR dieser
    Aenderung: Die liegen unveraendert auf der Platte und landen sonst roh im
    Paket.
    """
    # Kennungen durch NAMEN ersetzen, nicht durch [geschwaerzt]: Was die
    # Auswertung braucht, ist Geraete auseinanderhalten und Zeilen einander
    # zuordnen - nicht, welches Stueck Blech dahintersteht. Ein durchgaengiges
    # [geschwaerzt] koennte das nicht, es macht aus zwei Geraeten eines.
    #
    # Ergaenzt am 16.08.2026 auf Dirks Frage. Im Kopf dieser Datei stand
    # vorher, die Seriennummer bleibe bewusst stehen, weil sich ohne sie
    # "kaum etwas analysieren" lasse. Das verwechselte identifizierbar mit
    # unterscheidbar: Ein stabiler Platzhalter leistet fuer die Auswertung
    # dasselbe, und die Zuordnung zum echten Geraet kennt der Absender
    # ohnehin. Gemessen an einem echten Protokoll standen die Seriennummer
    # 3735 und die Kontokennung 1256 mal drin - bei 3813 Zeilen.
    for sn, name in geraete_platzhalter(config).items():
        text = text.replace(sn, name)
    # Die MQTT-Kennung des EcoFlow-Kontos steht in jedem Topic-Pfad
    # (/open/open-<32 Hex>/<sn>/quota). Sie stammt aus dem Zertifikatsabruf,
    # steht also in KEINEM Konfigurationsfeld - deshalb hier als Muster und
    # nicht ueber _GEHEIME_FELDER. Genau daran ist sie beim ersten Entwurf
    # vorbeigerutscht: Geschaut wurde auf die Konfiguration, nicht auf das,
    # was zur Laufzeit dazukommt.
    return _KONTO_KENNUNG.sub("<KONTO>", text)


def schwaerze(text: str, config: dict) -> str:
    for wert in _geheimnisse(config):
        text = text.replace(wert, GESCHWAERZT)
    text = benenne_um(text, config)
    for muster in _MUSTER:
        text = muster.sub(lambda m: m.group(1) + GESCHWAERZT, text)
    return text


class SchwaerzenderFormatter(logging.Formatter):
    """Formatter, durch den JEDE Protokollzeile laeuft, bevor sie irgendwo
    landet. Die Schwaerzung sitzt hier und nicht an den Aufrufstellen, damit
    sie sich nicht vergessen laesst."""

    def __init__(self, config_lesen: Callable[[], dict]) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        self._config_lesen = config_lesen

    def format(self, record: logging.LogRecord) -> str:
        zeile = super().format(record)
        try:
            return schwaerze(zeile, self._config_lesen())
        except Exception:
            # Im Zweifel lieber gar nichts herausgeben als ungeschwaerzt.
            return "[Schwaerzung fehlgeschlagen - Zeile unterdrueckt]"


class RingHandler(logging.Handler):
    """Haelt die letzten Zeilen im Speicher. Laeuft immer mit."""

    def __init__(self, zeilen: int = RING_ZEILEN) -> None:
        super().__init__()
        self.puffer: deque[str] = deque(maxlen=zeilen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.puffer.append(self.format(record))
        except Exception:
            pass  # Protokollieren darf nie der Grund fuer einen Absturz sein

    def zeilen(self) -> list[str]:
        return list(self.puffer)


class KopfzeilenHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler, der jede Datei mit einer Kopfzeile beginnt.

    Warum das noetig ist: Ein Protokoll ohne Versionsnummer ist bei der
    Fehlersuche fast wertlos - man weiss nicht, gegen welchen Stand man liest.
    Genau das faellt auf, sobald FlowBridge bei anderen laeuft: Wer Hilfe
    sucht, kopiert die letzten Zeilen und schickt sie. Ohne Herkunft koennte
    das ein Fehler sein, den es seit drei Fassungen nicht mehr gibt.

    Und deshalb bei JEDEM Oeffnen, nicht nur beim Start:

    * Nach einer Umschaltung ist die neue Datei leer. Steht die Version nur in
      der ersten, tragen vier der fuenf Dateien sie nicht - und welche davon
      jemand erwischt, ist Zufall.
    * Nach einem Neustart kann die Version eine ANDERE sein. Das ist der
      Update-Fall, also gerade der, bei dem die Frage aufkommt. Eine Kopfzeile
      pro Start trennt die Abschnitte genau dort, wo sich etwas geaendert hat.

    Kosten: eine Zeile je Start und Umschaltung.

    Die Zeile geht bewusst am Formatter vorbei direkt in den Strom - sie ist
    keine Protokollzeile, sondern eine Beschriftung der Datei. Zu schwaerzen
    gibt es daran nichts, sie enthaelt nur Version und Zeitpunkt.
    """

    def __init__(self, *args, kopf: Callable[[], str], **kwargs) -> None:
        # VOR super().__init__: das oeffnet die Datei bereits und ruft damit
        # _open() auf, das den Kopf schon braucht.
        self._kopf = kopf
        super().__init__(*args, **kwargs)

    def _open(self):
        strom = super()._open()
        try:
            strom.write(self._kopf() + "\n")
            strom.flush()
        except Exception:
            pass  # Protokollieren darf nie der Grund fuer einen Absturz sein
        return strom


def _kopfzeile(version: str) -> str:
    """Beschriftung am Anfang jeder Protokolldatei.

    Mit '#' vorn, damit sie sich von den Protokollzeilen abhebt und beim
    Filtern leicht wegfaellt."""
    jetzt = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return f"# FlowBridge {version} – Protokoll beginnt {jetzt}"


class Diagnose:
    """Haelt Ring- und Datei-Protokoll zusammen."""

    def __init__(self, config_lesen: Callable[[], dict], log_pfad: Path) -> None:
        self._config_lesen = config_lesen
        self._log_pfad = log_pfad
        self._formatter = SchwaerzenderFormatter(config_lesen)
        self._ring = RingHandler()
        self._ring.setFormatter(self._formatter)
        self._datei: logging.handlers.RotatingFileHandler | None = None
        self.start = time.time()

    def einhaengen(self) -> None:
        wurzel = logging.getLogger()
        if self._ring not in wurzel.handlers:
            wurzel.addHandler(self._ring)

    # ------------------------------------------------------- Datei-Protokoll
    @property
    def aktiv(self) -> bool:
        return self._datei is not None

    def einschalten(self) -> None:
        if self._datei is not None:
            return
        self._log_pfad.parent.mkdir(parents=True, exist_ok=True)
        handler = KopfzeilenHandler(
            self._log_pfad, maxBytes=MAX_DATEI_BYTES, backupCount=MAX_DATEIEN - 1,
            encoding="utf-8",
            kopf=lambda: _kopfzeile(version.get_version()),
        )
        handler.setFormatter(self._formatter)
        handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(handler)
        # Erst hier auf DEBUG: im Normalbetrieb waere das nur Rauschen.
        logging.getLogger().setLevel(logging.DEBUG)
        # ... aber NICHT fuer die Fremdbibliotheken (siehe FREMDE_LOGGER).
        # WARNING statt AUS: Ein echter HTTP-Fehler soll weiterhin drinstehen.
        for name in FREMDE_LOGGER:
            logging.getLogger(name).setLevel(logging.WARNING)
        self._datei = handler
        logger.info("Datei-Protokoll eingeschaltet: %s", self._log_pfad)

    def ausschalten(self) -> None:
        if self._datei is None:
            return
        logger.info("Datei-Protokoll ausgeschaltet.")
        logging.getLogger().removeHandler(self._datei)
        self._datei.close()
        self._datei = None
        logging.getLogger().setLevel(logging.INFO)
        # Daempfung zuruecknehmen, sonst blieben die Fremd-Logger auch dann
        # stumm, wenn sie jemand ausserhalb der Diagnose braucht.
        for name in FREMDE_LOGGER:
            logging.getLogger(name).setLevel(logging.NOTSET)

    def groesse_bytes(self) -> int:
        gesamt = 0
        for pfad in self._dateien():
            try:
                gesamt += pfad.stat().st_size
            except OSError:
                pass
        return gesamt

    def _dateien(self) -> list[Path]:
        gefunden = [self._log_pfad] if self._log_pfad.exists() else []
        for i in range(1, MAX_DATEIEN):
            p = self._log_pfad.with_name(f"{self._log_pfad.name}.{i}")
            if p.exists():
                gefunden.append(p)
        return gefunden

    def loeschen(self) -> None:
        war_aktiv = self.aktiv
        self.ausschalten()
        for pfad in self._dateien():
            try:
                pfad.unlink()
            except OSError as exc:
                logger.warning("Protokolldatei nicht loeschbar (%s): %s", pfad, exc)
        if war_aktiv:
            self.einschalten()

    # --------------------------------------------------------------- Paket
    def _protokoll_text(self) -> str:
        teile: list[str] = []
        # Aeltere Staende zuerst, damit die Zeit vorwaerts laeuft.
        for pfad in reversed(self._dateien()):
            try:
                teile.append(f"----- {pfad.name} -----")
                teile.append(
                    schwaerze(pfad.read_text(encoding="utf-8", errors="replace"),
                              self._config_lesen())
                )
            except OSError as exc:
                teile.append(f"[{pfad.name} nicht lesbar: {exc}]")
        teile.append("----- letzte Zeilen (Ringpuffer) -----")
        teile.extend(self._ring.zeilen())
        return "\n".join(teile)

    def paket(self, bericht: str, config_maskiert: str, topics: str) -> bytes:
        """ZIP mit Bericht, maskierter Konfiguration, Topics und Protokoll.

        HIER laeuft alles zusammen, was die Datei verlaesst - aus demselben
        Grund, aus dem die Schwaerzung im Formatter sitzt und nicht an den
        Aufrufstellen: Wer spaeter einen fuenften Bestandteil hinzufuegt, kann
        ihn nicht ungeschwaerzt hineinlegen.

        Vorher galt das nur fuers Protokoll. Bericht, Konfiguration und
        Topic-Liste gingen ungefiltert hinein und trugen die Seriennummer im
        Klartext - in der Topic-Liste sogar in jeder Zeile. Aufgefallen am
        16.08.2026 beim Einbau der Platzhalter.
        """
        config = self._config_lesen()
        puffer = io.BytesIO()
        with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("bericht.txt", schwaerze(bericht, config))
            z.writestr("konfiguration-maskiert.yaml", schwaerze(config_maskiert, config))
            z.writestr("mqtt-topics.txt", schwaerze(topics, config))
            # Nur umbenennen, nicht noch einmal schwaerzen: Die Zeilen sind
            # bereits durch den Formatter gelaufen, ein zweiter Durchgang
            # traefe die schon ersetzten Stellen erneut. Das Umbenennen ist
            # idempotent und holt die Dateien mit, die vor dieser Aenderung
            # geschrieben wurden.
            z.writestr("protokoll.txt", benenne_um(self._protokoll_text(), config))
            # Ohne diese Zuordnung waere das Paket zwar sauber, aber auch
            # stumm: Welches Modell hinter <GERAET-2> steckt, ist genau die
            # Frage, die man beim Lesen zuerst hat.
            z.writestr("geraete-zuordnung.txt", self._zuordnung_text(config))
        return puffer.getvalue()

    @staticmethod
    def _zuordnung_text(config: dict) -> str:
        """Platzhalter -> Modell. Bewusst OHNE Seriennummer."""
        geraete = (config.get("ecoflow") or {}).get("devices") or []
        zeilen = [
            "Zuordnung der Platzhalter",
            "",
            "Die Seriennummern stehen absichtlich nicht dabei - fuer die",
            "Auswertung genuegt das Modell, und die Zuordnung zum eigenen",
            "Geraet kennt nur, wer das Paket verschickt hat.",
            "",
        ]
        for nummer, geraet in enumerate(geraete, start=1):
            zeilen.append(f"  <GERAET-{nummer}>  {(geraet or {}).get('model') or 'unbekannt'}")
        if not geraete:
            zeilen.append("  (keine konfiguriert)")
        return "\n".join(zeilen) + "\n"

    def ring_zeilen(self) -> list[str]:
        return self._ring.zeilen()

    def laufzeit_sekunden(self) -> float:
        return time.time() - self.start


def baue_bericht(
    version: str,
    update_status: str,
    health: dict,
    geraete: list[dict],
    laufzeit_s: float,
    datei_protokoll: bool,
) -> str:
    """Der Text, den man als Erstes aufmacht."""
    zeilen = [
        "FlowBridge – Diagnosebericht",
        f"Erstellt:        {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Version:         {version}",
        f"Update-Zustand:  {update_status}",
        f"Laufzeit:        {int(laufzeit_s // 3600)} h {int(laufzeit_s % 3600 // 60)} min",
        f"Python:          {sys.version.split()[0]} auf {platform.platform()}",
        f"Datei-Protokoll: {'ein' if datei_protokoll else 'aus'}",
        "",
        "Verbindungen",
        f"  EcoFlow-Broker: {health.get('ecoflow_broker')}",
        f"  Lokaler Broker: {health.get('local_broker')}",
        f"  Geraete:        {health.get('devices')}",
        "",
        "Geraete",
    ]
    if not geraete:
        zeilen.append("  (keine konfiguriert)")
    for g in geraete:
        konfiguriert = g.get("model") or "unbekannt"
        gemeldet = g.get("product_name")
        zeilen += [
            f"  {g.get('sn')}",
            f"    Modell konfiguriert: {konfiguriert}",
            f"    Modell laut EcoFlow: {gemeldet or 'nicht abrufbar'}",
        ]
        # Der interessanteste Fall ueberhaupt: konfiguriert steht etwas
        # anderes als das, was EcoFlow meldet. Dann greifen die Befehle des
        # falschen Modells, und das Geraet verwirft sie stillschweigend -
        # ohne diesen Hinweis sucht man den Fehler ueberall sonst.
        if gemeldet and konfiguriert.strip().lower() != gemeldet.strip().lower():
            zeilen.append("    >>> ACHTUNG: Modelle stimmen nicht ueberein <<<")
        zeilen += [
            f"    Unterstuetzung:      {g.get('support_level')} "
            f"(steuerbar: {'ja' if g.get('controllable') else 'nein'})",
            f"    Ladestufen:          {g.get('charge_steps') or '-'}",
            f"    online:              {g.get('online')}",
            f"    gelesene Felder:     {g.get('felder')}",
            f"    letzter Fehler:      {g.get('error') or '-'}",
        ]
    return "\n".join(zeilen) + "\n"

"""
Feldinventar: Was liefert EcoFlow ueber die Zeit wirklich?

Anlass (13.08.2026): Der Abgleich eines alten Payload-Satzes gegen die heutige
Schnittstelle zeigte, dass von 168 Feldern noch 27 ankommen. Solche
Verschiebungen passieren still - EcoFlow spielt Firmware aus, und der
Datenstrom wird breiter oder schmaler, ohne dass jemand es merkt.

Der Kniff: Dafuer braucht es NICHT den Datenstrom, sondern ein Inventar.
Ein Mitschnitt waechst linear und ist nach Stunden unhandlich; interessant
ist je Feld nur, wann es zuerst und zuletzt gesehen wurde, wie oft es kommt
und in welchem Wertebereich. Das sind wenige Kilobyte - dauerhaft. Die Datei
waechst nur, wenn ein NEUES Feld auftaucht.

Genau daran wird eine Aenderung sichtbar:
  * neues Feld  -> "zuerst" traegt das heutige Datum
  * weggefallen -> "zuletzt" bleibt stehen und altert

Bewusst NICHT hier: Schwaerzung. Ein Inventar enthaelt Feldnamen und
Messwerte, keine Zugangsdaten - anders als das Diagnose-Protokoll, das auch
Signaturen und Schluessel zu sehen bekommt.

In der Datei auf der Platte steht die Seriennummer deshalb im Klartext; sie
ist der Schluessel, unter dem hier zugeordnet wird. Ersetzt wird sie erst
beim HERUNTERLADEN: `als_json()` verlangt die Platzhalter-Zuordnung als
Pflichtparameter, damit niemand versehentlich die Rohfassung ausliefert.
Wer sich feldinventar.json direkt aus dem Datenordner kopiert, hat die
Nummer weiterhin darin - was in Ordnung ist, denn das ist die eigene Platte.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import version

logger = logging.getLogger(__name__)

# Format der Datei. Aendert sich die Struktur, laesst sich daran ein alter
# Stand erkennen, statt ihn falsch zu deuten.
FORMAT_VERSION = 1

# Je Feld ein paar unterschiedliche Werte aufheben. Fuenf genuegen, um zu
# sehen, ob ein Feld ein Schalter (0/1), ein Zaehler oder ein Messwert ist.
MAX_BEISPIELE = 5

# Ereignisliste begrenzen, damit die Datei nicht doch unbemerkt waechst.
MAX_EREIGNISSE = 500

# Rohnachricht beim ERSTEN Auftreten eines Feldes mitschreiben - das passiert
# selten und erspart spaeter das Raten, in welchem Zusammenhang es kam.
MAX_ROHNACHRICHT = 600

# Nicht bei jeder Nachricht schreiben: Der Push kommt im Sekundentakt, das
# waere sinnlose Schreiblast auf der NAS. Neue Felder werden trotzdem sofort
# gesichert - das ist der Moment, den man nicht verlieren will.
SPEICHER_ABSTAND_S = 60


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Feldinventar:
    """Zaehlt mit, welche Felder je Geraet auftauchen - und seit wann."""

    def __init__(self, pfad: Path) -> None:
        self._pfad = pfad
        self._sperre = threading.Lock()
        self._aktiv = False
        self._zuletzt_gespeichert = 0.0
        self._daten: dict[str, Any] = self._laden()

    # ------------------------------------------------------------- Zustand
    @property
    def aktiv(self) -> bool:
        return self._aktiv

    def einschalten(self) -> None:
        with self._sperre:
            if self._aktiv:
                return
            self._aktiv = True
            self._daten.setdefault("gestartet", _jetzt())
            self._daten["zuletzt_aktiviert"] = _jetzt()
        self._speichern()
        logger.info("Feldinventar eingeschaltet: %s", self._pfad)

    def ausschalten(self) -> None:
        with self._sperre:
            self._aktiv = False
        self._speichern()
        logger.info("Feldinventar ausgeschaltet.")

    # ------------------------------------------------------------ Erfassen
    def beobachte(
        self, sn: str, felder: dict[str, Any], quelle: str, rohnachricht: str | None = None
    ) -> None:
        """Eine Lieferung verbuchen.

        `quelle` ist "push" oder "rest". Die Unterscheidung ist nicht
        kosmetisch: Der Push liefert nachweislich mehr Felder als quota/all
        (29 gegen 20, gemessen am 13.08.2026). Faellt eines kuenftig nur in
        einem der beiden Kanaele weg, waere das ohne diese Angabe unsichtbar.

        Wird auch aus dem paho-Netzwerk-Thread gerufen - daher die Sperre.
        """
        if not self._aktiv or not felder:
            return

        zeit = _jetzt()
        neu_entdeckt: list[str] = []

        with self._sperre:
            geraet = self._daten.setdefault("geraete", {}).setdefault(
                sn, {"felder": {}, "ereignisse": []}
            )
            bekannt = geraet["felder"]

            for name, wert in felder.items():
                eintrag = bekannt.get(name)
                if eintrag is None:
                    eintrag = {
                        "zuerst": zeit,
                        "zuletzt": zeit,
                        "anzahl": 0,
                        "quellen": [],
                        "beispiele": [],
                    }
                    bekannt[name] = eintrag
                    neu_entdeckt.append(name)

                eintrag["zuletzt"] = zeit
                eintrag["anzahl"] += 1
                if quelle not in eintrag["quellen"]:
                    eintrag["quellen"].append(quelle)
                self._wert_verbuchen(eintrag, wert)

            if neu_entdeckt:
                ereignis: dict[str, Any] = {
                    "zeit": zeit,
                    "was": "neu",
                    "quelle": quelle,
                    "felder": neu_entdeckt,
                }
                if rohnachricht:
                    ereignis["rohnachricht"] = rohnachricht[:MAX_ROHNACHRICHT]
                geraet["ereignisse"].append(ereignis)
                del geraet["ereignisse"][:-MAX_EREIGNISSE]

        # Neue Felder sofort sichern - genau die will man nicht verlieren,
        # wenn der Container gleich darauf neu startet.
        if neu_entdeckt:
            logger.info("Feldinventar: %s neue Felder bei %s (%s)", len(neu_entdeckt), sn, quelle)
            self._speichern()
        elif time.monotonic() - self._zuletzt_gespeichert > SPEICHER_ABSTAND_S:
            self._speichern()

    @staticmethod
    def _wert_verbuchen(eintrag: dict[str, Any], wert: Any) -> None:
        """Zahlen als Spanne fuehren, alles andere als Beispielmenge.

        Bei einer Zahl sagt min/max mehr als eine Liste von Stichproben - bei
        einem Text ist es genau umgekehrt.
        """
        if isinstance(wert, bool) or not isinstance(wert, (int, float)):
            beispiele = eintrag.setdefault("beispiele", [])
            kurz = str(wert)[:60]
            if kurz not in beispiele and len(beispiele) < MAX_BEISPIELE:
                beispiele.append(kurz)
            return
        eintrag["min"] = wert if "min" not in eintrag else min(eintrag["min"], wert)
        eintrag["max"] = wert if "max" not in eintrag else max(eintrag["max"], wert)

    # -------------------------------------------------------------- Ablage
    def _laden(self) -> dict[str, Any]:
        if not self._pfad.exists():
            return {"version": FORMAT_VERSION, "geraete": {}}
        try:
            daten = json.loads(self._pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # Eine kaputte Datei darf den Start nicht verhindern - das
            # Inventar ist Beiwerk, nicht Betriebsgrundlage.
            logger.warning("Feldinventar unlesbar, beginne neu: %s", exc)
            return {"version": FORMAT_VERSION, "geraete": {}}
        daten.setdefault("version", FORMAT_VERSION)
        daten.setdefault("geraete", {})
        return daten

    def _speichern(self) -> None:
        with self._sperre:
            # Bei JEDEM Schreiben neu setzen, nicht einmal beim Anlegen: Die
            # Datei ueberlebt Updates - sie liegt neben der config.yaml, nicht
            # im Abbild. Einmalig gesetzt behauptete sie sonst noch in einem
            # Jahr die Fassung, unter der sie angelegt wurde.
            #
            # Getrennt von "version": Das ist die FORMAT-Version der Datei
            # (FORMAT_VERSION, steht seit jeher auf 1). Wer das Inventar
            # aufmacht, um herauszufinden, welcher Stand die Daten erhoben
            # hat, findet dort sonst eine Zahl, die wie eine Antwort aussieht
            # und keine ist - gerade wenn die Datei per Mail hereinkommt.
            self._daten["flowbridge_version"] = version.get_version()
            inhalt = json.dumps(self._daten, indent=2, ensure_ascii=False, sort_keys=True)
        try:
            self._pfad.parent.mkdir(parents=True, exist_ok=True)
            self._pfad.write_text(inhalt, encoding="utf-8")
            self._zuletzt_gespeichert = time.monotonic()
        except OSError as exc:
            logger.warning("Feldinventar nicht speicherbar: %s", exc)

    # -------------------------------------------------------------- Ausgabe
    def zustand(self) -> dict[str, Any]:
        """Kurzfassung fuer die Oberflaeche."""
        with self._sperre:
            geraete = self._daten.get("geraete", {})
            felder = sum(len(g.get("felder", {})) for g in geraete.values())
            ereignisse = sum(len(g.get("ereignisse", [])) for g in geraete.values())
            gestartet = self._daten.get("gestartet")
        return {
            "enabled": self._aktiv,
            "started": gestartet,
            "devices": len(geraete),
            "fields": felder,
            "events": ereignisse,
            "size_bytes": self._pfad.stat().st_size if self._pfad.exists() else 0,
        }

    def als_json(
        self, platzhalter: dict[str, str], modelle: dict[str, str] | None = None
    ) -> bytes:
        """Das Inventar als JSON - mit Platzhaltern statt Seriennummern.

        `platzhalter` ist PFLICHT und hat keinen Vorgabewert. Genau daran ist
        es beim ersten Mal gescheitert: Der Download-Endpunkt reichte die
        Daten unveraendert durch, mit der Seriennummer als Schluessel unter
        "geraete", und in seinem Docstring stand die Begruendung, ohne sie
        liesse sich nichts zuordnen. Dieselbe Verwechslung von
        identifizierbar und unterscheidbar wie in diagnostics.py - ich hatte
        sie dort korrigiert und nicht gesucht, wo sie sonst noch steht.

        Ein leeres Dict ist erlaubt und heisst "unveraendert" - aber es ist
        dann eine Entscheidung, kein Versehen. Die Tests nutzen es, um die
        Buchhaltung unter der echten Seriennummer zu pruefen.

        `modelle` (Platzhalter -> Modell) landet als "geraete_zuordnung" in
        der Datei. Ohne sie waere das Ergebnis zwar sauber, aber stumm: Bei
        einem eingeschickten Inventar ist "welches Modell ist <GERAET-2>?"
        die erste Frage.
        """
        with self._sperre:
            daten = dict(self._daten)
            if platzhalter:
                daten["geraete"] = {
                    platzhalter.get(sn, sn): eintrag
                    for sn, eintrag in (daten.get("geraete") or {}).items()
                }
            if modelle:
                daten["geraete_zuordnung"] = dict(modelle)
            return json.dumps(
                daten, indent=2, ensure_ascii=False, sort_keys=True
            ).encode("utf-8")

    def zuruecksetzen(self) -> None:
        with self._sperre:
            self._daten = {"version": FORMAT_VERSION, "geraete": {}}
            if self._aktiv:
                self._daten["gestartet"] = _jetzt()
        self._speichern()
        logger.info("Feldinventar zurueckgesetzt.")

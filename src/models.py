"""
Welches Geraet welche Steuerbefehle bekommt - und wie belastbar die sind.

Wichtig, weil EcoFlow einen Befehl auch dann mit "Success" quittiert, wenn das
Geraet ihn stillschweigend verwirft (mehrfach beobachtet, u.a. bei lcdCfg und
bei acOutCfg mit Teil-Parametern). Eine erfolgreiche Antwort beweist also
nichts - nur eine messbare Wirkung am Geraet tut das.

Deshalb drei Reifegrade statt eines Ja/Nein:

  SUPPORT_VERIFIED   Befehle am echten Geraet gegengemessen. Bedienung normal.
  SUPPORT_DOCUMENTED Befehle aus der offiziellen Portal-Doku uebernommen, aber
                     mangels Hardware nicht nachgeprueft. Bedienung nutzbar,
                     im UI aber als ungeprueft gekennzeichnet.
  SUPPORT_NONE       Nichts bekannt. Nur Ueberwachung - Messwerte, Modul-Tabs
                     und Verlauf laufen modellunabhaengig.
"""
from __future__ import annotations

import commands_delta2
import commands_river2

SUPPORT_VERIFIED = "verified"
SUPPORT_DOCUMENTED = "documented"
SUPPORT_NONE = "none"

# Modell-Kennung (Teilstring aus productName, kleingeschrieben) -> Modul + Reifegrad.
# Teilstring-Vergleich, weil EcoFlow "RIVER 2 Pro" liefert, andere Quellen
# "River 2 Pro" schreiben. Reihenfolge zaehlt: spezifischere Kennungen zuerst.
_MODELLE: tuple[tuple[str, object, str], ...] = (
    ("river 2", commands_river2, SUPPORT_VERIFIED),
    ("delta 2", commands_delta2, SUPPORT_DOCUMENTED),
)


def _eintrag(model: str | None):
    if not model:
        return None
    klein = model.lower()
    for kennung, modul, grad in _MODELLE:
        if kennung in klein:
            return modul, grad
    return None


def command_module(model: str | None):
    """Passendes Kommando-Modul oder None, wenn nichts bekannt ist."""
    eintrag = _eintrag(model)
    return eintrag[0] if eintrag else None


def support_level(model: str | None) -> str:
    eintrag = _eintrag(model)
    return eintrag[1] if eintrag else SUPPORT_NONE


def is_controllable(model: str | None) -> bool:
    return command_module(model) is not None


def nur_lesbar(model: str | None) -> tuple[str, ...]:
    """Felder, die dieses Modell meldet, aber nicht annimmt.

    Nicht dasselbe wie "nicht steuerbar": Das Geraet ist steuerbar, nur
    dieses eine Feld nicht. Die Liste steht im jeweiligen Kommando-Modul,
    weil sie am Geraet gemessen wurde - und nicht jedes Modell dieselben
    Luecken hat. Beim Delta 2 ist watthConfig mangels Hardware weder
    bestaetigt noch widerlegt; dort bleibt es vorerst bedienbar.
    """
    modul = command_module(model)
    if modul is None:
        return ()
    return tuple(getattr(modul, "NUR_LESBAR", ()))


def charge_watts_steps(model: str | None) -> list[int]:
    """Erlaubte Ladeleistungs-Stufen des Modells (leer = nicht steuerbar).

    Bewusst modellabhaengig: das River 2 Pro geht bis 870 W, eine Delta 2
    laedt deutlich hoeher - ein fest verdrahteter Regler waere dort falsch.
    """
    modul = command_module(model)
    if modul is None:
        return []
    return list(getattr(modul, "CHARGE_WATTS_STEPS", ()))

"""Tests fuer die Modell-Weiche (models.py).

Wichtig, weil EcoFlow einen Befehl auch dann mit "Success" quittiert, wenn das
Geraet ihn stillschweigend verwirft. Ein Delta 2 mit River-2-Befehlen zu
bedienen saehe im UI also erfolgreich aus, ohne es zu sein - deshalb wird nur
freigegeben, was am echten Geraet verifiziert wurde.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import commands_river2  # noqa: E402
import models  # noqa: E402


@pytest.mark.parametrize(
    "produktname",
    ["RIVER 2 Pro", "River 2 Pro", "RIVER 2 Max", "river 2"],
)
def test_river2_varianten_werden_erkannt(produktname):
    """EcoFlow schreibt 'RIVER 2 Pro', andere Quellen 'River 2 Pro'."""
    assert models.command_module(produktname) is commands_river2
    assert models.is_controllable(produktname)


@pytest.mark.parametrize("produktname", ["Delta Pro 3", "Glacier", "PowerStream", "DELTA 3 MAX"])
def test_unbekannte_modelle_sind_nicht_steuerbar(produktname):
    assert models.command_module(produktname) is None
    assert not models.is_controllable(produktname)
    assert models.charge_watts_steps(produktname) == []
    assert models.support_level(produktname) == models.SUPPORT_NONE


def test_delta2_ist_steuerbar_aber_nur_nach_doku():
    """Steuerbar ja - aber der Reifegrad muss vom River 2 unterscheidbar
    bleiben, damit das UI es kennzeichnen kann."""
    assert models.is_controllable("DELTA 2")
    assert models.support_level("DELTA 2") == models.SUPPORT_DOCUMENTED
    assert models.support_level("RIVER 2 Pro") == models.SUPPORT_VERIFIED


@pytest.mark.parametrize("wert", [None, ""])
def test_fehlendes_modell_ist_nicht_steuerbar(wert):
    """Altbestand ohne gespeichertes Modell darf keine Befehle bekommen."""
    assert not models.is_controllable(wert)


def test_river2_liefert_seine_ladestufen():
    stufen = models.charge_watts_steps("RIVER 2 Pro")
    assert stufen[0] == 100
    assert stufen[-1] == 870

"""Tests fuer die DELTA-2-Befehle.

Diese Befehle stammen aus der offiziellen Doku, sind aber NICHT an Hardware
verifiziert (Reifegrad "documented", siehe models.py). Die Tests pruefen
deshalb nur, dass FlowBridge genau das sendet, was die Doku beschreibt - ob
das Geraet es befolgt, kann erst jemand mit einer echten Delta 2 sagen.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import commands_delta2 as d2  # noqa: E402
import commands_river2 as r2  # noqa: E402
import models  # noqa: E402


class FakeClient:
    def __init__(self):
        self.aufruf = None

    async def set_quota(self, sn, module_type, operate_type, params):
        self.aufruf = {"moduleType": module_type, "operateType": operate_type, "params": params}
        return {}


def _sende(property_name, value, current=None):
    c = FakeClient()
    asyncio.run(d2.apply_command(c, "SN-D2", property_name, value, current or {}))
    return c.aufruf


def test_ladeleistung_wie_in_der_doku():
    a = _sende("charge_power_watts", "800")
    assert a["moduleType"] == 5
    assert a["operateType"] == "acChgCfg"
    assert a["params"] == {"chgWatts": 800, "chgPauseFlag": 0}


def test_delta2_reicht_hoeher_als_das_river_2_pro():
    """1200 W waere am River 2 Pro ungueltig - hier muss es durchgehen."""
    assert 1200 in d2.CHARGE_WATTS_STEPS
    assert 1200 not in r2.CHARGE_WATTS_STEPS
    a = _sende("charge_power_watts", "1200")
    assert a["params"]["chgWatts"] == 1200


def test_river2_hoechstwert_passt_nicht_ins_delta2_raster():
    """870 ist River-2-spezifisch; hier gilt das 100er-Raster."""
    assert 870 not in d2.CHARGE_WATTS_STEPS
    with pytest.raises(r2.CommandError):
        _sende("charge_power_watts", "870")


def test_pause_behaelt_die_leistung():
    a = _sende("ac_charging_enabled", "off", {"charge_power_watts": 600})
    assert a["params"] == {"chgWatts": 600, "chgPauseFlag": 1}


def test_ladeleistung_hebt_laufende_pause_nicht_auf():
    a = _sende("charge_power_watts", "400", {"ac_charging_enabled_set": False})
    assert a["params"]["chgPauseFlag"] == 1


def test_ac_ausgang_sendet_alle_vier_felder():
    a = _sende("xboost_enabled", "on",
               {"ac_output_enabled": 1, "ac_output_voltage": 230, "ac_output_freq_hz": 50})
    assert a["operateType"] == "acOutCfg"
    assert a["params"] == {"enabled": 1, "xboost": 1, "out_voltage": 230, "out_freq": 1}


def test_delta2_eigene_befehle():
    """dcOutCfg und quietMode kennt das River 2 Pro nicht."""
    assert _sende("dc_output_enabled", "on") == {
        "moduleType": 1, "operateType": "dcOutCfg", "params": {"enabled": 1}}
    assert _sende("quiet_mode", "on") == {
        "moduleType": 5, "operateType": "quietMode", "params": {"enabled": 1}}


def test_unbekanntes_property_wird_abgelehnt():
    with pytest.raises(r2.CommandError):
        _sende("gibtsnicht", "on")


def test_modellweiche_trennt_die_beiden_sauber():
    assert models.command_module("DELTA 2") is d2
    assert models.command_module("DELTA 2 Max") is d2
    assert models.command_module("RIVER 2 Pro") is r2


def test_reifegrade_sind_unterschiedlich():
    """Der Unterschied muss sichtbar bleiben - "dokumentiert" ist nicht "geprueft"."""
    assert models.support_level("RIVER 2 Pro") == models.SUPPORT_VERIFIED
    assert models.support_level("DELTA 2") == models.SUPPORT_DOCUMENTED
    assert models.support_level("Glacier") == models.SUPPORT_NONE

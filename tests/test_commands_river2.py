"""Tests fuer die acChgCfg-Befehle (Ladeleistung + Pause).

Kernpunkt: acChgCfg braucht IMMER beide Parameter (chgWatts und chgPauseFlag)
- ein Teil-Update wird vom Geraet stillschweigend ignoriert, waehrend die Cloud
trotzdem "Success" meldet. Daraus folgt die Falle, die diese Tests absichern:
wer nur die Leistung aendert, darf eine laufende Pause nicht unbemerkt
aufheben, und wer pausiert, darf die eingestellte Leistung nicht verlieren.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import commands_river2 as cmd  # noqa: E402


class FakeClient:
    """Merkt sich den letzten set_quota-Aufruf, statt zu senden."""

    def __init__(self):
        self.aufruf = None

    async def set_quota(self, sn, module_type, operate_type, params):
        self.aufruf = {"sn": sn, "moduleType": module_type, "operateType": operate_type,
                       "params": params}
        return {}


def _sende(property_name, value, current=None):
    client = FakeClient()
    asyncio.run(cmd.apply_command(client, "SN1", property_name, value, current or {}))
    return client.aufruf


def test_ladeleistung_sendet_beide_parameter():
    a = _sende("charge_power_watts", "300")
    assert a["operateType"] == "acChgCfg"
    assert a["moduleType"] == cmd.MODULE_MPPT
    assert a["params"] == {"chgWatts": 300, "chgPauseFlag": 0}


def test_ladeleistung_hebt_laufende_pause_NICHT_auf():
    """Sonst würde ein Verstellen der Leistung die Ladung ungewollt anwerfen."""
    a = _sende("charge_power_watts", "300", {"ac_charging_enabled_set": False})
    assert a["params"] == {"chgWatts": 300, "chgPauseFlag": 1}


def test_unbekannter_pausenzustand_bedeutet_laden():
    """Nach einem Neustart ist nichts bekannt - dann darf nicht pausiert werden."""
    a = _sende("charge_power_watts", "300", {"ac_charging_enabled_set": None})
    assert a["params"]["chgPauseFlag"] == 0


def test_pause_behaelt_die_eingestellte_leistung():
    a = _sende("ac_charging_enabled", "off", {"charge_power_watts_set": 450})
    assert a["params"] == {"chgWatts": 450, "chgPauseFlag": 1}


def test_laden_an_behaelt_die_eingestellte_leistung():
    a = _sende("ac_charging_enabled", "on", {"charge_power_watts_set": 450})
    assert a["params"] == {"chgWatts": 450, "chgPauseFlag": 0}


def test_pause_ohne_bekannte_leistung_nutzt_das_minimum():
    """Nicht unbemerkt hochregeln, wenn die Leistung (noch) unbekannt ist."""
    a = _sende("ac_charging_enabled", "off", {})
    assert a["params"]["chgWatts"] == cmd.CHARGE_WATTS_MIN


@pytest.mark.parametrize("wert", ["90", "900", "175", "860", "keinezahl"])
def test_ungueltige_ladeleistung_wird_abgelehnt(wert):
    with pytest.raises(cmd.CommandError):
        _sende("charge_power_watts", wert)


def test_hoechstwert_870_ist_erlaubt():
    """870 liegt NICHT im 50er-Raster ab 100 - eine Modulo-Prüfung hätte den
    Höchstwert fälschlich abgelehnt, er wäre also gar nicht setzbar gewesen."""
    a = _sende("charge_power_watts", "870")
    assert a["params"]["chgWatts"] == 870


def test_rasterstufen_beginnen_und_enden_richtig():
    assert cmd.CHARGE_WATTS_STEPS[0] == 100
    assert cmd.CHARGE_WATTS_STEPS[-1] == 870
    assert 850 in cmd.CHARGE_WATTS_STEPS
    assert 860 not in cmd.CHARGE_WATTS_STEPS


def test_ungueltiger_schaltwert_wird_abgelehnt():
    with pytest.raises(cmd.CommandError):
        _sende("ac_charging_enabled", "vielleicht")


# Vollstaendiger AC-Stand, wie ihn normalize_quota liefert. Alle vier Felder
# muessen dastehen - unvollstaendig ist seit 16.08.2026 ein Fehler, nicht mehr
# ein Fall fuer Vorgabewerte (s. unten).
AC_STAND = {
    "ac_output_enabled": 1,
    "xboost_enabled": 0,
    "ac_output_voltage": 230,
    "ac_output_freq_hz": 50,
}


def test_ac_ausgang_sendet_alle_vier_felder():
    """acOutCfg wirkt nur vollständig - Teil-Updates ignoriert das Gerät."""
    a = _sende("xboost_enabled", "on", AC_STAND)
    assert a["params"] == {"enabled": 1, "xboost": 1, "out_voltage": 230, "out_freq": 1}


def test_ac_frequenz_wird_beim_schreiben_zum_enum():
    """Lesen liefert Hertz (50/60), Schreiben erwartet 1/2."""
    a = _sende("xboost_enabled", "on", {**AC_STAND, "ac_output_freq_hz": 60})
    assert a["params"]["out_freq"] == 2


@pytest.mark.parametrize("fehlt", sorted(AC_STAND))
def test_unvollstaendiger_ac_stand_wird_abgelehnt(fehlt):
    """Am 16.08.2026 im Feld aufgeschlagen: Dirk hatte den Container neu
    erstellt und den AC-Ausgang eingeschaltet, bevor der erste Push da war.

    Damals standen in _ac_out_cfg Rückfallwerte. Der Stand war leer, also ging
    `xboost: 0` mit hinaus - **X-Boost wurde stillschweigend ausgeschaltet**,
    obwohl niemand danach gefragt hatte. Ebenso wären 230 V / 50 Hz gesetzt
    worden. EcoFlow quittierte mit Erfolg.

    Ein Befehl darf nur das ändern, wonach gefragt wurde. Fehlt auch nur eines
    der vier Felder, ist Abbrechen mit lesbarer Meldung die einzige ehrliche
    Antwort - raten heißt hier, drei fremde Einstellungen zu überschreiben."""
    unvollstaendig = {k: v for k, v in AC_STAND.items() if k != fehlt}
    with pytest.raises(cmd.CommandError) as fehler:
        _sende("xboost_enabled", "on", unvollstaendig)
    assert fehlt in str(fehler.value)


def test_leerer_stand_verstellt_nicht_stillschweigend():
    """Der Fall aus dem Feld in Reinform: gar kein Stand bekannt."""
    with pytest.raises(cmd.CommandError):
        _sende("ac_output_enabled", "on", {})


@pytest.mark.parametrize("wert,erwartet", [
    ("on", 1), ("off", 0),
    ("true", 1), ("false", 0),
    ("True", 1), ("False", 0),
    ("1", 1), ("0", 0),
    ("an", 1), ("aus", 0),
    ("  ON  ", 1),
])
def test_schaltwerte_werden_grosszuegig_gelesen(wert, erwartet):
    """Ein abgelehnter Schaltbefehl sieht auf dem MQTT-Weg wie "tut nichts"
    aus - dort gibt es keinen Rueckkanal fuer Fehlermeldungen. Deshalb werden
    die naheliegenden Schreibweisen alle akzeptiert."""
    from commands_river2 import _parse_bool
    assert _parse_bool(wert) == erwartet


def test_unsinniger_schaltwert_wird_weiterhin_abgelehnt():
    from commands_river2 import CommandError, _parse_bool
    with pytest.raises(CommandError):
        _parse_bool("vielleicht")


# ------------------------------------------- Backup-Reserve (14.08.2026)
class TestBackupReserve:
    """Beim River 2 Pro nur LESBAR - am Geraet gemessen (14.08.2026).

    Der Werdegang gehoert hierher, weil er zwei Irrtuemer festhaelt:

    1. Zuerst schickte FlowBridge beim Setzen des Werts fest `isConfig: 1`
       mit, schaltete die Reserve also ungefragt ein. Das sah nach einem
       Fehler in der Parameterbildung aus - und wurde als solcher behoben.
    2. Erst danach zeigte die Messung, dass `watthConfig` ueberhaupt nicht
       angenommen wird: drei Laeufe, eine Viertelstunde, moduleType 1 und 5,
       mit und ohne vollstaendigen Param-Satz. EcoFlow quittiert jedes Mal
       ohne Fehler, `pd.watchIsConfig` bleibt stehen, und in der EcoFlow-App
       bewegt sich nichts.

    Der Lesepfad ist einwandfrei - Umschalten IN der App kommt sofort an.
    Deshalb: anzeigen, nicht anbieten.
    """

    def test_beide_felder_gelten_als_nur_lesbar(self):
        assert set(cmd.NUR_LESBAR) == {
            "backup_reserve_enabled",
            "backup_reserve_percent",
        }

    @pytest.mark.parametrize(
        ("property_name", "wert"),
        [
            ("backup_reserve_enabled", "off"),
            ("backup_reserve_enabled", "on"),
            ("backup_reserve_percent", "40"),
        ],
    )
    def test_setzen_wird_abgelehnt(self, property_name, wert):
        """Ausdruecklich mit Fehler, nicht still.

        Ueber MQTT (EisBaer, Home Assistant) wartet niemand auf eine
        Antwort - ohne diese Ausnahme verschwaende der Befehl spurlos, und
        man suchte den Fehler bei sich. Genau das ist passiert.
        """
        with pytest.raises(cmd.CommandError) as fehler:
            _sende(property_name, wert, {"backup_reserve_enabled": 1,
                                         "backup_reserve_percent": 86})
        assert "watthConfig" in str(fehler.value)

    def test_es_geht_gar_kein_aufruf_mehr_raus(self):
        """Gegenprobe zum Fehler: Es darf auch kein set_quota entstehen."""
        client = FakeClient()
        for property_name in cmd.NUR_LESBAR:
            with pytest.raises(cmd.CommandError):
                asyncio.run(cmd.apply_command(client, "SN1", property_name, "50", {}))
        assert client.aufruf is None

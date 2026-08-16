"""Tests fuer die gemerkten Sollwerte (AC-Ladeleistung und Lade-Pause).

EcoFlow liefert diese beiden Werte nicht zurueck. FlowBridge merkt sich
deshalb, was es zuletzt gesetzt hat - und seit 12.08.2026 ueberlebt das auch
einen Neustart, weil es in der config.yaml landet.
"""
import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config as cfg  # noqa: E402

SN = "TEST-SN-0001"


@pytest.fixture(autouse=True)
def eigene_configdatei(tmp_path, monkeypatch):
    """Nie die echte config.yaml anfassen."""
    ziel = tmp_path / "config.yaml"
    monkeypatch.setattr(cfg, "_config_path", lambda: ziel)
    return ziel


def test_sollwert_wird_geschrieben_und_gelesen():
    cfg.write_setpoint(SN, "charge_power_watts", 350)
    assert cfg.read_setpoints()[SN]["charge_power_watts"] == 350


def test_zweiter_sollwert_ueberschreibt_den_ersten_nicht():
    cfg.write_setpoint(SN, "charge_power_watts", 350)
    cfg.write_setpoint(SN, "ac_charging_enabled", False)

    werte = cfg.read_setpoints()[SN]
    assert werte == {"charge_power_watts": 350, "ac_charging_enabled": False}


def test_mehrere_geraete_stoeren_sich_nicht():
    cfg.write_setpoint("SN-A", "charge_power_watts", 100)
    cfg.write_setpoint("SN-B", "charge_power_watts", 870)

    werte = cfg.read_setpoints()
    assert werte["SN-A"]["charge_power_watts"] == 100
    assert werte["SN-B"]["charge_power_watts"] == 870


def test_ohne_datei_leeres_ergebnis_statt_fehler():
    assert cfg.read_setpoints() == {}


def test_sollwerte_ueberleben_das_speichern_der_einstellungen():
    """Regression: das Setup-UI schreibt die ganze Config - dabei duerfen die
    gemerkten Sollwerte nicht verloren gehen."""
    cfg.write_setpoint(SN, "charge_power_watts", 500)

    config = cfg.load_config()
    config["mqtt"]["host"] = "192.168.0.99"
    cfg.write_config(config)

    assert cfg.read_setpoints()[SN]["charge_power_watts"] == 500
    assert cfg.load_config()["mqtt"]["host"] == "192.168.0.99"


# --------------------------------------- Pause gegen Messung (14.08.2026)
class TestPauseGegenMessung:
    """Die gemerkte Ladepause muss fallen, wenn der Speicher nachweislich laedt.

    Von Dirk im Feld gefunden: Wer in der EcoFlow-App die Backup-Reserve
    umschaltet, startet damit das Laden - die Reserve IST eine Ladesteuerung.
    `chgPauseFlag` ist nicht lesbar, FlowBridge zeigte deshalb weiter
    "pausiert", waehrend die Batterie 41 W aufnahm.

    Live mitgeschnitten am 14.08.2026, 07:47:38 bis 07:47:42.
    """

    @pytest.fixture(autouse=True)
    def sauber(self, monkeypatch):
        import app

        app._ac_charging_set.clear()
        app._ac_charging_gesetzt_um.clear()
        # Nicht in die echte Konfiguration schreiben.
        monkeypatch.setattr(app, "write_setpoint", lambda *a, **k: None)
        return app

    def test_pause_faellt_wenn_die_batterie_laedt(self, sauber):
        app = sauber
        app._ac_charging_set[SN] = False
        app._pause_gegen_messung_pruefen(SN, {"ac_watts_in": 128, "battery_watts_in": 41})
        assert SN not in app._ac_charging_set

    def test_durchleitung_kippt_die_pause_nicht(self, sauber):
        """Netz versorgt einen Verbraucher, Batterie unbeteiligt.

        Genau dieser Fall hat uns schon einmal in die Irre gefuehrt - ohne
        die Batteriebedingung waere jede Durchleitung ein falsches
        "laedt doch"."""
        app = sauber
        app._ac_charging_set[SN] = False
        app._pause_gegen_messung_pruefen(SN, {"ac_watts_in": 128, "battery_watts_in": 0})
        assert app._ac_charging_set[SN] is False

    def test_solarladung_kippt_die_pause_nicht(self, sauber):
        """Die Pause betrifft nur das Laden aus dem NETZ."""
        app = sauber
        app._ac_charging_set[SN] = False
        app._pause_gegen_messung_pruefen(SN, {"ac_watts_in": 0, "battery_watts_in": 60})
        assert app._ac_charging_set[SN] is False

    def test_gemerktes_laeuft_bleibt_unangetastet(self, sauber):
        app = sauber
        app._ac_charging_set[SN] = True
        app._pause_gegen_messung_pruefen(SN, {"ac_watts_in": 128, "battery_watts_in": 41})
        assert app._ac_charging_set[SN] is True

    def test_kleiner_batteriefluss_reicht_nicht(self, sauber):
        """Unter MIN_FLUSS_W ist es Rauschen, kein Ladevorgang."""
        app = sauber
        app._ac_charging_set[SN] = False
        app._pause_gegen_messung_pruefen(SN, {"ac_watts_in": 20, "battery_watts_in": 3})
        assert app._ac_charging_set[SN] is False


class TestSchonfristNachEigenemBefehl:
    """Die Messung darf den Befehl erst widerlegen, wenn sie ihn kennen kann.

    Von Dirk am 16.08.2026 gefunden: Pause druecken, ein paar Sekunden warten,
    und der Schalter stand wieder auf "laeuft". Im Protokoll dreimal sauber
    belegt - zwischen `set_quota ... chgPauseFlag: 1` und "Gemerkte Ladepause
    verworfen" lagen 5, 7 und 8 Millisekunden.

    Ursache: `_execute_command` merkt den neuen Zustand und ruft direkt
    `_publish_state()`, das gegen den Messwert von VOR dem Befehl prueft. Der
    zeigt naturgemaess noch Ladung - der Speicher hatte 8 ms Zeit. Die
    Pruefung verwarf also den Zustand, den sie gerade erst bekommen hatte.
    """

    @pytest.fixture(autouse=True)
    def sauber(self, monkeypatch):
        import app

        app._ac_charging_set.clear()
        app._ac_charging_gesetzt_um.clear()
        app._quota_cache.pop(SN, None)
        app._state.pop(SN, None)
        monkeypatch.setattr(app, "write_setpoint", lambda *a, **k: None)
        yield app
        app._ac_charging_set.clear()
        app._ac_charging_gesetzt_um.clear()
        app._quota_cache.pop(SN, None)
        app._state.pop(SN, None)

    def test_frisch_gesetzte_pause_ueberlebt_die_alte_messung(self, sauber):
        app = sauber
        app._ac_charging_set[SN] = False
        app._ac_charging_gesetzt_um[SN] = time.monotonic()  # gerade eben
        app._pause_gegen_messung_pruefen(SN, {"ac_watts_in": 109, "battery_watts_in": 78})
        assert app._ac_charging_set[SN] is False, "die eigene Pause darf sich nicht selbst verwerfen"

    def test_nach_der_schonfrist_greift_die_messung_wieder(self, sauber):
        """Gegenprobe - sonst haetten wir die Pruefung stillgelegt statt repariert."""
        app = sauber
        app._ac_charging_set[SN] = False
        app._ac_charging_gesetzt_um[SN] = time.monotonic() - app.PAUSE_SCHONFRIST_S - 1
        app._pause_gegen_messung_pruefen(SN, {"ac_watts_in": 109, "battery_watts_in": 78})
        assert SN not in app._ac_charging_set

    def test_ohne_eigenen_befehl_gilt_keine_schonfrist(self, sauber):
        """Ein aus der config.yaml wiederhergestellter Zustand hat keinen
        Zeitpunkt - dort waere eine Schonfrist auch sinnlos, der Befehl liegt
        beliebig lange zurueck."""
        app = sauber
        app._ac_charging_set[SN] = False
        app._pause_gegen_messung_pruefen(SN, {"ac_watts_in": 109, "battery_watts_in": 78})
        assert SN not in app._ac_charging_set

    def test_der_befehlsweg_selbst_behaelt_die_pause(self, sauber, monkeypatch):
        """Der Fall, wie Dirk ihn ausgeloest hat - durch den echten Befehlspfad.

        Die Einzeltests oben pruefen die Bedingung; dieser prueft die
        REIHENFOLGE in `_execute_command`. Wuerde der Zeitpunkt erst nach
        `_publish_state()` gesetzt, waeren jene gruen und dieser rot - und der
        Fehler waere unveraendert da."""
        app = sauber

        class FakeModul:
            @staticmethod
            async def apply_command(*_a, **_k):
                return {"code": "0", "message": "Success"}

        monkeypatch.setattr(app, "load_config", lambda: {
            "ecoflow": {
                "access_key": "AK", "secret_key": "SK",
                "devices": [{"sn": SN, "model": "RIVER 2 Pro"}],
            },
            "mqtt": {}, "ui": {},
        })
        monkeypatch.setattr(app.models, "command_module", lambda _m: FakeModul)
        monkeypatch.setattr(app, "EcoFlowClient", lambda *a, **k: object())
        # Der Speicher laedt zum Zeitpunkt des Befehls noch - genau so war es.
        app._quota_cache[SN] = {"inv.inputWatts": 109, "bms_bmsStatus.inputWatts": 78}

        asyncio.run(app._execute_command(SN, "ac_charging_enabled", "off"))

        assert app._ac_charging_set[SN] is False
        assert app._state[SN]["ac_charging_enabled_set"] is False

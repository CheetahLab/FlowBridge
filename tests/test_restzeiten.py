"""
Restzeiten: EcoFlow packt Ladezeit und Restlaufzeit in EIN Feld
(pd.remainTime) und benutzt 5999 als "keine Schaetzung". Beides muss
aufgeloest sein, bevor Werte an HA/EisBaer gehen.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from device import KEINE_SCHAETZUNG, normalize_quota  # noqa: E402

SN = "R621TEST"


def _status(**quota):
    return normalize_quota(SN, quota)


def test_platzhalter_wird_nicht_als_restzeit_ausgegeben():
    """5999 heisst 'keine Aussage' - roh weitergereicht waeren das 100 Stunden."""
    s = _status(**{"bms_emsStatus.dsgRemainTime": KEINE_SCHAETZUNG})
    assert "discharge_remain_min" not in s
    assert "charge_remain_min" not in s


def test_beim_entladen_wird_remaintime_zur_restlaufzeit():
    s = _status(**{"pd.remainTime": 662, "inv.inputWatts": 0, "mppt.inWatts": 0})
    assert s["discharge_remain_min"] == 662
    assert "charge_remain_min" not in s


def test_beim_laden_wird_remaintime_zur_ladezeit():
    s = _status(**{"pd.remainTime": 143, "inv.inputWatts": 300})
    assert s["charge_remain_min"] == 143
    assert "discharge_remain_min" not in s


def test_solarladen_zaehlt_ebenfalls_als_laden():
    s = _status(**{"pd.remainTime": 200, "inv.inputWatts": 0, "mppt.inWatts": 120})
    assert s["charge_remain_min"] == 200


def test_vorzeichen_entscheidet_nicht_ueber_die_richtung():
    """Die Doku sagt '>0 = bis voll'; das River 2 Pro liefert beim Entladen
    aber positive Werte. Massgeblich ist der gemessene Leistungsfluss."""
    entladen = _status(**{"pd.remainTime": -300, "inv.inputWatts": 0})
    assert entladen["discharge_remain_min"] == 300

    laden = _status(**{"pd.remainTime": -300, "inv.inputWatts": 200})
    assert laden["charge_remain_min"] == 300


def test_es_ist_immer_hoechstens_eine_der_beiden_zeiten_gesetzt():
    for quota in (
        {"pd.remainTime": 662},
        {"pd.remainTime": 143, "inv.inputWatts": 300},
        {"pd.remainTime": 143, "inv.inputWatts": 300,
         "bms_emsStatus.dsgRemainTime": 400},
    ):
        s = _status(**quota)
        gesetzt = [f for f in ("charge_remain_min", "discharge_remain_min") if f in s]
        assert len(gesetzt) <= 1, f"{quota} -> {gesetzt}"


def test_durchleitbetrieb_gilt_nicht_als_laden():
    """Gemessen 13.08.2026: mit Netzkabel speist das Geraet Verbraucher direkt
    durch - Eingang 53 W, Ausgang 53 W, Batterie unbeteiligt. Am Eingang
    festgemacht sprang die Restzeit im Takt des Verbrauchers zwischen beiden
    Kanaelen hin und her."""
    s = _status(**{
        "pd.remainTime": 3629,
        "inv.inputWatts": 53,
        "pd.wattsOutSum": 53,
        "bms_bmsStatus.inputWatts": 0,
    })
    assert s["discharge_remain_min"] == 3629
    assert "charge_remain_min" not in s


def test_laden_mit_gleichzeitigem_verbraucher_bleibt_laden():
    """Der Gegenfall: Batterie nimmt auf, obwohl am Ausgang etwas haengt."""
    s = _status(**{
        "pd.remainTime": 143,
        "inv.inputWatts": 500,
        "pd.wattsOutSum": 53,
        "bms_bmsStatus.inputWatts": 380,
    })
    assert s["charge_remain_min"] == 143
    assert "discharge_remain_min" not in s


def test_anlaufendes_laden_zaehlt_schon_als_laden():
    """ac_watts_in kommt aus dem INV-Modul, battery_watts_in aus dem BMS.
    Beim Anlaufen meldet der Eingang laengst Leistung, waehrend das BMS noch
    0 sagt - allein an der Batterie festgemacht galt das faelschlich als
    Entladung (beobachtet 13.08.2026: 118 W Zufluss, Anzeige 'Ruhe')."""
    s = _status(**{
        "pd.remainTime": 326,
        "inv.inputWatts": 118,
        "bms_bmsStatus.inputWatts": 0,
    })
    assert s["charge_remain_min"] == 326
    assert "discharge_remain_min" not in s


def test_ohne_batteriemessung_zaehlt_der_nettozufluss():
    """Modelle ohne bms.inputWatts: Eingang minus Ausgang entscheidet."""
    durchleitung = _status(**{"pd.remainTime": 300, "inv.inputWatts": 53, "pd.wattsOutSum": 53})
    assert durchleitung["discharge_remain_min"] == 300

    laden = _status(**{"pd.remainTime": 300, "inv.inputWatts": 500, "pd.wattsOutSum": 53})
    assert laden["charge_remain_min"] == 300


def test_dsgremaintime_bleibt_rueckfall_wenn_remaintime_fehlt():
    """quota/all liefert pd.remainTime nicht - dann muss der BMS-Wert her."""
    s = _status(**{"bms_emsStatus.dsgRemainTime": 480})
    assert s["discharge_remain_min"] == 480


def test_dokumentierte_ladezeit_wird_bevorzugt():
    """Delta 2 liefert chgRemainTime direkt - dann nicht raten."""
    s = _status(**{
        "bms_emsStatus.chgRemainTime": 90,
        "pd.remainTime": 999,
        "inv.inputWatts": 500,
    })
    assert s["charge_remain_min"] == 90


def test_rohfeld_taucht_nicht_im_status_auf():
    """_remain_raw ist nur ein Zwischenschritt und gehoert nicht auf den Broker."""
    s = _status(**{"pd.remainTime": 662})
    assert "_remain_raw" not in s
    assert "remain_time_min" not in s

"""
Steuerbefehle fuer die DELTA 2.

WICHTIG - Reifegrad: Diese Befehle stammen aus der offiziellen Doku der
EcoFlow IoT Open Platform (Abschnitt "Delta 2"), sind aber NICHT an echter
Hardware verifiziert. Das ist ein anderer Reifegrad als commands_river2.py,
wo jeder Befehl am Geraet gegengemessen wurde - siehe models.py, SUPPORT_*.

Warum das ausdruecklich dasteht: EcoFlow quittiert Befehle auch dann mit
"Success", wenn das Geraet sie stillschweigend verwirft (mehrfach beobachtet).
Eine erfolgreiche Antwort beweist hier also gar nichts, solange niemand mit
einer echten Delta 2 nachgemessen hat.

Unterschiede zum River 2 Pro, die beim Testen zu beachten sind:
- Der Sollwert der Ladeleistung ist bei der Delta 2 LESBAR (mppt.cfgChgWatts).
  FlowBridge muss sich hier also nichts merken - der Wert kommt vom Geraet.
- Die Doku nennt KEINEN erlaubten Wertebereich fuer chgWatts. Die Stufen unten
  sind daher eine Annahme nach Produktangaben (200-1200 W). Wer eine Delta 2
  hat: Wert setzen, dann mppt.cfgChgWatts auslesen - zeigt das Geraet etwas
  anderes, stimmen die Grenzen nicht und gehoeren hier korrigiert.
- Spannungsangaben sind teils anders skaliert (in einem Doku-Beispiel
  inv.cfgAcOutVol = 230000, also Millivolt statt Volt). Bei acOutCfg deshalb
  besonders genau hinsehen.
"""
from __future__ import annotations

import logging

from commands_river2 import CommandError, _parse_bool, _parse_percent
from commands_river2 import _watth_config  # gleiche watthConfig-Semantik
from ecoflow_client import EcoFlowClient

logger = logging.getLogger(__name__)

MODULE_PD = 1
MODULE_BMS = 2
MODULE_MPPT = 5

# VORLAEUFIG - nicht aus der Doku, sondern aus Produktangaben abgeleitet.
# Siehe Modulkopf: an echter Hardware pruefen und ggf. korrigieren.
CHARGE_WATTS_MIN = 200
CHARGE_WATTS_MAX = 1200
CHARGE_WATTS_STEP = 100
CHARGE_WATTS_STEPS: tuple[int, ...] = tuple(
    range(CHARGE_WATTS_MIN, CHARGE_WATTS_MAX + CHARGE_WATTS_STEP, CHARGE_WATTS_STEP)
)


def _ac_out_cfg(current: dict, **overrides) -> dict:
    """Vollstaendiges acOutCfg-Set (wie beim River 2: Teil-Updates wirken nicht).

    out_freq ist beim Schreiben ein Enum (1 = 50 Hz, 2 = 60 Hz), beim Lesen
    kommen echte Hertz zurueck - dieselbe Asymmetrie wie beim River 2.
    """
    freq_hz = current.get("ac_output_freq_hz", 50)
    params = {
        "enabled": int(current.get("ac_output_enabled", 0)),
        "xboost": int(current.get("xboost_enabled", 0)),
        "out_voltage": int(current.get("ac_output_voltage", 230)),
        "out_freq": 2 if int(freq_hz) == 60 else 1,
    }
    params.update(overrides)
    return params


async def apply_command(
    client: EcoFlowClient, sn: str, property_name: str, raw_value: str, current: dict | None = None
) -> dict:
    """Wie commands_river2.apply_command, aber mit den Delta-2-Befehlen."""
    current = current or {}

    if property_name == "ac_output_enabled":
        return await client.set_quota(
            sn, MODULE_MPPT, "acOutCfg", _ac_out_cfg(current, enabled=_parse_bool(raw_value))
        )

    if property_name == "xboost_enabled":
        return await client.set_quota(
            sn, MODULE_MPPT, "acOutCfg", _ac_out_cfg(current, xboost=_parse_bool(raw_value))
        )

    if property_name == "car_output_enabled":
        return await client.set_quota(
            sn, MODULE_MPPT, "mpptCar", {"enabled": _parse_bool(raw_value)}
        )

    if property_name == "dc_output_enabled":
        # Delta-2-spezifisch: eigener DC-Ausgang neben dem KFZ-Ausgang.
        return await client.set_quota(
            sn, MODULE_PD, "dcOutCfg", {"enabled": _parse_bool(raw_value)}
        )

    if property_name == "ac_charging_enabled":
        watts = int(current.get("charge_power_watts") or CHARGE_WATTS_MIN)
        return await client.set_quota(
            sn,
            MODULE_MPPT,
            "acChgCfg",
            {"chgWatts": watts, "chgPauseFlag": 0 if _parse_bool(raw_value) else 1},
        )

    if property_name == "charge_power_watts":
        try:
            watts = int(raw_value.strip())
        except ValueError as exc:
            raise CommandError(f"Ladeleistung erwartet eine Ganzzahl, bekam '{raw_value}'") from exc
        if watts not in CHARGE_WATTS_STEPS:
            raise CommandError(
                f"Ungueltige Ladeleistung {watts} W - erlaubt sind "
                f"{CHARGE_WATTS_MIN}-{CHARGE_WATTS_MAX} W in {CHARGE_WATTS_STEP}-W-Schritten "
                "(Grenzen vorlaeufig, nicht an Hardware geprueft)"
            )
        pausiert = current.get("ac_charging_enabled_set") is False
        return await client.set_quota(
            sn,
            MODULE_MPPT,
            "acChgCfg",
            {"chgWatts": watts, "chgPauseFlag": 1 if pausiert else 0},
        )

    if property_name == "charge_limit_percent":
        return await client.set_quota(
            sn, MODULE_BMS, "upsConfig", {"maxChgSoc": _parse_percent(raw_value, property_name)}
        )

    if property_name == "discharge_limit_percent":
        return await client.set_quota(
            sn, MODULE_BMS, "dsgCfg", {"minDsgSoc": _parse_percent(raw_value, property_name)}
        )

    if property_name == "backup_reserve_percent":
        return await client.set_quota(
            sn, MODULE_PD, "watthConfig",
            _watth_config(current, bpPowerSoc=_parse_percent(raw_value, property_name)),
        )

    if property_name == "backup_reserve_enabled":
        return await client.set_quota(
            sn, MODULE_PD, "watthConfig",
            _watth_config(current, isConfig=int(_parse_bool(raw_value))),
        )

    if property_name == "quiet_mode":
        # Delta-2-spezifisch (leiser Lademodus). Beim River 2 Pro wirkungslos.
        return await client.set_quota(
            sn, MODULE_MPPT, "quietMode", {"enabled": _parse_bool(raw_value)}
        )

    raise CommandError(f"Unbekanntes cmnd-Property '{property_name}' fuer DELTA 2")

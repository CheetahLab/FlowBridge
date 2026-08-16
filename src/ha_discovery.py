"""
Home-Assistant-MQTT-Discovery fuer FlowBridge.

HA erkennt Entitaeten ueber retained Config-Topics unterhalb eines Praefixes
(Standard "homeassistant"):

    homeassistant/{component}/{node_id}/{object_id}/config

Umgesetzt nach der HA-MQTT-Discovery-Spezifikation:
- Jede Entitaet bekommt eine stabile `unique_id` (Seriennummer + Feld), sonst
  laesst HA sie nicht ueber die Oberflaeche verwalten.
- Alle Entitaeten eines Speichers teilen sich einen `device`-Block, damit sie
  in HA unter EINEM Geraet erscheinen statt einzeln herumzuliegen.
- `availability` zweistufig: FlowBridge selbst UND das jeweilige Geraet. Nur
  wenn beides online ist, gilt die Entitaet als verfuegbar - so verschwindet
  bei einem FlowBridge-Absturz nicht nur ein Speicher, sondern ehrlich alles.
- `device_class` und `state_class` gesetzt, damit HA Einheiten, Symbole und
  Langzeitstatistik richtig zuordnet.

Steuerbare Entitaeten (switch/number) entstehen nur fuer Modelle, deren
Befehle FlowBridge kennt - sonst hinge in HA ein Schalter, der nichts tut.
"""
from __future__ import annotations

import json

from mqtt_bridge import COMMAND_SEGMENT

# feld -> (Anzeigename, Einheit, device_class, state_class, icon)
_SENSOREN: dict[str, tuple[str, str | None, str | None, str | None, str | None]] = {
    "soc_percent": ("Ladezustand", "%", "battery", "measurement", None),
    "battery_soc_percent": ("Ladezustand (BMS)", "%", "battery", "measurement", None),
    "ac_watts_in": ("AC-Ladeleistung", "W", "power", "measurement", None),
    "dc_watts_in": ("DC-Eingang", "W", "power", "measurement", "mdi:solar-power"),
    "battery_watts_in": ("Batterie laden", "W", "power", "measurement", None),
    "battery_watts_out": ("Batterie entladen", "W", "power", "measurement", None),
    "watts_out": ("Ausgang gesamt", "W", "power", "measurement", None),
    "ac_watts_out": ("AC-Ausgangsleistung", "W", "power", "measurement", None),
    "car_watts": ("KFZ-Ausgang", "W", "power", "measurement", "mdi:car"),
    "usb1_watts": ("USB-A", "W", "power", "measurement", "mdi:usb"),
    "typec1_watts": ("USB-C Ausgang", "W", "power", "measurement", "mdi:usb-c-port"),
    "typec_charge_watts": ("USB-C Eingang", "W", "power", "measurement", "mdi:usb-c-port"),
    "ac_output_voltage": ("AC-Spannung", "V", "voltage", "measurement", None),
    "ac_output_freq_hz": ("AC-Frequenz", "Hz", "frequency", "measurement", None),
    "battery_temp_c": ("Batterietemperatur", "°C", "temperature", "measurement", None),
    "charge_remain_min": ("Bis voll geladen", "min", "duration", "measurement", "mdi:battery-clock"),
    "discharge_remain_min": (
        "Restlaufzeit", "min", "duration", "measurement", "mdi:battery-clock-outline"),
    "cycles": ("Ladezyklen", None, None, "total_increasing", "mdi:battery-sync"),
}

# feld -> (Anzeigename, cmd-Property, icon)
_SCHALTER: dict[str, tuple[str, str, str]] = {
    "ac_output_enabled": ("AC-Ausgang", "ac_output_enabled", "mdi:power-socket-de"),
    "xboost_enabled": ("X-Boost", "xboost_enabled", "mdi:flash"),
    "car_output_enabled": ("12V-KFZ-Ausgang", "car_output_enabled", "mdi:car-battery"),
    # Zweiteilig wie in der EcoFlow-App: Schalter hier, Prozentwert unter
    # _ZAHLEN. Der Wert wirkt nur, wenn der Schalter an ist.
    "backup_reserve_enabled": (
        "Backup-Reserve aktiv", "backup_reserve_enabled", "mdi:home-battery"),
}

# feld -> (Anzeigename, cmd-Property, min, max, step, Einheit, icon)
_ZAHLEN: dict[str, tuple[str, str, int, int, int, str, str]] = {
    "charge_limit_percent": ("Ladelimit", "charge_limit_percent", 0, 100, 1, "%", "mdi:battery-high"),
    "discharge_limit_percent": (
        "Entladelimit", "discharge_limit_percent", 0, 100, 1, "%", "mdi:battery-low"),
    "backup_reserve_percent": (
        "Backup-Reserve", "backup_reserve_percent", 0, 100, 1, "%", "mdi:home-battery"),
}


def _device_block(sn: str, name: str, model: str | None) -> dict:
    return {
        "identifiers": [f"flowbridge_{sn}"],
        "name": name or sn,
        "manufacturer": "EcoFlow",
        "model": model or "unbekannt",
        "serial_number": sn,
        "via_device": "flowbridge",
    }


def build_entities(
    sn: str,
    name: str,
    model: str | None,
    base_topic: str,
    bridge_availability_topic: str,
    ecoflow_availability_topic: str,
    controllable: bool,
    charge_steps: list[int],
    discovery_prefix: str = "homeassistant",
    nur_lesbar: tuple[str, ...] = (),
) -> list[tuple[str, str]]:
    """Liefert [(config_topic, json_payload), ...] fuer ein Geraet.

    Ein leerer payload loescht die Entitaet in HA - dafuer gibt es
    build_removals().
    """
    geraet = _device_block(sn, name, model)
    # Drei unabhaengige Ausfallquellen, alle drei muessen stimmen:
    # FlowBridge selbst, die Verbindung zur EcoFlow-Cloud und das Geraet.
    # Faellt die Cloud aus, sind die Werte eingefroren - ohne diesen Eintrag
    # zeigte HA sie unveraendert weiter, als waeren sie aktuell.
    verfuegbarkeit = [
        {"topic": bridge_availability_topic},
        {"topic": ecoflow_availability_topic},
        {"topic": f"{base_topic}/{sn}/available"},
    ]
    gemeinsam = {
        "device": geraet,
        "availability": verfuegbarkeit,
        "availability_mode": "all",
    }
    eintraege: list[tuple[str, str]] = []

    def cfg_topic(component: str, objekt: str) -> str:
        return f"{discovery_prefix}/{component}/flowbridge_{sn}/{objekt}/config"

    for feld, (bezeichnung, einheit, device_class, state_class, icon) in _SENSOREN.items():
        payload = {
            **gemeinsam,
            "name": bezeichnung,
            "unique_id": f"flowbridge_{sn}_{feld}",
            "object_id": f"flowbridge_{sn}_{feld}",
            "state_topic": f"{base_topic}/{sn}/status/{feld}",
        }
        if einheit:
            payload["unit_of_measurement"] = einheit
        if device_class:
            payload["device_class"] = device_class
        if state_class:
            payload["state_class"] = state_class
        if icon:
            payload["icon"] = icon
        eintraege.append((cfg_topic("sensor", feld), json.dumps(payload, ensure_ascii=False)))

    if not controllable:
        # Ohne bekannte Befehle keine Schalter/Regler anlegen - sie wuerden in
        # HA existieren und beim Betaetigen wirkungslos bleiben.
        return eintraege

    for feld, (bezeichnung, prop, icon) in _SCHALTER.items():
        if feld in nur_lesbar:
            # Das Geraet meldet den Zustand, nimmt ihn aber nicht an. Als
            # binary_sensor bleibt der Wert in HA sichtbar - ein Schalter
            # waere ein Knopf, der nichts tut.
            eintraege.append((
                cfg_topic("binary_sensor", feld),
                json.dumps({
                    **gemeinsam,
                    "name": bezeichnung,
                    "unique_id": f"flowbridge_{sn}_{feld}",
                    "object_id": f"flowbridge_{sn}_{feld}",
                    "state_topic": f"{base_topic}/{sn}/status/{feld}",
                    "payload_on": "1",
                    "payload_off": "0",
                    "icon": icon,
                }, ensure_ascii=False),
            ))
            continue
        payload = {
            **gemeinsam,
            "name": bezeichnung,
            "unique_id": f"flowbridge_{sn}_{feld}",
            "object_id": f"flowbridge_{sn}_{feld}",
            "state_topic": f"{base_topic}/{sn}/status/{feld}",
            "command_topic": f"{base_topic}/{sn}/{COMMAND_SEGMENT}/{prop}",
            # Gelesen wird 1/0, geschrieben on/off - deshalb getrennte Angaben.
            "state_on": "1",
            "state_off": "0",
            "payload_on": "on",
            "payload_off": "off",
            "icon": icon,
        }
        eintraege.append((cfg_topic("switch", feld), json.dumps(payload, ensure_ascii=False)))

    # AC-Laden pausieren: Zustand kommt je nach Modell aus verschiedenen
    # Quellen, deshalb ueber das gemerkte Feld statt ueber chgPauseFlag.
    pause_payload = {
        **gemeinsam,
        "name": "AC-Laden",
        "unique_id": f"flowbridge_{sn}_ac_charging_enabled",
        "object_id": f"flowbridge_{sn}_ac_charging_enabled",
        "state_topic": f"{base_topic}/{sn}/status/ac_charging_enabled_set",
        "command_topic": f"{base_topic}/{sn}/{COMMAND_SEGMENT}/ac_charging_enabled",
        "state_on": "true",
        "state_off": "false",
        "payload_on": "on",
        "payload_off": "off",
        "icon": "mdi:power-plug-battery",
    }
    eintraege.append(
        (cfg_topic("switch", "ac_charging_enabled"), json.dumps(pause_payload, ensure_ascii=False))
    )

    for feld, (bezeichnung, prop, minimum, maximum, schritt, einheit, icon) in _ZAHLEN.items():
        if feld in nur_lesbar:
            # Wie oben bei den Schaltern: als Sensor sichtbar, aber nicht
            # als Eingabefeld, das nichts bewirkt.
            eintraege.append((
                cfg_topic("sensor", feld),
                json.dumps({
                    **gemeinsam,
                    "name": bezeichnung,
                    "unique_id": f"flowbridge_{sn}_{feld}",
                    "object_id": f"flowbridge_{sn}_{feld}",
                    "state_topic": f"{base_topic}/{sn}/status/{feld}",
                    "unit_of_measurement": einheit,
                    "icon": icon,
                }, ensure_ascii=False),
            ))
            continue
        payload = {
            **gemeinsam,
            "name": bezeichnung,
            "unique_id": f"flowbridge_{sn}_{feld}",
            "object_id": f"flowbridge_{sn}_{feld}",
            "state_topic": f"{base_topic}/{sn}/status/{feld}",
            "command_topic": f"{base_topic}/{sn}/{COMMAND_SEGMENT}/{prop}",
            "min": minimum,
            "max": maximum,
            "step": schritt,
            "unit_of_measurement": einheit,
            "mode": "box",
            "icon": icon,
        }
        eintraege.append((cfg_topic("number", feld), json.dumps(payload, ensure_ascii=False)))

    if charge_steps:
        # Schrittweite aus der Modell-Stufenliste ableiten, statt sie fest zu
        # verdrahten: River 2 Pro 50 W, Delta 2 100 W.
        schritt = charge_steps[1] - charge_steps[0] if len(charge_steps) > 1 else 50
        payload = {
            **gemeinsam,
            "name": "AC-Ladeleistung",
            "unique_id": f"flowbridge_{sn}_charge_power_watts",
            "object_id": f"flowbridge_{sn}_charge_power_watts",
            "state_topic": f"{base_topic}/{sn}/status/charge_power_watts_set",
            "command_topic": f"{base_topic}/{sn}/{COMMAND_SEGMENT}/charge_power_watts",
            "min": charge_steps[0],
            "max": charge_steps[-1],
            "step": schritt,
            "unit_of_measurement": "W",
            "device_class": "power",
            "mode": "slider",
            "icon": "mdi:transmission-tower-import",
        }
        eintraege.append(
            (cfg_topic("number", "charge_power_watts"), json.dumps(payload, ensure_ascii=False))
        )

    return eintraege


# Felder, die es einmal gab und die inzwischen anders heissen. Ihre
# Config-Topics sind retained - ohne aktives Loeschen haengt in HA fuer immer
# eine Entitaet, die nie wieder einen Wert bekommt.
VERALTETE_SENSOREN = ("remain_time_min",)


def build_removals(sn: str, discovery_prefix: str = "homeassistant") -> list[str]:
    """Config-Topics eines Geraets, die zum Loeschen leer gesendet werden."""
    topics = [f"{discovery_prefix}/sensor/flowbridge_{sn}/{f}/config" for f in _SENSOREN]
    topics += [f"{discovery_prefix}/switch/flowbridge_{sn}/{f}/config" for f in _SCHALTER]
    topics.append(f"{discovery_prefix}/switch/flowbridge_{sn}/ac_charging_enabled/config")
    topics += [f"{discovery_prefix}/number/flowbridge_{sn}/{f}/config" for f in _ZAHLEN]
    topics.append(f"{discovery_prefix}/number/flowbridge_{sn}/charge_power_watts/config")
    return topics + build_legacy_removals(sn, discovery_prefix)


def build_legacy_removals(sn: str, discovery_prefix: str = "homeassistant") -> list[str]:
    """Config-Topics umbenannter Felder.

    Muss AUCH bei aktiver Discovery gesendet werden - sonst bleibt die alte
    Entitaet neben der neuen bestehen und zeigt fuer immer ihren letzten Wert.
    """
    return [f"{discovery_prefix}/sensor/flowbridge_{sn}/{f}/config" for f in VERALTETE_SENSOREN]

"""
Normalisierung: EcoFlow-Quota-Dict -> neutraler FlowBridge-Status-Dict.

EcoFlow-Feldnamen unterscheiden sich je nach Geraete-Generation (River 2 /
River 2 Pro vs. Delta 2/Pro vs. PowerStream ...). Statt hart auf ein Modell
zu mappen, wird pro Metrik eine Liste bekannter Kandidaten-Keys durchprobiert
– der erste vorhandene gewinnt. Fehlt eine Metrik komplett, wird sie im
Ergebnis weggelassen (nicht als None durchgereicht), damit Dashboard/MQTT-
Payload sauber bleiben.

VERIFIZIERT (12.08.2026) gegen einen echten quota/all-Dump eines River 2
(SN-Praefix R621) via scripts/test_quota.py UND gegen die offizielle
EcoFlow-Dev-Portal-Doku (GetAllQuotaResponse fuer River 2 Pro) – beide
stimmen exakt ueberein. Batterietemperatur und Ladezyklen sind fuer dieses
Geraet OFFIZIELL nicht Teil von quota/all (nicht nur "gerade nicht
geliefert") – falls ueberhaupt verfuegbar, dann nur ueber den MQTT-Live-Push,
den FlowBridge aktuell nicht nutzt (nur REST-Polling).

Andere Modelle (Delta 2/Pro etc.) sind weiterhin ungetestet – Kandidaten
dafuer bleiben Vermutungen aus Community-Projekten, bis jemand mit so einem
Geraet quota/all einmal dagegen laufen laesst.
"""
from __future__ import annotations

from typing import Any

# EcoFlows Platzhalter fuer "keine Schaetzung moeglich" (99 h 59 min). Roh
# weitergereicht stuende in Home Assistant und EisBaer eine erfundene Restzeit
# von 100 Stunden - schlimmer als gar kein Wert.
KEINE_SCHAETZUNG = 5999

# Darunter ist ein Leistungsfluss nicht von Messrauschen zu unterscheiden.
MIN_FLUSS_W = 10

# metric_name -> Liste moeglicher Quota-Keys, in Praeferenz-Reihenfolge.
# Kommentar "verifiziert" = bestaetigt gegen echten River-2-quota/all-Dump.
_METRIC_CANDIDATES: dict[str, list[str]] = {
    "soc_percent": ["pd.soc", "bms_bmsStatus.soc", "bmsMaster.soc"],  # verifiziert: pd.soc
    # ACHTUNG: bpPowerSoc ist NICHT der SoC einer Zusatzbatterie (so war es hier
    # zunaechst falsch benannt), sondern die eingestellte Backup-Reserve in
    # Prozent - ein Sollwert aus watthConfig, kein Messwert. Siehe Dev-Portal:
    # "bpPowerSoc: Backup reserve".
    "backup_reserve_percent": ["pd.bpPowerSoc"],
    # Der EIN/AUS-Schalter der Backup-Reserve - in der EcoFlow-App genau so
    # beschriftet. Am 14.08.2026 live verifiziert: Umlegen in der App
    # bewegt dieses Feld (1->0->1->0 im Push-Mitschnitt).
    #
    # Hiess bis dahin "energy_management_enabled" - ein Name aus der Zeit,
    # als nur die Herkunft (watthConfig/isConfig) bekannt war, nicht die
    # Bedeutung. Umbenannt, weil ein falscher Name in einem Produkt, das
    # weitergegeben wird, laenger schadet als eine einmalige Umstellung.
    "backup_reserve_enabled": ["pd.watchIsConfig"],
    "ac_watts_in": ["inv.inputWatts"],  # laut Doku "AC input real-time power" = Ladeleistung am Netz
    "dc_watts_in": ["mppt.inWatts"],  # laut Doku "DC input real-time power" (Solar ODER KFZ)
    "watts_out": ["pd.wattsOutSum", "pd.dsgPowerAC"],  # laut Doku "Total output real-time power"
    "ac_watts_out": ["inv.outputWatts"],  # laut Doku "AC output real-time power"
    "battery_temp_c": ["bms_bmsStatus.temp", "bmsMaster.temp"],  # weder in quota/all NOCH im MQTT-Push (Stand 12.08.2026)
    "discharge_remain_min": ["bms_emsStatus.dsgRemainTime", "bms_bmsStatus.remainTime"],  # verifiziert
    # NUR im MQTT-Push, nicht in quota/all (Capture 12.08.2026, scripts/capture_mqtt.py).
    # Traegt BEIDE Richtungen in einem Feld - wird unten auf charge_remain_min /
    # discharge_remain_min verteilt und erscheint selbst nicht im Ergebnis.
    "_remain_raw": ["pd.remainTime"],
    "charge_remain_min": ["bms_emsStatus.chgRemainTime"],  # Delta 2 u. a.; River 2 Pro liefert es nicht
    "battery_watts_in": ["bms_bmsStatus.inputWatts"],  # Lade-Leistung an der Batterie
    "battery_watts_out": ["bms_bmsStatus.outputWatts"],
    "battery_soc_percent": ["bms_bmsStatus.soc"],  # BMS-eigener SoC (kann minimal von pd.soc abweichen)
    "ac_output_enabled": ["mppt.cfgAcEnabled"],  # verifiziert (war vorher falsch: inv.cfgAcEnabled)
    "ac_output_voltage": ["mppt.cfgAcOutVol"],  # verifiziert
    "ac_output_freq_hz": ["mppt.cfgAcOutFreq"],  # verifiziert
    "xboost_enabled": ["mppt.cfgAcXboost"],  # verifiziert
    "car_output_enabled": ["pd.carState"],  # verifiziert (12V-KFZ-Ausgang)
    "car_watts": ["pd.carWatts"],  # verifiziert
    "usb1_watts": ["pd.usb1Watts"],  # verifiziert
    "typec1_watts": ["pd.typec1Watts"],  # verifiziert
    "typec_charge_watts": ["pd.typecChaWatts"],  # verifiziert
    "charge_limit_percent": ["bms_emsStatus.maxChargeSoc", "pd.chgSocMax"],  # verifiziert (war vorher falsch: bms_bmsStatus.*)
    "discharge_limit_percent": ["bms_emsStatus.minDsgSoc", "pd.dsgSocMin"],  # verifiziert (war vorher falsch: bms_bmsStatus.*)
    "cycles": ["bms_bmsStatus.cycles", "bmsMaster.cycles"],  # weder in quota/all NOCH im MQTT-Push (Stand 12.08.2026)
    # Sollwerte, die manche Modelle zurueckmelden. Das River 2 Pro tut das
    # NICHT (deshalb dort der gemerkte Wert), die DELTA 2 laut Doku schon -
    # dann ist der gelesene Wert die verlaesslichere Quelle.
    "charge_power_watts": ["mppt.cfgChgWatts"],
    "charge_paused": ["mppt.chgPauseFlag", "inv.chgPauseFlag"],
}

# BEWUSST NICHT gemappt (Capture 12.08.2026): inv.cfgAcEnabled / inv.cfgAcXboost /
# inv.cfgAcOutVol / inv.cfgAcOutFreq und mppt.carState. Das INV-Modul meldet
# dieselben AC-Groessen wie MPPT, aber teils in anderer Kodierung und mit
# abweichenden Werten (im Capture: mppt 230V/50Hz vs. inv 0V/2) - MPPT ist hier
# die verlaessliche Quelle. mppt.carState dupliziert pd.carState.


# Praefix -> (Modulname fuers UI, moduleType laut EcoFlow-Doku)
MODULE_LABELS: dict[str, tuple[str, int]] = {
    "pd.": ("PD", 1),
    "bms_bmsStatus.": ("BMS", 2),
    "bms_emsStatus.": ("EMS", 2),
    "inv.": ("INV", 3),
    "mppt.": ("MPPT", 5),
}


def group_by_module(quota: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Rohe Quota-Felder nach Modul gruppieren (fuer die Kontroll-Tabs im UI).

    Feldnamen werden dabei ohne Praefix gefuehrt - das Modul steht ja schon in
    der Gruppe. Unbekannte Praefixe landen unter "Sonstige", damit nichts
    stillschweigend verschwindet, wenn EcoFlow ein neues Modul einfuehrt.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for key, value in quota.items():
        for prefix, (label, _module_type) in MODULE_LABELS.items():
            if key.startswith(prefix):
                grouped.setdefault(label, {})[key[len(prefix):]] = value
                break
        else:
            grouped.setdefault("Sonstige", {})[key] = value
    return grouped


def _ohne_platzhalter(wert: Any) -> int | None:
    """5999 heisst 'keine Schaetzung' - dann lieber gar keinen Wert liefern."""
    if not isinstance(wert, (int, float)) or isinstance(wert, bool):
        return None
    return None if abs(int(wert)) >= KEINE_SCHAETZUNG else int(wert)


def _restzeiten_aufloesen(result: dict[str, Any]) -> None:
    """Verteilt pd.remainTime auf zwei Felder mit FESTER Bedeutung.

    EcoFlow packt beide Richtungen in ein Feld: mal ist es die Zeit bis voll,
    mal die verbleibende Laufzeit. Ein MQTT-Kanal, der im Betrieb seine
    Bedeutung wechselt, ist in HA und EisBaer nicht verknuepfbar - deshalb
    hier die Aufteilung in:

        charge_remain_min     - bis zum Ladeende (nur waehrend des Ladens)
        discharge_remain_min  - verbleibende Laufzeit (sonst)

    Die Richtung kommt aus dem tatsaechlichen Leistungsfluss und ausdruecklich
    NICHT aus dem Vorzeichen: die Doku (Delta 2) sagt ">0 = bis voll geladen",
    das River 2 Pro liefert aber im Leerlauf-Entladen einen POSITIVEN Wert
    (662 min bei 43 % und ~30 W Eigenverbrauch - das ist Laufzeit, keine
    Ladezeit). Der Leistungsfluss ist messbar, das Vorzeichen nur behauptet.

    dsgRemainTime bleibt der Rueckfall: es steht auf echter Hardware fast
    immer auf dem Platzhalter, waehrend pd.remainTime sich wirklich bewegt.
    """
    roh = _ohne_platzhalter(result.pop("_remain_raw", None))
    betrag = abs(roh) if roh is not None else None
    dsg = _ohne_platzhalter(result.get("discharge_remain_min"))
    chg = _ohne_platzhalter(result.get("charge_remain_min"))

    # Richtung an der BATTERIE ablesen, nicht am Eingang: bei angestecktem
    # Netzkabel speist das Geraet Verbraucher direkt durch (Durchleitbetrieb) -
    # dann ist die Eingangsleistung hoch, waehrend die Batterie voellig
    # unbeteiligt ist. Am Eingang festgemacht sprang derselbe Wert im Takt des
    # Verbrauchers zwischen beiden Kanaelen hin und her (gemessen 13.08.2026
    # mit einem taktenden Geraet am AC-Ausgang).
    #
    # ODER, weil beide Quellen zeitversetzt eintreffen: ac_watts_in stammt aus
    # dem INV-Modul, battery_watts_in aus dem BMS. Beim Anlaufen meldet der
    # Eingang laengst Leistung, waehrend das BMS noch 0 sagt.
    zu = (result.get("ac_watts_in") or 0) + (result.get("dc_watts_in") or 0)
    netto = zu - (result.get("watts_out") or 0)
    laedt = (result.get("battery_watts_in") or 0) > 0 or netto > MIN_FLUSS_W

    # Bewusst sich gegenseitig ausschliessend: das Geraet laedt ODER es
    # entlaedt. Beide Zeiten gleichzeitig zu melden hiesse, dass eine davon
    # eine Schaetzung fuer einen Zustand ist, in dem das Geraet gar nicht ist.
    if laedt:
        result["charge_remain_min"] = chg if chg is not None else betrag
        result["discharge_remain_min"] = None
    else:
        result["charge_remain_min"] = None
        result["discharge_remain_min"] = betrag if betrag is not None else dsg

    # Fehlende Werte ganz weglassen statt als None durchzureichen (Prinzip wie
    # bei den uebrigen Metriken).
    for feld in ("charge_remain_min", "discharge_remain_min"):
        if result.get(feld) is None:
            result.pop(feld, None)


def normalize_quota(sn: str, quota: dict[str, Any]) -> dict[str, Any]:
    """quota/all-Antwort (oder MQTT-quota-Push) -> neutraler Status-Dict fuers Dashboard/MQTT."""
    result: dict[str, Any] = {"sn": sn}
    for metric, candidates in _METRIC_CANDIDATES.items():
        for key in candidates:
            if key in quota:
                result[metric] = quota[key]
                break
    _restzeiten_aufloesen(result)
    # Rohfelder zusaetzlich mitgeben, nach Modul gruppiert - speist die
    # Kontroll-Tabs (MPPT/BMS/...) im UI. Nichts geht verloren, auch Felder
    # ohne eigene Metrik bleiben sichtbar.
    result["_modules"] = group_by_module(quota)
    return result

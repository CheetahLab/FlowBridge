"""
Steuerbefehle fuer River 2 / River 2 Pro (moduleType/operateType/params laut
EcoFlow-Dev-Portal-Doku, Stand 12.08.2026).

Der Kern (app.py) kennt diese Details bewusst nicht, er ruft nur
apply_command(client, sn, property_name, raw_value) auf. Jede
Property validiert ihren Wert selbst und wirft NIE – Fehler werden als
CommandError signalisiert, kein Crash im Poller/API-Handler.

Andere Geraetefamilien (Delta-Serie) brauchen ein eigenes Modul nach diesem
Muster, sobald jemand mit so einem Geraet die Set-Commands verifiziert hat.
"""
from __future__ import annotations

import logging

from ecoflow_client import EcoFlowClient

logger = logging.getLogger(__name__)

MODULE_PD = 1
MODULE_BMS = 2
MODULE_MPPT = 5

# Bewusst grosszuegig: on/off ist die eigene Schreibweise, aber ein
# MQTT-Client schickt genauso naheliegend true, 1 oder yes. Wer von Hand mit
# mosquitto_pub testet, tippt eher "1" als "on" - und eine abgelehnte
# Schaltung sieht auf dem MQTT-Weg wie "tut gar nichts" aus, weil es dort
# keinen Rueckkanal fuer Fehlermeldungen gibt.
_BOOL_VALUES = {
    "on": 1, "off": 0,
    "true": 1, "false": 0,
    "1": 1, "0": 0,
    "an": 1, "aus": 0,
    "ein": 1,
    "yes": 1, "no": 0,
}

# AC-Ladeleistung River 2 Pro: 100 W bis 870 W in 50-W-Schritten.
# ACHTUNG: 870 liegt NICHT im 50er-Raster ab 100 (100+50*15 = 850) - der
# Hoechstwert ist eine eigene, zusaetzliche Stufe. Eine reine Modulo-Pruefung
# haette ihn faelschlich abgelehnt.
CHARGE_WATTS_MIN = 100
CHARGE_WATTS_MAX = 870
CHARGE_WATTS_STEP = 50
CHARGE_WATTS_STEPS: tuple[int, ...] = tuple(
    range(CHARGE_WATTS_MIN, CHARGE_WATTS_MAX, CHARGE_WATTS_STEP)
) + (CHARGE_WATTS_MAX,)


# Felder, die dieses Modell zwar MELDET, aber ueber die offene API nicht
# annimmt. Am 14.08.2026 an Dirks River 2 Pro gemessen: watthConfig wurde in
# drei Laeufen und ueber eine Viertelstunde nie wirksam - weder mit
# moduleType 1 noch 5, weder mit vollstaendigem noch mit halbem Param-Satz.
# EcoFlow quittierte jedes Mal ohne Fehler, pd.watchIsConfig blieb auf 1 und
# in der EcoFlow-App bewegte sich nichts.
#
# Umgekehrt kommt das Umschalten IN der App sofort bei FlowBridge an - der
# Lesepfad ist also einwandfrei. Die App benutzt zum Schreiben offenbar einen
# anderen Weg als die dokumentierte Schnittstelle.
#
# Konsequenz: anzeigen, nicht anbieten. Ein Bedienelement, das nachweislich
# nichts bewirkt, ist schlimmer als keines - man sucht den Fehler dann bei
# sich.
NUR_LESBAR: tuple[str, ...] = ("backup_reserve_enabled", "backup_reserve_percent")


class CommandError(Exception):
    """Ungueltiges property/value oder von EcoFlow abgelehnt – nie eine rohe Exception nach aussen."""


def _parse_bool(raw_value: str) -> int:
    parsed = _BOOL_VALUES.get(raw_value.strip().lower())
    if parsed is None:
        raise CommandError(f"Ungueltiger Wert '{raw_value}' – erwartet on/off")
    return parsed


def _parse_percent(raw_value: str, field_name: str) -> int:
    try:
        value = int(raw_value.strip())
    except ValueError as exc:
        raise CommandError(f"'{field_name}' erwartet eine Ganzzahl, bekam '{raw_value}'") from exc
    if not (0 <= value <= 100):
        raise CommandError(f"'{field_name}' muss zwischen 0 und 100 liegen, bekam {value}")
    return value


def _ac_out_cfg(current: dict, **overrides) -> dict:
    """Vollstaendiges acOutCfg-Param-Set bauen (enabled, xboost, out_voltage, out_freq).

    WICHTIG (verifiziert 12.08.2026): acOutCfg mit nur EINEM Feld quittiert
    EcoFlow zwar mit code "0"/Success, das Geraet ignoriert es aber - der
    Zustand aendert sich nachweislich nicht. Es muessen immer alle vier
    Felder mitgeschickt werden; die nicht geaenderten kommen aus dem zuletzt
    gelesenen Quota-Stand.

    Achtung Kodierungs-Asymmetrie: out_freq ist beim SCHREIBEN ein Enum
    (1 = 50Hz, 2 = 60Hz), beim LESEN meldet mppt.cfgAcOutFreq dagegen die
    echten Hertz (50/60). Deshalb hier zurueckuebersetzen.

    KEINE VORGABEWERTE (16.08.2026). Bis dahin standen hier Rueckfallwerte:
    fehlte der Stand, ging `xboost: 0` mit hinaus. Wer direkt nach einem
    Neustart den AC-Ausgang einschaltete - da ist der Stand noch leer, der
    erste Push braucht ein paar Sekunden - schaltete damit stillschweigend
    X-Boost aus. Ebenso waeren 230 V / 50 Hz gesetzt worden, auch bei einem
    Geraet, das auf 60 Hz stand.

    Das ist die schlimmste Sorte Fehler in diesem Modul: Der Aufrufer bat um
    genau ein Feld, drei weitere aenderten sich ungefragt mit, und EcoFlow
    quittierte mit Erfolg. Deshalb wird jetzt lieber abgebrochen. Der Aufrufer
    (app.py) besorgt den Stand vorher per REST; kommt auch der nicht, ist eine
    lesbare Meldung allemal besser als ein stiller Eingriff.
    """
    fehlend = [
        feld
        for feld in ("ac_output_enabled", "xboost_enabled", "ac_output_voltage",
                     "ac_output_freq_hz")
        if current.get(feld) is None
    ]
    if fehlend:
        raise CommandError(
            "Zustand des AC-Ausgangs noch nicht bekannt ("
            + ", ".join(fehlend)
            + ") – ein paar Sekunden warten und noch einmal versuchen. "
            "Ohne ihn liesse sich der Befehl nur mit geratenen Werten senden, "
            "und das wuerde X-Boost, Spannung oder Frequenz mitverstellen."
        )
    freq_hz = current["ac_output_freq_hz"]
    params = {
        "enabled": int(current["ac_output_enabled"]),
        "xboost": int(current["xboost_enabled"]),
        "out_voltage": int(current["ac_output_voltage"]),
        "out_freq": 2 if int(freq_hz) == 60 else 1,
    }
    params.update(overrides)
    return params


def _watth_config(current: dict, **overrides) -> dict:
    """Vollstaendiges watthConfig-Param-Set bauen (isConfig, bpPowerSoc).

    Die Backup-Reserve ist zweiteilig: ein Schalter (`isConfig`) und ein
    Prozentwert (`bpPowerSoc`). In der EcoFlow-App laesst sich der Wert nur
    einstellen, wenn der Schalter an ist.

    Bis 14.08.2026 schickte FlowBridge beim Setzen des Werts fest
    `isConfig: 1` mit - wer nur den Prozentwert aenderte, schaltete die
    Reserve damit ungefragt EIN. Seit es einen eigenen Schalter gibt, bleibt
    der jeweils andere Teil stehen: Ein Befehl aendert genau das, wonach
    gefragt wurde.

    Fehlt der Schalterzustand noch (z.B. direkt nach dem Start, bevor der
    erste Push kam), gilt 1 - das entspricht dem bisherigen Verhalten und
    ist die harmlosere Annahme: Ein gesetzter Prozentwert soll wirken.

    Wichtig: Wie bei acOutCfg immer BEIDE Felder mitschicken. EcoFlow
    quittiert Teilmengen mit "Success" und verwirft sie stillschweigend.
    """
    params = {
        "isConfig": int(current.get("backup_reserve_enabled", 1)),
        "bpPowerSoc": int(current.get("backup_reserve_percent", 0)),
    }
    params.update(overrides)
    return params


async def apply_command(
    client: EcoFlowClient, sn: str, property_name: str, raw_value: str, current: dict | None = None
) -> dict:
    """Cmnd-Wert auf ein River-2(-Pro)-Geraet anwenden. Gibt die EcoFlow-Antwortdaten zurueck.

    `current` ist der zuletzt bekannte normalisierte Geraetestatus (siehe
    device.normalize_quota) - noetig fuer acOutCfg, das nur als vollstaendiges
    Param-Set wirkt (s. _ac_out_cfg).

    Wirft CommandError bei ungueltiger Eingabe oder unbekanntem property_name –
    der Aufrufer (app.py / mqtt_bridge cmnd-Handler) faengt das und loggt/meldet es,
    statt den Prozess crashen zu lassen: Ein falscher Wert auf einem Topic darf
    die Bruecke fuer alle anderen Geraete nicht mitreissen.
    """
    current = current or {}

    if property_name == "car_output_enabled":
        return await client.set_quota(
            sn, MODULE_MPPT, "mpptCar", {"enabled": _parse_bool(raw_value)}
        )

    if property_name == "ac_output_enabled":
        return await client.set_quota(
            sn, MODULE_MPPT, "acOutCfg", _ac_out_cfg(current, enabled=_parse_bool(raw_value))
        )

    if property_name == "xboost_enabled":
        return await client.set_quota(
            sn, MODULE_MPPT, "acOutCfg", _ac_out_cfg(current, xboost=_parse_bool(raw_value))
        )

    if property_name == "ac_charging_enabled":
        # UNDOKUMENTIERT fuer das River 2 Pro, aber verifiziert (12.08.2026):
        # chgPauseFlag 1 -> Ladung faellt binnen Sekunden auf 0 W, 0 -> kehrt
        # zurueck. Die Geraetedoku fuehrt das nur fuer Delta 2 / Delta 2 Max.
        # Laut dortiger Beschreibung wird die Pause NICHT dauerhaft gespeichert
        # und faellt beim Aus- und Einstecken des Netzkabels wieder weg.
        #
        # acChgCfg braucht beide Parameter zusammen (wie acOutCfg) - deshalb
        # die zuletzt gesetzte Ladeleistung mitschicken. Ist keine bekannt
        # (z.B. nach Neustart), wird das Minimum verwendet, damit hier nicht
        # unbemerkt hochgeregelt wird.
        watts = int(current.get("charge_power_watts_set") or CHARGE_WATTS_MIN)
        return await client.set_quota(
            sn,
            MODULE_MPPT,
            "acChgCfg",
            {"chgWatts": watts, "chgPauseFlag": 0 if _parse_bool(raw_value) else 1},
        )

    if property_name == "charge_power_watts":
        # UNDOKUMENTIERT, aber am echten River 2 Pro verifiziert (12.08.2026):
        # 700 W gesetzt -> AC-Eingang 709 W, 100 W gesetzt -> 89 W. Steht NICHT
        # in der Dev-Portal-Doku; Payload-Form stammt aus der EcoFlow-App
        # (moduleType 5 / acChgCfg). Die Umstellung braucht 20-50 s, bis sie
        # sich im gemessenen Eingang zeigt.
        #
        # Eine laufende Pause bleibt erhalten: acChgCfg braucht beide Parameter,
        # und blind chgPauseFlag 0 mitzuschicken wuerde die Ladung stillschweigend
        # wieder anwerfen, nur weil jemand die Leistung verstellt.
        try:
            watts = int(raw_value.strip())
        except ValueError as exc:
            raise CommandError(f"Ladeleistung erwartet eine Ganzzahl, bekam '{raw_value}'") from exc
        if watts not in CHARGE_WATTS_STEPS:
            raise CommandError(
                f"Ungueltige Ladeleistung {watts} W - erlaubt sind "
                f"{CHARGE_WATTS_MIN}-{CHARGE_WATTS_STEPS[-2]} W in "
                f"{CHARGE_WATTS_STEP}-W-Schritten sowie {CHARGE_WATTS_MAX} W"
            )
        # False nur bei ausdruecklich bekannter Pause - unbekannt (None) heisst
        # laden, sonst wuerde ein frischer Start ungewollt pausieren.
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

    if property_name in NUR_LESBAR:
        # Ausdruecklich statt stillschweigend: Ueber MQTT (EisBaer, Home
        # Assistant) kaeme sonst gar keine Rueckmeldung, und der Befehl
        # verschwaende spurlos - genau der Zustand, der uns hier Stunden
        # gekostet hat.
        raise CommandError(
            f"'{property_name}' laesst sich beim River 2 (Pro) nicht setzen - "
            "das Geraet nimmt watthConfig ueber die offene API nicht an "
            "(gemessen 14.08.2026). Lesen funktioniert, Schalten nur in der "
            "EcoFlow-App."
        )

    raise CommandError(f"Unbekanntes cmnd-Property '{property_name}' fuer River 2 (Pro)")

"""
Topic-Export: generische Liste und EisBaer-Import-Dateien.

Zweck: Wer FlowBridge an eine Visualisierung haengt, tippt sonst dutzende
Topics von Hand ab. Der Export nimmt genau das ab - und traegt gleich die
Typen und Schaltwerte ein, die man sonst raten muesste.

Zwei Formate:

1. GENERISCH - eine CSV mit Topic, Richtung, Typ, Beispielwert. Fuer jeden
   MQTT-Client brauchbar, auch zum blossen Nachschlagen.

2. EISBAER - zwei Dateien nach dem Format des Kanal- bzw. Payloadeditors.
   WICHTIG: erst das XML importieren, dann die CSV. Die CSV verweist ueber
   Spalte 11 auf ProfileIds, die zum Importzeitpunkt existieren muessen.

Beides gegen echte EisBaer-Exporte abgeglichen (EMU Professional, Tasmota),
nicht nur gegen Prosa.

DER PUNKT, AN DEM ES SONST STILL SCHEITERT
------------------------------------------
EisBaer sendet fuer einen Boolean-Kanal ohne gesetzten TrueString woertlich
"True"/"False". FlowBridge nimmt das inzwischen zwar an (_BOOL_VALUES in
commands_river2.py kennt true/false/1/0/an/aus), aber der Export verlaesst
sich NICHT darauf: Was der Kanal senden soll, gehoert in den Kanal und nicht
in die Nachsicht der Gegenstelle. Wird das Einlesen dort je enger gefasst,
taten sonst alle exportierten Schalter stillschweigend nichts - auf dem
MQTT-Weg gibt es keinen Rueckkanal fuer Fehlermeldungen.

Deshalb tragen alle Befehlskanaele An=on/Aus=off ausdruecklich in Spalte
12/13 (so macht es auch der echte Tasmota-Export mit ON/OFF).

Ebenso `1`/`0`: EcoFlow-Flags kommen als 1 und 0 auf den Broker. Diese beiden
fallen durch alle Erkennungsstufen von EisBaer durch (bool.TryParse("1") ist
False, und "1" steht in keiner Hardcoded-Liste). Ohne An=1/Aus=0 waere so ein
Kanal dauerhaft "Aus".
"""
from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field

# Statusfelder, die EcoFlow als 1/0 liefert, aber Schalter sind. Sie brauchen
# An=1/Aus=0, sonst zeigt EisBaer sie dauerhaft als "Aus".
_FLAG_FELDER = frozenset({
    "ac_output_enabled",
    "xboost_enabled",
    "car_output_enabled",
    "backup_reserve_enabled",
})

# Befehle, die on/off erwarten (der Rest sind Zahlen).
_SCHALT_BEFEHLE = frozenset({
    "ac_output_enabled",
    "xboost_enabled",
    "car_output_enabled",
    "ac_charging_enabled",
    "backup_reserve_enabled",
})

_ZAHL_BEFEHLE = (
    "charge_power_watts",
    "charge_limit_percent",
    "discharge_limit_percent",
    "backup_reserve_percent",
)

def _attr(wert: str) -> str:
    """Attributwert escapen. Bewusst eigenhaendig statt quoteattr, weil der
    Type-Schnipsel bereits fertig escapt ist und sonst ein zweites Mal
    durchliefe."""
    return (
        wert.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# Modul-Topics, fuer die ein JSON-Profil entsteht.
_MODULE = ("pd", "bms", "ems", "inv", "mppt")


# Einheit aus dem Feldnamen. Steht in keiner EcoFlow-Antwort - aber ohne sie
# raet der Leser einer generischen Liste, ob 105 nun Watt oder Prozent sind.
_EINHEITEN = (
    ("_percent", "%"),
    ("_watts_in", "W"), ("_watts_out", "W"), ("_watts", "W"), ("watts_out", "W"),
    ("_voltage", "V"),
    ("_freq_hz", "Hz"),
    ("_remain_min", "min"), ("_min", "min"),
    ("_temp_c", "°C"),
)


def _einheit(feld: str) -> str:
    for endung, einheit in _EINHEITEN:
        if feld.endswith(endung):
            return einheit
    return ""


@dataclass
class Kanal:
    """Eine Zeile der Kanaleditor-CSV."""
    name: str
    topic: str
    datatype: str           # EisBaer-CodingType
    publish: bool = False
    profile_id: str = ""
    an: str = "True"
    aus: str = "False"
    hinweis: str = ""       # nur fuer den generischen Export
    beispiel: str = ""      # nur fuer den generischen Export
    # Neutraler Typname fuer den generischen Export: "INT64_STRING" ist
    # EisBaer-Jargon und sagt einem Node-RED- oder MQTT-Explorer-Nutzer nichts.
    art: str = "text"
    einheit: str = ""


@dataclass
class ProfilKnoten:
    name: str
    typ: str                       # System.Int64 / ... / System.Single (Container)
    ist_container: bool = False
    kinder: list["ProfilKnoten"] = field(default_factory=list)


def _typ_aus_wert(wert) -> str:
    """Beobachten statt raten - genau wie EisBaers eigener Payload-Wizard.

    Kein Ratespiel bei signed/unsigned: Int64 ist der Obertyp und deckt beide
    Faelle ab. Zwischen Ganzzahl und Dezimalzahl gibt es dagegen KEINEN
    gemeinsamen Obertyp, deshalb wird dort nicht verbreitert.
    """
    if isinstance(wert, bool):
        return "System.Boolean"
    if isinstance(wert, int):
        return "System.Int64"
    if isinstance(wert, float):
        return "System.Double"
    return "System.String"


def _datatype_flach(feld: str, wert) -> tuple[str, str, str, str]:
    """-> (CodingType, An, Aus, neutrale Art) fuer einen Einzelwert-Kanal."""
    if feld in _FLAG_FELDER:
        # 1/0 faellt durch alle Erkennungsstufen - An/Aus sind hier Pflicht.
        return "BOOLEAN_STRING", "1", "0", "boolean"
    if isinstance(wert, bool):
        # true/false erkennt EisBaer ueber bool.TryParse selbst.
        return "BOOLEAN_STRING", "True", "False", "boolean"
    if isinstance(wert, int):
        return "INT64_STRING", "True", "False", "ganzzahl"
    if isinstance(wert, float):
        return "DOUBLE_STRING", "True", "False", "dezimalzahl"
    # Es gibt KEIN DATETIME_STRING - ein flacher Zeitstempel wird STRING.
    return "STRING", "True", "False", "text"


def _profil_id(modell: str | None, teil: str) -> str:
    """Shape-basiert, nicht geraetebasiert: zwei River 2 Pro teilen sich ein
    Profil. Das ist genau so gedacht - die Struktur haengt am Modell, nicht
    an der Seriennummer."""
    basis = (modell or "GERAET").upper().replace(" ", "-")
    return f"FLOWBRIDGE-{basis}-{teil.upper()}"


def baue_kanaele(
    sn: str,
    geraetename: str,
    status: dict,
    base_topic: str,
    modell: str | None,
    steuerbar: bool,
    mit_modulen: bool = False,
    nur_lesbar: tuple[str, ...] = (),
) -> list[Kanal]:
    """Alle Kanaele eines Geraets - Verfuegbarkeit, JSON, Einzelwerte, Befehle.

    `mit_modulen` nimmt zusaetzlich die fuenf Modul-Topics samt ihrer Profile
    auf. Standard ist AUS: die Rohwerte der Module sind zum Nachschauen da,
    im taeglichen Betrieb arbeitet man mit den Einzelwerten unter status/.
    Eingeschaltet waechst das Profil-XML um rund 50 Knoten.
    """
    kanaele: list[Kanal] = []
    name = geraetename or sn

    # --- Verfuegbarkeit. online/offline erkennt EisBaer zwar hardcodiert,
    #     echte Exporte tragen es trotzdem ein - dann steht es auch im
    #     Kanaleditor sichtbar da.
    kanaele.append(Kanal(
        "FlowBridge Dienst", f"{base_topic}/bridge/available",
        "BOOLEAN_STRING", an="online", aus="offline", art="boolean",
        hinweis="FlowBridge selbst (Last-Will)",
    ))
    kanaele.append(Kanal(
        "FlowBridge EcoFlow-Cloud", f"{base_topic}/bridge/ecoflow",
        "BOOLEAN_STRING", an="online", aus="offline", art="boolean",
        hinweis="Verbindung zur EcoFlow-Cloud",
    ))
    kanaele.append(Kanal(
        f"{name} erreichbar", f"{base_topic}/{sn}/available",
        "BOOLEAN_STRING", an="online", aus="offline", art="boolean",
        hinweis="Geraet selbst",
    ))

    # --- JSON-Topics mit Profilverweis
    kanaele.append(Kanal(
        f"{name} Zustand", f"{base_topic}/{sn}/state", "JSON",
        profile_id=_profil_id(modell, "state"), art="json",
        hinweis="alle Werte als JSON",
    ))
    module = (status.get("_modules") or {}) if mit_modulen else {}
    for modul in _MODULE:
        if modul.upper() not in {m.upper() for m in module}:
            continue
        kanaele.append(Kanal(
            f"{name} {modul.upper()}", f"{base_topic}/{sn}/modules/{modul}", "JSON",
            profile_id=_profil_id(modell, modul), art="json",
            hinweis="Rohwerte des Moduls",
        ))

    # --- Einzelwerte
    for feld, wert in sorted(status.items()):
        if feld.startswith("_") or feld in ("sn", "online") or wert is None:
            continue
        datatype, an, aus, art = _datatype_flach(feld, wert)
        kanaele.append(Kanal(
            f"{name} {feld}", f"{base_topic}/{sn}/status/{feld}",
            datatype, an=an, aus=aus, beispiel=str(wert),
            art=art, einheit=_einheit(feld),
        ))

    # --- Befehle. Publish=True, weil ein Pfadsegment "cmnd" ist.
    #
    # `nur_lesbar` bleibt hier aussen vor: Ein Kanal im EisBaer, auf den man
    # schreiben kann und der nichts bewirkt, ist schlimmer als ein fehlender -
    # in der Visualisierung sieht man ihm nicht an, dass er ins Leere geht.
    # Der Lese-Kanal unter status/ entsteht weiter oben und bleibt.
    if steuerbar:
        for prop in sorted(_SCHALT_BEFEHLE - set(nur_lesbar)):
            kanaele.append(Kanal(
                f"{name} {prop} setzen", f"{base_topic}/{sn}/cmnd/{prop}",
                "BOOLEAN_STRING", publish=True, an="on", aus="off", art="boolean",
                hinweis="on oder off (auch true/1/an werden angenommen)",
            ))
        for prop in _ZAHL_BEFEHLE:
            if prop in nur_lesbar:
                continue
            kanaele.append(Kanal(
                f"{name} {prop} setzen", f"{base_topic}/{sn}/cmnd/{prop}",
                "INT64_STRING", publish=True, art="ganzzahl",
                einheit=_einheit(prop),
            ))
    return kanaele


def baue_profile(
    status: dict, modell: str | None, mit_modulen: bool = False
) -> list[tuple[str, ProfilKnoten]]:
    """-> [(ProfileId, Wurzelknoten), ...] fuer die JSON-Topics."""
    profile: list[tuple[str, ProfilKnoten]] = []

    def aus_dict(name: str, daten: dict) -> ProfilKnoten:
        knoten = ProfilKnoten(name, "System.Single", ist_container=True)
        for schluessel, wert in daten.items():
            if isinstance(wert, dict):
                knoten.kinder.append(aus_dict(schluessel, wert))
            else:
                knoten.kinder.append(ProfilKnoten(schluessel, _typ_aus_wert(wert)))
        return knoten

    ohne_intern = {k: v for k, v in status.items() if not k.startswith("_") and v is not None}
    profile.append((_profil_id(modell, "state"), aus_dict("state", ohne_intern)))

    if mit_modulen:
        for modul, felder in (status.get("_modules") or {}).items():
            profile.append((_profil_id(modell, modul), aus_dict(modul.lower(), felder)))
    return profile


# ------------------------------------------------------------------ Ausgabe
def eisbaer_csv(kanaele: list[Kanal]) -> str:
    """Kanaleditor-CSV: UTF-8, Semikolon, KEIN Kopfzeile, 13 Spalten, CRLF."""
    puffer = io.StringIO()
    schreiber = csv.writer(puffer, delimiter=";", lineterminator="\r\n",
                           quoting=csv.QUOTE_MINIMAL)
    for nr, k in enumerate(kanaele, start=1):
        schreiber.writerow([
            nr,                 # 1 laufende Nummer
            k.name,             # 2 Name
            k.topic,            # 3 Topic
            k.datatype,         # 4 Datatype
            1,                  # 5 QOS (mindestens einmal)
            1,                  # 6 Faktor - Basis-Export ist roh
            "False",            # 7 Retain
            "dummy",            # 8 BaseTopic
            "True" if k.publish else "False",  # 9 Publish
            "True",             # 10 Subscribe - immer
            k.profile_id,       # 11 ProfileId (Join-Schluessel zum XML)
            k.an,               # 12 An / TrueString
            k.aus,              # 13 Aus / FalseString
        ])
    return puffer.getvalue()


def eisbaer_xml(profile: list[tuple[str, ProfilKnoten]]) -> str:
    """Payloadeditor-XML.

    17 Attribute in fester Reihenfolge, abgeglichen gegen echte Exporte
    (EMU Professional). Neuere EisBaer-Staende kennen zusaetzlich
    `AlternativeName`; ein Import ohne das Attribut wird toleriert, deshalb
    bleibt es hier weg - so passt die Datei auch zu aelteren Staenden.

    IDs sind ueber die GESAMTE Datei eindeutig, nicht je Baum.
    """
    zeilen = ['<?xml version="1.0" encoding="utf-8"?>', "<DeviceProfileList>"]
    naechste_id = [1]

    def schreibe(knoten: ProfilKnoten, profil: str, eltern_id: int) -> None:
        eigene = naechste_id[0]
        naechste_id[0] += 1
        # Type ist ein escapter XML-Schnipsel, KEIN Typname. Container tragen
        # System.Single als internen Fuellwert - die Oberflaeche zeigt bei
        # ihnen ohnehin keinen Datentyp an.
        #
        # Bewusst von Hand escapt und NICHT ueber quoteattr: das escapt den
        # fertigen Schnipsel ein zweites Mal ("&amp;lt;"), und genau dieses
        # Doppel-Escaping ist hier schon einmal passiert. Die Schreibweise
        # entspricht exakt den echten EisBaer-Exporten.
        surrogat = f"&lt;TypeSurrogate Type=&quot;{knoten.typ}&quot; /&gt;"
        attribute = [
            ("Name", knoten.name),
            ("Id", str(eigene)),
            ("ParentId", str(eltern_id)),
            ("ProfileId", profil),
            ("IsContainer", "True" if knoten.ist_container else "False"),
            ("Type", surrogat),
            ("Direction", "Output"),          # "Vom Geraet"
            ("NumberOfElements", "1"),
            ("IsArray", "False"),
            ("UseAsTrigger", "False"),
            ("AutoTrigger", "False"),
            ("DiscardAfterTrigger", "False"),
            ("LoraPort", "1" if eltern_id == -1 else "0"),
            ("Factor", "1"),
            ("OutputDefaultValues", "False"),
            ("TrueValue", ""),
            ("FalseValue", ""),
        ]
        # Der Typ ist bereits escapt (siehe oben), alle anderen Werte nicht.
        offen = " ".join(
            f'{name}="{wert if name == "Type" else _attr(wert)}"'
            for name, wert in attribute
        )
        zeilen.append(f"  <DeviceProfile {offen}>")
        zeilen.append(
            '    <DataPointValue xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true" />'
        )
        zeilen.append("  </DeviceProfile>")
        for kind in knoten.kinder:
            schreibe(kind, profil, eigene)

    for profil, wurzel in profile:
        schreibe(wurzel, profil, -1)
    zeilen.append("</DeviceProfileList>")
    return "\r\n".join(zeilen) + "\r\n"




def generische_csv(kanaele: list[Kanal]) -> str:
    """Schlichte Liste zum Nachschlagen - fuer JEDEN MQTT-Client.

    Bewusst ohne EisBaer-Vokabular: "INT64_STRING" sagt einem Node-RED- oder
    MQTT-Explorer-Nutzer nichts, "ganzzahl" schon.

    Die Richtung ist hier ehrlich SCHREIBEN statt "lesen+schreiben": auf
    cmnd/-Topics veroeffentlicht FlowBridge nichts. Das Subscribe=True der
    EisBaer-CSV ist eine Konvention jenes Editors - wer diese Liste liest und
    dort Werte erwartet, wartet vergeblich.

    An/Aus stehen nur bei Wahrheitswerten; bei Zahlen waeren sie Rauschen.
    """
    puffer = io.StringIO()
    schreiber = csv.writer(puffer, lineterminator="\r\n")
    schreiber.writerow(
        ["Topic", "Richtung", "Typ", "Einheit", "An", "Aus", "Beispielwert", "Hinweis"]
    )
    for k in kanaele:
        boolean = k.art == "boolean"
        schreiber.writerow([
            k.topic,
            "schreiben" if k.publish else "lesen",
            k.art,
            k.einheit,
            k.an if boolean else "",
            k.aus if boolean else "",
            k.beispiel,
            k.hinweis,
        ])
    return puffer.getvalue()


# Liegt dem ZIP bei. Die Importreihenfolge steckt schon in den Dateinamen,
# aber ein Archiv verleitet dazu, einfach alles auf einmal hineinzuziehen.
_LIESMICH = [
    "FlowBridge - EisBaer-Import",
    "===========================",
    "",
    "REIHENFOLGE EINHALTEN:",
    "  1. 1-payloadeditor.xml  im Payload-Profil-Editor importieren",
    "  2. 2-kanaleditor.csv    im Kanal-Editor importieren",
    "",
    "Die CSV verweist ueber Spalte 11 auf ProfileIds aus dem XML. In der",
    "falschen Reihenfolge importiert haengen die JSON-Kanaele ohne Profil",
    "in der Luft.",
    "",
    "Bereits richtig eingetragen:",
    "",
    "  - Befehlskanaele (cmnd/) mit An=on / Aus=off. Ohne diese Werte sendet",
    "    EisBaer woertlich True/False. FlowBridge nimmt das zwar an, aber der",
    "    Export verlaesst sich nicht darauf - was ein Kanal senden soll,",
    "    gehoert in den Kanal.",
    "",
    "  - EcoFlow-Flags (ac_output_enabled, xboost_enabled, ...) mit An=1 /",
    "    Aus=0. Diese beiden Werte fallen durch alle Erkennungsstufen von",
    "    EisBaer; ohne die Angabe stuende der Kanal dauerhaft auf 'Aus'.",
    "",
    "  - Verfuegbarkeits-Topics mit An=online / Aus=offline.",
    "",
    "Faktor ueberall 1: der Export ist roh und rechnet nichts um.",
]


def eisbaer_zip(kanaele: list[Kanal], profile: list[tuple[str, ProfilKnoten]]) -> bytes:
    """Beide EisBaer-Dateien in einem Archiv, mit der Reihenfolge im Namen."""
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("1-payloadeditor.xml", eisbaer_xml(profile))
        z.writestr("2-kanaleditor.csv", eisbaer_csv(kanaele))
        z.writestr("LIESMICH.txt", "\r\n".join(_LIESMICH) + "\r\n")
    return puffer.getvalue()

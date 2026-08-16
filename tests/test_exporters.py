"""
Topic-Export. Geprueft wird vor allem das, was beim Import STILL scheitert -
falsche Schaltwerte fallen erst auf, wenn im EisBaer ein Schalter nichts tut.

Abgeglichen gegen echte EisBaer-Exporte (EMU Professional, Tasmota) statt
gegen Prosa.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import exporters  # noqa: E402

SN = "R621TESTSN000000"
STATUS = {
    "sn": SN,
    "online": True,
    "soc_percent": 35,
    "ac_watts_in": 105,
    "ac_output_enabled": 1,       # EcoFlow-Flag: 1/0
    "xboost_enabled": 1,
    "ac_charging_enabled_set": True,   # echter Boolean: true/false
    "ac_output_voltage": 230,
    "last_update": "2026-08-13T04:00:00+00:00",
    "_modules": {
        "PD": {"soc": 35, "wattsOutSum": 0},
        "MPPT": {"cfgAcEnabled": 1, "inWatts": 0},
    },
}


def _kanaele(steuerbar=True, mit_modulen=True, nur_lesbar=()):
    return exporters.baue_kanaele(
        SN, "River 2 Pro Dirk", STATUS, "flowbridge", "RIVER 2 Pro",
        steuerbar, mit_modulen, nur_lesbar=nur_lesbar,
    )


# ------------------------------------------- Nur lesbare Felder (14.08.2026)
def test_nur_lesbares_feld_bekommt_keinen_befehlskanal():
    """Am Geraet gemessen: watthConfig wird nicht angenommen.

    Ein beschreibbarer Kanal im EisBaer waere schlimmer als keiner - in der
    Visualisierung sieht man ihm nicht an, dass er ins Leere geht. Der
    LESE-Kanal unter status/ muss dagegen bleiben.
    """
    nur_lesbar = ("backup_reserve_enabled", "backup_reserve_percent")
    # Der Lese-Kanal entsteht aus dem gemeldeten Status, also muss das Feld
    # hier auch drinstehen - sonst prueft der Test nur die halbe Zusage.
    status = {**STATUS, "backup_reserve_enabled": 1, "backup_reserve_percent": 80}
    kanaele = exporters.baue_kanaele(
        SN, "River 2 Pro Dirk", status, "flowbridge", "RIVER 2 Pro",
        True, True, nur_lesbar=nur_lesbar,
    )
    topics = [k.topic for k in kanaele]

    assert not [t for t in topics if "/cmnd/backup_reserve" in t]
    assert [t for t in topics if t.endswith("/status/backup_reserve_enabled")]
    assert [t for t in topics if t.endswith("/status/backup_reserve_percent")]


def test_ohne_einschraenkung_bleiben_die_befehlskanaele():
    """Gegenprobe - sonst koennte die Filterung auch alles wegnehmen."""
    topics = [k.topic for k in _kanaele()]
    assert [t for t in topics if "/cmnd/backup_reserve_enabled" in t]
    assert [t for t in topics if "/cmnd/backup_reserve_percent" in t]


def _zeilen(kanaele):
    return [z for z in exporters.eisbaer_csv(kanaele).split("\r\n") if z]


def _spalten(zeile):
    return zeile.split(";")


def _finde(kanaele, topic):
    return next(k for k in kanaele if k.topic == topic)


# ------------------------------------------------------------------ Format
def test_csv_hat_dreizehn_spalten_und_keine_kopfzeile():
    zeilen = _zeilen(_kanaele())
    assert all(len(_spalten(z)) == 13 for z in zeilen)
    assert not zeilen[0].lower().startswith("nr;")


def test_csv_nutzt_crlf():
    assert exporters.eisbaer_csv(_kanaele()).endswith("\r\n")


def test_basetopic_und_qos_wie_im_echten_export():
    sp = _spalten(_zeilen(_kanaele())[0])
    assert sp[4] == "1"        # QOS
    assert sp[5] == "1"        # Faktor - Basis-Export ist roh
    assert sp[7] == "dummy"    # BaseTopic


# -------------------------------------------------------- Publish/Subscribe
def test_subscribe_ist_immer_wahr():
    assert all(_spalten(z)[9] == "True" for z in _zeilen(_kanaele()))


def test_publish_nur_bei_cmnd_segment():
    for zeile in _zeilen(_kanaele()):
        sp = _spalten(zeile)
        erwartet = "True" if "/cmnd/" in sp[2] else "False"
        assert sp[8] == erwartet, sp[2]


# ------------------------------------------------------- die stillen Fallen
def test_befehlsschalter_tragen_on_und_off():
    """Ohne gesetzten TrueString sendet EisBaer woertlich "True"/"False".
    FlowBridge nimmt das inzwischen an - der Export verlaesst sich aber
    NICHT darauf: was ein Kanal senden soll, gehoert in den Kanal. Wuerde
    das Einlesen je enger gefasst, taeten sonst alle exportierten Schalter
    stillschweigend nichts."""
    k = _finde(_kanaele(), f"flowbridge/{SN}/cmnd/ac_output_enabled")
    assert (k.an, k.aus) == ("on", "off")
    assert k.datatype == "BOOLEAN_STRING"


def test_ecoflow_flags_tragen_eins_und_null():
    """1/0 faellt durch alle drei Erkennungsstufen von EisBaer - ohne An/Aus
    stuende der Kanal dauerhaft auf "Aus"."""
    k = _finde(_kanaele(), f"flowbridge/{SN}/status/ac_output_enabled")
    assert (k.an, k.aus) == ("1", "0")
    assert k.datatype == "BOOLEAN_STRING"


def test_echte_booleans_brauchen_keine_schaltwerte():
    """true/false erkennt EisBaer selbst ueber bool.TryParse."""
    k = _finde(_kanaele(), f"flowbridge/{SN}/status/ac_charging_enabled_set")
    assert (k.an, k.aus) == ("True", "False")


def test_verfuegbarkeit_traegt_online_offline():
    k = _finde(_kanaele(), "flowbridge/bridge/available")
    assert (k.an, k.aus) == ("online", "offline")


def test_zeitstempel_wird_string_nicht_datetime():
    """Es gibt keinen CodingType DATETIME_STRING - ein flacher Zeitstempel
    muss STRING werden."""
    assert _finde(_kanaele(), f"flowbridge/{SN}/status/last_update").datatype == "STRING"


def test_ganzzahl_wird_int64():
    assert _finde(_kanaele(), f"flowbridge/{SN}/status/soc_percent").datatype == "INT64_STRING"


# --------------------------------------------------------------- Join + XML
def test_jede_profil_id_der_csv_existiert_im_xml():
    """Der Join-Schluessel ist heilig: Spalte 11 muss im XML vorkommen,
    sonst haengt der Kanal beim Import in der Luft."""
    kanaele = _kanaele()
    xml = exporters.eisbaer_xml(exporters.baue_profile(STATUS, "RIVER 2 Pro", True))
    for k in kanaele:
        if k.profile_id:
            assert f'ProfileId="{k.profile_id}"' in xml, k.profile_id


def test_json_kanaele_haben_eine_profil_id_und_andere_nicht():
    for k in _kanaele():
        if k.datatype == "JSON":
            assert k.profile_id
        else:
            assert not k.profile_id


def test_xml_ids_sind_ueber_die_ganze_datei_eindeutig():
    xml = exporters.eisbaer_xml(exporters.baue_profile(STATUS, "RIVER 2 Pro", True))
    ids = [z.split('Id="')[1].split('"')[0] for z in xml.splitlines() if "<DeviceProfile " in z]
    assert len(ids) == len(set(ids))


def test_container_tragen_single_als_fuellwert():
    """Container haben im Profileditor keinen Datentyp - System.Single ist
    ein interner Fuellwert, den die Oberflaeche nie anzeigt."""
    xml = exporters.eisbaer_xml(exporters.baue_profile(STATUS, "RIVER 2 Pro", True))
    for zeile in xml.splitlines():
        if 'IsContainer="True"' in zeile:
            assert "System.Single" in zeile


def test_typ_ist_escaptes_surrogat_und_nicht_doppelt_escapt():
    """Doppel-Escaping ist ein realer, schon einmal aufgetretener Fehler."""
    xml = exporters.eisbaer_xml(exporters.baue_profile(STATUS, "RIVER 2 Pro", True))
    assert "&lt;TypeSurrogate Type=&quot;System.Int64&quot; /&gt;" in xml
    assert "&amp;lt;" not in xml


def test_wurzeln_haben_parentid_minus_eins_und_loraport_eins():
    xml = exporters.eisbaer_xml(exporters.baue_profile(STATUS, "RIVER 2 Pro", True))
    wurzeln = [z for z in xml.splitlines() if 'ParentId="-1"' in z]
    assert wurzeln
    assert all('LoraPort="1"' in z for z in wurzeln)
    assert all('LoraPort="0"' in z for z in xml.splitlines()
               if "<DeviceProfile " in z and 'ParentId="-1"' not in z)


def test_jeder_knoten_hat_ein_datapointvalue():
    xml = exporters.eisbaer_xml(exporters.baue_profile(STATUS, "RIVER 2 Pro", True))
    assert xml.count("<DeviceProfile ") == xml.count("<DataPointValue")


def test_profile_sind_shape_basiert_nicht_geraetebasiert():
    """Zwei River 2 Pro sollen sich ein Profil teilen - die Struktur haengt
    am Modell, nicht an der Seriennummer."""
    a = exporters.baue_profile(STATUS, "RIVER 2 Pro", True)
    b = exporters.baue_profile({**STATUS, "sn": "R621ANDERE"}, "RIVER 2 Pro", True)
    assert [p for p, _ in a] == [p for p, _ in b]
    assert SN not in a[0][0]


# ------------------------------------------------------------- Steuerbarkeit
def test_ohne_steuerbarkeit_keine_befehlskanaele():
    """Ein Schalter, der nichts bewirkt, waere schlimmer als keiner."""
    assert not any("/cmnd/" in k.topic for k in _kanaele(steuerbar=False))


# ---------------------------------------------------------------- generisch
def test_generische_csv_hat_kopfzeile():
    text = exporters.generische_csv(_kanaele())
    assert text.splitlines()[0].startswith("Topic,")


# ----------------------------------------------------------- Modul-Variante
def test_ohne_module_keine_modul_topics():
    """Standard: die Rohwerte der Module sind zum Nachschauen da, im
    Alltag arbeitet man mit den Einzelwerten unter status/."""
    topics = [k.topic for k in _kanaele(mit_modulen=False)]
    assert not any("/modules/" in t for t in topics)
    assert f"flowbridge/{SN}/state" in topics       # state bleibt


def test_mit_modulen_kommen_sie_dazu():
    topics = [k.topic for k in _kanaele(mit_modulen=True)]
    assert f"flowbridge/{SN}/modules/pd" in topics


def test_ohne_module_auch_keine_modul_profile():
    """Sonst stuenden im XML Profile, auf die keine CSV-Zeile verweist."""
    profile = exporters.baue_profile(STATUS, "RIVER 2 Pro", False)
    assert [p for p, _ in profile] == ["FLOWBRIDGE-RIVER-2-PRO-STATE"]


def test_join_stimmt_auch_ohne_module():
    kanaele = _kanaele(mit_modulen=False)
    xml = exporters.eisbaer_xml(exporters.baue_profile(STATUS, "RIVER 2 Pro", False))
    for k in kanaele:
        if k.profile_id:
            assert f'ProfileId="{k.profile_id}"' in xml


# ------------------------------------------------------------------- Archiv
def test_zip_enthaelt_beide_dateien_und_eine_anleitung():
    import zipfile
    from io import BytesIO
    rohdaten = exporters.eisbaer_zip(
        _kanaele(), exporters.baue_profile(STATUS, "RIVER 2 Pro", True)
    )
    with zipfile.ZipFile(BytesIO(rohdaten)) as z:
        assert set(z.namelist()) == {
            "1-payloadeditor.xml", "2-kanaleditor.csv", "LIESMICH.txt"
        }
        anleitung = z.read("LIESMICH.txt").decode("utf-8")
    # Die Reihenfolge steckt im Dateinamen UND in der Anleitung.
    assert "REIHENFOLGE" in anleitung


# --------------------------------------------------------- generische Liste
def test_generische_liste_nennt_cmnd_als_schreiben():
    """"lesen+schreiben" waere falsch: auf cmnd/ veroeffentlicht FlowBridge
    nichts. Wer dort Werte erwartet, wartet vergeblich."""
    for zeile in exporters.generische_csv(_kanaele()).splitlines():
        if "/cmnd/" in zeile:
            assert zeile.split(",")[1] == "schreiben"
        elif zeile.startswith("flowbridge/"):
            assert zeile.split(",")[1] == "lesen"


def test_generische_liste_nutzt_kein_eisbaer_vokabular():
    text = exporters.generische_csv(_kanaele())
    assert "INT64_STRING" not in text
    assert "BOOLEAN_STRING" not in text
    assert "ganzzahl" in text


def test_generische_liste_nennt_einheiten():
    zeilen = exporters.generische_csv(_kanaele()).splitlines()
    watt = next(z for z in zeilen if z.startswith(f"flowbridge/{SN}/status/ac_watts_in"))
    prozent = next(z for z in zeilen if z.startswith(f"flowbridge/{SN}/status/soc_percent"))
    assert watt.split(",")[3] == "W"
    assert prozent.split(",")[3] == "%"


def test_generische_liste_laesst_schaltwerte_bei_zahlen_leer():
    """Bei einem Zahlenkanal sind An/Aus bedeutungslos - sie stuenden in
    jeder zweiten Zeile als Rauschen."""
    zeile = next(z for z in exporters.generische_csv(_kanaele()).splitlines()
                 if z.startswith(f"flowbridge/{SN}/status/soc_percent"))
    sp = zeile.split(",")
    assert sp[4] == "" and sp[5] == ""

"""
Tests fuer das Feldinventar.

Zweck des Inventars: mitbekommen, wenn EcoFlow den Datenstrom aendert - etwa
nach einem Firmware-Update. Geprueft wird deshalb vor allem, dass ein NEUES
Feld als Ereignis auftaucht und ein weggefallenes an seinem alten "zuletzt"
erkennbar bleibt.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from inventar import MAX_BEISPIELE, Feldinventar  # noqa: E402

SN = "R621TESTSN000000"


@pytest.fixture
def inv(tmp_path):
    i = Feldinventar(tmp_path / "feldinventar.json")
    i.einschalten()
    return i


def test_ausgeschaltet_wird_nichts_erfasst(tmp_path):
    """Der Schalter muss wirklich schalten - sonst schriebe FlowBridge bei
    jedem Anwender ungefragt mit."""
    i = Feldinventar(tmp_path / "x.json")
    i.beobachte(SN, {"pd.soc": 27}, "push")
    assert i.zustand()["fields"] == 0


def test_felder_werden_gezaehlt(inv):
    inv.beobachte(SN, {"pd.soc": 27}, "push")
    inv.beobachte(SN, {"pd.soc": 28}, "push")
    daten = json.loads(inv.als_json({}))
    eintrag = daten["geraete"][SN]["felder"]["pd.soc"]
    assert eintrag["anzahl"] == 2
    assert eintrag["min"] == 27
    assert eintrag["max"] == 28


def test_quelle_wird_unterschieden(inv):
    """Push liefert nachweislich mehr Felder als quota/all (29 gegen 20,
    gemessen am 13.08.2026). Faellt eines kuenftig nur in einem der beiden
    Kanaele weg, waere das ohne diese Angabe unsichtbar."""
    inv.beobachte(SN, {"pd.soc": 27}, "push")
    inv.beobachte(SN, {"pd.soc": 27}, "rest")
    quellen = json.loads(inv.als_json({}))["geraete"][SN]["felder"]["pd.soc"]["quellen"]
    assert sorted(quellen) == ["push", "rest"]


def test_neues_feld_erzeugt_ein_ereignis(inv):
    """Der eigentliche Zweck: Ein Feld, das nach einem Firmware-Update
    auftaucht, soll ins Auge springen - ohne dass jemand suchen muss."""
    inv.beobachte(SN, {"pd.soc": 27}, "push")
    inv.beobachte(SN, {"pd.soc": 27, "bms_bmsStatus.cycles": 42}, "push",
                  rohnachricht='{"typeCode":"bmsStatus","params":{"cycles":42}}')

    ereignisse = json.loads(inv.als_json({}))["geraete"][SN]["ereignisse"]
    assert len(ereignisse) == 2  # erstes Feld + das neue
    letztes = ereignisse[-1]
    assert letztes["felder"] == ["bms_bmsStatus.cycles"]
    assert "cycles" in letztes["rohnachricht"]


def test_bekanntes_feld_erzeugt_kein_ereignis(inv):
    """Gegenprobe: Sonst waere die Ereignisliste im Sekundentakt voll und
    das eine interessante Ereignis darin nicht mehr zu finden."""
    for _ in range(5):
        inv.beobachte(SN, {"pd.soc": 27}, "push")
    assert len(json.loads(inv.als_json({}))["geraete"][SN]["ereignisse"]) == 1


def test_weggefallenes_feld_bleibt_mit_altem_zeitstempel_stehen(inv):
    """So wird ein VERSCHWUNDENES Feld sichtbar: Sein "zuletzt" altert,
    waehrend die anderen weiterlaufen."""
    inv.beobachte(SN, {"pd.soc": 27, "pd.altfeld": 1}, "push")
    alt = json.loads(inv.als_json({}))["geraete"][SN]["felder"]["pd.altfeld"]["zuletzt"]

    for _ in range(3):
        inv.beobachte(SN, {"pd.soc": 27}, "push")

    felder = json.loads(inv.als_json({}))["geraete"][SN]["felder"]
    assert felder["pd.altfeld"]["zuletzt"] == alt
    assert felder["pd.altfeld"]["anzahl"] == 1
    assert felder["pd.soc"]["anzahl"] == 4


def test_texte_landen_als_beispiele_und_sind_begrenzt(inv):
    """Bei einer Zahl sagt min/max mehr, bei Text genau umgekehrt - und die
    Liste darf nicht unbegrenzt wachsen."""
    for i in range(MAX_BEISPIELE + 5):
        inv.beobachte(SN, {"pd.version": f"v{i}"}, "push")
    eintrag = json.loads(inv.als_json({}))["geraete"][SN]["felder"]["pd.version"]
    assert len(eintrag["beispiele"]) == MAX_BEISPIELE
    assert "min" not in eintrag


def test_ueberlebt_einen_neustart(tmp_path):
    """Das Inventar soll ueber Wochen laufen - ein Container-Update darf es
    nicht auf null setzen."""
    pfad = tmp_path / "feldinventar.json"
    erste = Feldinventar(pfad)
    erste.einschalten()
    erste.beobachte(SN, {"pd.soc": 27}, "push")

    zweite = Feldinventar(pfad)
    zweite.einschalten()
    zweite.beobachte(SN, {"pd.soc": 29}, "push")

    eintrag = json.loads(zweite.als_json({}))["geraete"][SN]["felder"]["pd.soc"]
    assert eintrag["anzahl"] == 2
    assert eintrag["min"] == 27 and eintrag["max"] == 29


def test_kaputte_datei_verhindert_den_start_nicht(tmp_path):
    """Das Inventar ist Beiwerk. Eine unlesbare Datei darf FlowBridge nicht
    am Hochkommen hindern."""
    pfad = tmp_path / "kaputt.json"
    pfad.write_text("{das ist kein JSON", encoding="utf-8")
    i = Feldinventar(pfad)
    i.einschalten()
    i.beobachte(SN, {"pd.soc": 27}, "push")
    assert i.zustand()["fields"] == 1


def test_zuruecksetzen_leert_alles(inv):
    inv.beobachte(SN, {"pd.soc": 27}, "push")
    inv.zuruecksetzen()
    zustand = inv.zustand()
    assert zustand["fields"] == 0 and zustand["devices"] == 0


# ------------------------------------------------- Verdrahtung in app.py
def test_beide_kanaele_landen_im_inventar(monkeypatch):
    """Der eigentliche Anschlusspunkt.

    `_apply_quota_update` ist der gemeinsame Trichter fuer MQTT-Push und
    REST-Resync. Wird dort nicht erfasst, laeuft das Inventar leer mit - und
    das faellt erst nach Wochen auf, wenn die Datei leer ist. Deshalb ein
    Spion statt eines echten Inventars: geprueft wird die Verdrahtung, nicht
    noch einmal die Buchhaltung.
    """
    import app as app_modul

    erfasst: list[tuple[str, dict, str]] = []

    class Spion:
        aktiv = True

        def beobachte(self, sn, felder, quelle, rohnachricht=None):
            erfasst.append((sn, felder, quelle))

    monkeypatch.setattr(app_modul, "_inventar", Spion())
    monkeypatch.setattr(app_modul, "_publish_state", lambda _sn: None)

    app_modul._apply_quota_update(SN, {"pd.soc": 27}, from_push=True)
    app_modul._apply_quota_update(SN, {"pd.soc": 28}, from_push=False)

    assert [q for _, _, q in erfasst] == ["push", "rest"]
    assert erfasst[0][1] == {"pd.soc": 27}


# ------------------------------------------------ Versionsstempel in der Datei
# Ergaenzt am 16.08.2026. Das Inventar ist die Datei, die Mitwirkende
# HERSCHICKEN sollen, damit ein weiteres Modell aufgenommen werden kann. Zur
# Auswertung gehoert, mit welchem Stand sie erhoben wurde - und die
# vorhandene Zahl beantwortete das nicht.


def test_inventar_haelt_die_flowbridge_fassung_fest(tmp_path, monkeypatch):
    import version as version_modul

    monkeypatch.setattr(version_modul, "get_version", lambda: "2026.08.16-99")
    inv = Feldinventar(tmp_path / "feldinventar.json")
    inv.einschalten()
    inv.beobachte(SN, {"pd.soc": 42}, "push")
    inv.ausschalten()  # schreibt die Datei

    daten = json.loads((tmp_path / "feldinventar.json").read_text(encoding="utf-8"))
    assert daten["flowbridge_version"] == "2026.08.16-99"


def test_formatversion_bleibt_davon_unberuehrt(tmp_path, monkeypatch):
    """Die beiden Felder bedeuten Verschiedenes und duerfen nicht verschmelzen.

    `version` ist die FORMAT-Version der Datei (steht seit jeher auf 1),
    `flowbridge_version` der Stand, der die Daten erhoben hat. Genau diese
    Verwechslung war der Anlass: Wer das Inventar aufmachte, fand ein Feld
    namens `version` und hielt die 1 fuer eine Antwort."""
    import version as version_modul

    monkeypatch.setattr(version_modul, "get_version", lambda: "2026.08.16-99")
    inv = Feldinventar(tmp_path / "feldinventar.json")
    inv.einschalten()
    inv.ausschalten()

    daten = json.loads((tmp_path / "feldinventar.json").read_text(encoding="utf-8"))
    assert daten["version"] == 1
    assert daten["flowbridge_version"] == "2026.08.16-99"


def test_fassung_wird_bei_jedem_schreiben_nachgezogen(tmp_path, monkeypatch):
    """Die Datei ueberlebt Updates - sie liegt neben der config.yaml.

    Einmalig beim Anlegen gesetzt, behauptete sie noch in einem Jahr die
    Fassung, unter der sie entstanden ist."""
    import version as version_modul

    pfad = tmp_path / "feldinventar.json"

    monkeypatch.setattr(version_modul, "get_version", lambda: "2026.08.16-04")
    inv = Feldinventar(pfad)
    inv.einschalten()
    inv.ausschalten()
    assert json.loads(pfad.read_text(encoding="utf-8"))["flowbridge_version"] == "2026.08.16-04"

    # Update: dieselbe Datei, neue Fassung.
    monkeypatch.setattr(version_modul, "get_version", lambda: "2026.08.16-05")
    inv = Feldinventar(pfad)
    inv.einschalten()
    inv.ausschalten()
    assert json.loads(pfad.read_text(encoding="utf-8"))["flowbridge_version"] == "2026.08.16-05"


# ------------------------------------------- Platzhalter im ausgelieferten JSON
# Ergaenzt am 16.08.2026, nachdem Dirk in die Datei geschaut hat: Unter
# "geraete" stand die Seriennummer als Schluessel. Die Platzhalter waren kurz
# zuvor im Diagnosepaket eingebaut worden - hier fehlten sie, weil ich den
# Denkfehler an einer Stelle korrigiert und nicht gesucht hatte, wo er sonst
# noch steht.


def _inventar_mit(tmp_path, *beobachtungen):
    """Eingeschaltetes Inventar mit ein paar Buchungen.

    Eingeschaltet, weil `beobachte()` sonst nichts verbucht - und in tmp_path,
    weil `einschalten()` sofort speichert und sonst eine Datei im
    Arbeitsverzeichnis anlegte."""
    inv = Feldinventar(tmp_path / "feldinventar.json")
    inv.einschalten()
    for sn, felder in beobachtungen:
        inv.beobachte(sn, felder, "push")
    return inv


def test_download_ersetzt_die_seriennummer_als_schluessel(tmp_path):
    inv = _inventar_mit(tmp_path, (SN, {"pd.soc": 42}))
    daten = json.loads(inv.als_json({SN: "<GERAET-1>"}))
    assert SN not in json.dumps(daten)
    assert "<GERAET-1>" in daten["geraete"]


def test_download_nennt_das_modell_zum_platzhalter(tmp_path):
    """Sauber allein genuegt nicht - "welches Modell ist <GERAET-2>?" ist bei
    einem eingeschickten Inventar die erste Frage."""
    inv = _inventar_mit(tmp_path, (SN, {"pd.soc": 42}))
    daten = json.loads(inv.als_json({SN: "<GERAET-1>"}, {"<GERAET-1>": "DELTA 2"}))
    assert daten["geraete_zuordnung"] == {"<GERAET-1>": "DELTA 2"}


def test_zwei_geraete_bleiben_im_download_unterscheidbar(tmp_path):
    """Der Grund fuer Platzhalter statt Weglassen - sonst faellt das
    Inventar zweier Geraete in eines zusammen."""
    inv = _inventar_mit(tmp_path, ("SN-AAAA", {"pd.soc": 1}), ("SN-BBBB", {"pd.soc": 2}))
    daten = json.loads(inv.als_json({"SN-AAAA": "<GERAET-1>", "SN-BBBB": "<GERAET-2>"}))
    assert set(daten["geraete"]) == {"<GERAET-1>", "<GERAET-2>"}
    # Zahlen liegen unter min/max - "zuletzt" ist der Zeitstempel.
    assert daten["geraete"]["<GERAET-1>"]["felder"]["pd.soc"]["max"] == 1
    assert daten["geraete"]["<GERAET-2>"]["felder"]["pd.soc"]["max"] == 2


def test_messwerte_bleiben_vollstaendig_erhalten(tmp_path):
    """Gegenprobe: Umbenannt wird der Schluessel, nicht der Inhalt."""
    inv = _inventar_mit(tmp_path, (SN, {"pd.soc": 42, "inv.inputWatts": 109}))
    felder = json.loads(inv.als_json({SN: "<GERAET-1>"}))["geraete"]["<GERAET-1>"]["felder"]
    assert felder["pd.soc"]["max"] == 42
    assert felder["inv.inputWatts"]["max"] == 109


def test_leeres_dict_laesst_alles_stehen(tmp_path):
    """Ausdrueckliche Entscheidung, kein Versehen - dafuer ist das Argument
    Pflicht und hat keinen Vorgabewert."""
    inv = _inventar_mit(tmp_path, (SN, {"pd.soc": 42}))
    assert SN in json.loads(inv.als_json({}))["geraete"]

"""
Schwaerzung im Diagnose-Paket.

Diese Datei wird per E-Mail verschickt. Stuenden dort die EcoFlow-Schluessel
drin, haette der Absender die Kontrolle ueber seinen Speicher weitergegeben.
Deshalb ist das hier der wichtigste Test der ganzen Ablage.
"""
import logging
import logging.handlers
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import diagnostics  # noqa: E402

# ERFUNDENE Werte. Hier standen einmal echte Schluessel - als Testdaten
# naheliegend, aber grundfalsch: Testdateien landen im Repository, werden
# weitergegeben und liegen in der Historie. Laenge und Zeichenvorrat
# entsprechen echten EcoFlow-Schluesseln, damit die Schwaerzung realistisch
# geprueft wird; die Werte selbst sind es nicht.
ACCESS = "TESTaccessKEY0000000000000000AAAA"
SECRET = "TESTsecretKEY0000000000000000BBBB"
MQTT_PW = "brokergeheimnis123"

CONFIG = {
    "ecoflow": {"access_key": ACCESS, "secret_key": SECRET, "devices": []},
    "mqtt": {"host": "192.168.1.10", "password": MQTT_PW},
    "auth": {
        "password_hash": "aGFzaHdlcnRfbGFuZ19nZW51Zw",
        "password_salt": "c2FsemxhbmdnZW51Zw",
        "session_secret": "c2l0enVuZ3NnZWhlaW1uaXNfbGFuZw",
    },
}


def _config():
    return CONFIG


# --------------------------------------------------------- woertlich
@pytest.mark.parametrize("geheim", [ACCESS, SECRET, MQTT_PW,
                                    CONFIG["auth"]["session_secret"],
                                    CONFIG["auth"]["password_hash"]])
def test_konfigurierte_geheimnisse_verschwinden(geheim):
    text = f"irgendein Text mit {geheim} mittendrin"
    assert geheim not in diagnostics.schwaerze(text, CONFIG)


def test_geheimnis_wird_auch_ohne_umgebenden_schluessel_gefunden():
    """Der Wert kann auch nackt in einer Zeile stehen - etwa in einer URL."""
    text = f"GET https://api-e.ecoflow.com/x?accessKey={ACCESS}&nonce=123456"
    ergebnis = diagnostics.schwaerze(text, CONFIG)
    assert ACCESS not in ergebnis


def test_laengstes_geheimnis_zuerst():
    """Ist ein Geheimnis Teil eines anderen, darf der kurze Treffer den
    langen nicht zerschneiden und einen Rest stehen lassen."""
    config = {"ecoflow": {"access_key": "ABC123XYZ", "secret_key": "ABC123XYZ-VERLAENGERT"}}
    ergebnis = diagnostics.schwaerze("Wert: ABC123XYZ-VERLAENGERT", config)
    assert "ABC123XYZ" not in ergebnis


# ------------------------------------------------------------ nach Muster
@pytest.mark.parametrize(
    "zeile,verraeterisch",
    [
        ('{"secretKey": "NochNieGesehenAber32ZeichenLang"}', "NochNieGesehenAber32ZeichenLang"),
        ("accessKey=EinAndererSchluesselWert123", "EinAndererSchluesselWert123"),
        ("password: mein-anderes-passwort", "mein-anderes-passwort"),
        ("sign=3f8a9b2c1d4e5f6a7b8c9d0e1f2a3b4c", "3f8a9b2c1d4e5f6a7b8c9d0e1f2a3b4c"),
        ("Authorization: Bearer abcdefghijklmnop", "abcdefghijklmnop"),
        ("Cookie: flowbridge_session=1799999999.SigNaTur", "1799999999.SigNaTur"),
    ],
)
def test_unbekannte_geheimnisse_werden_nach_muster_erkannt(zeile, verraeterisch):
    """Faengt auch das ab, was gar nicht in der Konfiguration steht - etwa
    einen vertippten Schluessel aus einem fehlgeschlagenen Verbindungstest."""
    assert verraeterisch not in diagnostics.schwaerze(zeile, {})


def test_unbekannte_seriennummer_wird_nicht_angefasst():
    """Ersetzt werden nur die Nummern der KONFIGURIERTEN Geraete.

    Hier steht in der Konfiguration keines, also bleibt der Text unveraendert.
    Bewusst kein Muster auf "sieht aus wie eine Seriennummer": Das traefe auch
    Nutzdaten, und aus zwei verschiedenen Geraeten wuerde eines.

    ACHTUNG, dieser Test hiess bis 16.08.2026 "seriennummer_bleibt_lesbar" und
    trug als Begruendung, ohne sie lasse sich "nichts analysieren". Das war
    derselbe Denkfehler, der an drei Stellen im Quelltext stand: Gebraucht wird
    UNTERSCHEIDBAR, nicht IDENTIFIZIERBAR. Konfigurierte Geraete werden sehr
    wohl ersetzt - siehe test_seriennummer_wird_zum_platzhalter weiter unten.
    """
    text = "Geraet R621TESTSN000000 meldet 20 Felder"
    assert "R621TESTSN000000" in diagnostics.schwaerze(text, CONFIG)


def test_normale_werte_bleiben_stehen():
    text = "SoC 43 %, AC-Eingang 105 W, Broker 192.168.1.10:1883"
    assert diagnostics.schwaerze(text, CONFIG) == text


# ------------------------------------------------------------- Formatter
def _zeile(nachricht, *args):
    f = diagnostics.SchwaerzenderFormatter(_config)
    record = logging.LogRecord("test", logging.INFO, __file__, 1, nachricht, args, None)
    return f.format(record)


def test_formatter_schwaerzt_auch_eingesetzte_platzhalter():
    """%s-Argumente werden erst beim Formatieren eingesetzt - eine Pruefung
    auf der Rohnachricht wuerde sie glatt uebersehen."""
    assert SECRET not in _zeile("Verbinde mit Schluessel %s", SECRET)


def test_formatter_gibt_im_zweifel_nichts_heraus(monkeypatch):
    """Wenn die Schwaerzung scheitert, darf die Zeile NICHT ungeschwaerzt
    durchrutschen."""
    def kaputt():
        raise RuntimeError("Konfiguration nicht lesbar")

    f = diagnostics.SchwaerzenderFormatter(kaputt)
    record = logging.LogRecord("test", logging.INFO, __file__, 1, f"Key {SECRET}", (), None)
    ergebnis = f.format(record)
    assert SECRET not in ergebnis
    assert "unterdrueckt" in ergebnis


# ---------------------------------------------------------------- Ring
def test_ringpuffer_laeuft_immer_mit_und_ist_begrenzt():
    ring = diagnostics.RingHandler(zeilen=5)
    ring.setFormatter(diagnostics.SchwaerzenderFormatter(_config))
    for i in range(20):
        ring.emit(logging.LogRecord("t", logging.INFO, __file__, 1, "Zeile %d", (i,), None))
    zeilen = ring.zeilen()
    assert len(zeilen) == 5
    assert "Zeile 19" in zeilen[-1]


def test_ringpuffer_schwaerzt_ebenfalls():
    ring = diagnostics.RingHandler()
    ring.setFormatter(diagnostics.SchwaerzenderFormatter(_config))
    ring.emit(logging.LogRecord("t", logging.INFO, __file__, 1, "Key %s", (SECRET,), None))
    assert SECRET not in "\n".join(ring.zeilen())


# ---------------------------------------------------------------- Paket
def test_paket_enthaelt_alle_teile_und_keine_geheimnisse(tmp_path):
    d = diagnostics.Diagnose(_config, tmp_path / "flowbridge.log")
    d.einschalten()
    logging.getLogger("test").info("Anmeldung mit Schluessel %s", SECRET)
    d.ausschalten()

    rohdaten = d.paket(
        bericht="FlowBridge – Diagnosebericht\n",
        config_maskiert="ecoflow:\n  secret_key: '••••••••'\n",
        topics="flowbridge/R621TESTSN000000/state\n",
    )
    with zipfile.ZipFile(BytesIO(rohdaten)) as z:
        namen = set(z.namelist())
        assert namen == {
            "bericht.txt", "konfiguration-maskiert.yaml",
            "mqtt-topics.txt", "protokoll.txt",
            # Seit 16.08.2026: Ohne diese Zuordnung waere das Paket zwar
            # sauber, aber stumm - welches Modell hinter <GERAET-2> steckt,
            # ist beim Lesen die erste Frage.
            "geraete-zuordnung.txt",
        }
        alles = "".join(z.read(n).decode("utf-8") for n in namen)
    assert SECRET not in alles
    assert ACCESS not in alles


def test_protokolldatei_wird_geschwaerzt_geschrieben(tmp_path):
    """Nicht erst beim Packen: schon die Datei auf der Platte darf die
    Geheimnisse nicht enthalten."""
    pfad = tmp_path / "flowbridge.log"
    d = diagnostics.Diagnose(_config, pfad)
    d.einschalten()
    logging.getLogger("test").info("Schluessel %s und Passwort %s", SECRET, MQTT_PW)
    d.ausschalten()

    inhalt = pfad.read_text(encoding="utf-8")
    assert SECRET not in inhalt
    assert MQTT_PW not in inhalt
    assert diagnostics.GESCHWAERZT in inhalt


def test_loeschen_raeumt_die_dateien_weg(tmp_path):
    pfad = tmp_path / "flowbridge.log"
    d = diagnostics.Diagnose(_config, pfad)
    d.einschalten()
    logging.getLogger("test").info("etwas")
    d.ausschalten()
    assert pfad.exists()
    d.loeschen()
    assert not pfad.exists()
    assert d.groesse_bytes() == 0


# ---------------------------------------------------------------- Bericht
def _bericht(**geraet):
    basis = {
        "sn": "R621TEST", "model": "RIVER 2 Pro", "product_name": "RIVER 2 Pro",
        "support_level": "verified", "controllable": True,
        "charge_steps": [100, 150], "online": True, "felder": 20, "error": None,
    }
    return diagnostics.baue_bericht(
        version="2026.08.13-08", update_status="unknown",
        health={}, geraete=[{**basis, **geraet}], laufzeit_s=60,
        datei_protokoll=True,
    )


def test_bericht_nennt_beide_modellangaben():
    t = _bericht()
    assert "Modell konfiguriert: RIVER 2 Pro" in t
    assert "Modell laut EcoFlow: RIVER 2 Pro" in t


def test_bericht_warnt_bei_abweichendem_modell():
    """Der interessanteste Fall: konfiguriert steht etwas anderes als das,
    was EcoFlow meldet - dann greifen die Befehle des falschen Modells."""
    t = _bericht(model="RIVER 2 Pro", product_name="DELTA 2")
    assert "ACHTUNG" in t


def test_bericht_warnt_nicht_bei_abweichender_schreibweise():
    assert "ACHTUNG" not in _bericht(model="river 2 pro", product_name="RIVER 2 Pro")


def test_bericht_kommt_ohne_ecoflow_antwort_aus():
    """Ist die Geraeteliste nicht abrufbar, ist das selbst ein Befund - der
    Bericht muss trotzdem entstehen."""
    t = _bericht(product_name=None)
    assert "nicht abrufbar" in t
    assert "ACHTUNG" not in t


def test_bericht_nennt_unterstuetzungsgrad():
    t = _bericht(support_level="documented", controllable=True)
    assert "documented" in t
    assert "steuerbar: ja" in t


# ------------------------------------------------- Rauschunterdrueckung (14.08.2026)
def test_fremdbibliotheken_werden_gedaempft(tmp_path):
    """70 % des Protokolls waren httpcore-Zeilen.

    Gemessen an einem echten 17-Minuten-Protokoll: 162 von 231 KB stammten
    von httpcore ("connect_tcp.started" je REST-Aufruf). Bei 3x2 MB Rotation
    reichte die Datei damit nur ~7,5 Stunden zurueck - zu wenig, um einem
    Aussetzer nachzugehen, der alle paar Stunden auftritt.
    """
    d = diagnostics.Diagnose(lambda: {}, tmp_path / "x.log")
    httpcore = logging.getLogger("httpcore")

    d.einschalten()
    try:
        assert logging.getLogger().level == logging.DEBUG, "FlowBridge selbst bleibt auf DEBUG"
        assert httpcore.level == logging.WARNING
        # WARNING statt AUS: ein echter HTTP-Fehler muss weiterhin durchkommen.
        assert httpcore.isEnabledFor(logging.WARNING)
        assert not httpcore.isEnabledFor(logging.DEBUG)
    finally:
        d.ausschalten()

    # Nach dem Ausschalten wieder freigeben - sonst blieben sie dauerhaft stumm.
    assert httpcore.level == logging.NOTSET


# ------------------------------------------------------- Reichweite (14.08.2026)
def test_protokoll_reicht_mehrere_tage_zurueck(tmp_path):
    """Der Deckel bestimmt, wie weit man zuruecksehen kann.

    Bei 3 x 2 MB waren garantiert nur ~17 Stunden abgedeckt - denn direkt nach
    einer Umschaltung ist die neueste Datei leer, es zaehlen also nur die
    aelteren Staende. Fuer Aussetzer, die alle paar Stunden kommen und erst am
    naechsten Morgen auffallen, war das zu knapp.

    Dieser Test haelt die Reichweite fest, damit sie niemand beilaeufig wieder
    einsammelt: (MAX_DATEIEN - 1) x MAX_DATEI_BYTES ist die Zusage.
    """
    garantiert_bytes = (diagnostics.MAX_DATEIEN - 1) * diagnostics.MAX_DATEI_BYTES
    # ~4 KB/min gemessen am 14.08.2026, ohne das Rauschen der Fremdbibliotheken.
    garantierte_stunden = garantiert_bytes / 1024 / 4 / 60
    assert garantierte_stunden > 72, "mindestens drei Tage, sonst faellt eine Nacht weg"

    d = diagnostics.Diagnose(lambda: {}, tmp_path / "x.log")
    d.einschalten()
    try:
        passend = [
            h for h in logging.getLogger().handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
            and Path(h.baseFilename) == tmp_path / "x.log"
        ]
        assert len(passend) == 1
        # Die Konstanten muessen auch wirklich am Handler ankommen.
        assert passend[0].maxBytes == diagnostics.MAX_DATEI_BYTES
        assert passend[0].backupCount == diagnostics.MAX_DATEIEN - 1
    finally:
        d.ausschalten()


# ------------------------------------------------- Versionsstempel im Protokoll
# Ergaenzt am 16.08.2026 auf Dirks Frage: "Nicht dass jemand mit einer alten
# Fassung Testdaten schickt." Das Protokoll enthielt bis dahin nirgends eine
# Versionsnummer - nur der Diagnosebericht im ZIP. Wer die letzten Zeilen
# kopiert und schickt (der Normalfall), schickte sie damit ohne Herkunft.


def test_jede_protokolldatei_beginnt_mit_der_version(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics.version, "get_version", lambda: "2026.08.16-99")
    d = diagnostics.Diagnose(lambda: {}, tmp_path / "x.log")
    d.einschalten()
    try:
        logging.getLogger().warning("irgendetwas")
    finally:
        d.ausschalten()

    zeilen = (tmp_path / "x.log").read_text(encoding="utf-8").splitlines()
    assert zeilen[0].startswith("# FlowBridge 2026.08.16-99"), zeilen[0]


def test_auch_nach_der_umschaltung_steht_die_version_oben(tmp_path, monkeypatch):
    """Der eigentliche Punkt.

    Umgeschaltet wird nach GROESSE. Stuende die Version nur in der ersten
    Datei, traegen vier von fuenf sie nicht - und welche davon jemand
    erwischt, ist Zufall."""
    monkeypatch.setattr(diagnostics.version, "get_version", lambda: "2026.08.16-99")
    monkeypatch.setattr(diagnostics, "MAX_DATEI_BYTES", 400)  # schnell umschalten
    d = diagnostics.Diagnose(lambda: {}, tmp_path / "x.log")
    d.einschalten()
    try:
        for i in range(40):
            logging.getLogger().warning("Zeile %d mit etwas Fuellung zum Umschalten", i)
    finally:
        d.ausschalten()

    dateien = sorted(tmp_path.glob("x.log*"))
    assert len(dateien) > 1, "Test taugt nur, wenn wirklich umgeschaltet wurde"
    for pfad in dateien:
        erste = pfad.read_text(encoding="utf-8").splitlines()[0]
        assert erste.startswith("# FlowBridge 2026.08.16-99"), f"{pfad.name}: {erste}"


def test_neustart_mit_neuer_fassung_setzt_eine_neue_kopfzeile(tmp_path, monkeypatch):
    """Der Update-Fall - gerade der, bei dem die Frage aufkommt.

    Die Protokolldatei liegt neben der config.yaml und ueberlebt das Update.
    Ohne zweite Kopfzeile stuende ueber den Zeilen der neuen Fassung noch die
    Nummer der alten."""
    pfad = tmp_path / "x.log"

    monkeypatch.setattr(diagnostics.version, "get_version", lambda: "2026.08.16-04")
    d = diagnostics.Diagnose(lambda: {}, pfad)
    d.einschalten()
    logging.getLogger().warning("vor dem Update")
    d.ausschalten()

    monkeypatch.setattr(diagnostics.version, "get_version", lambda: "2026.08.16-05")
    d = diagnostics.Diagnose(lambda: {}, pfad)
    d.einschalten()
    logging.getLogger().warning("nach dem Update")
    d.ausschalten()

    text = pfad.read_text(encoding="utf-8")
    assert "# FlowBridge 2026.08.16-04" in text
    assert "# FlowBridge 2026.08.16-05" in text
    # Reihenfolge stimmt: die alte Kopfzeile steht vor der neuen.
    assert text.index("2026.08.16-04") < text.index("2026.08.16-05")


def test_kopfzeile_verdraengt_die_protokollzeilen_nicht(tmp_path, monkeypatch):
    """Gegenprobe: Die Beschriftung kommt DAZU, sie ersetzt nichts."""
    monkeypatch.setattr(diagnostics.version, "get_version", lambda: "2026.08.16-99")
    d = diagnostics.Diagnose(lambda: {}, tmp_path / "x.log")
    d.einschalten()
    try:
        logging.getLogger().warning("die eigentliche Meldung")
    finally:
        d.ausschalten()
    assert "die eigentliche Meldung" in (tmp_path / "x.log").read_text(encoding="utf-8")


# ------------------------------------------------------ Platzhalter statt Kennungen
# Ergaenzt am 16.08.2026 auf Dirks Frage: "Wuerde nicht ein namentlicher
# Platzhalter gehen?" - Ja, und er ist besser als die alte Begruendung.
# Gemessen an einem echten Protokoll (3813 Zeilen): Seriennummer 3735 mal,
# Kontokennung 1256 mal.

# ERFUNDEN, wie ACCESS und SECRET oben - und aus demselben Grund.
# Der Name sagt es absichtlich: BEISPIEL. Er hiess einmal SN_ECHT, und genau
# so eine Benennung laedt dazu ein, beim naechsten Mal eine echte Nummer
# einzutragen - "steht ja dran".
# Hier standen bis zum 16.08.2026 die echte Seriennummer und die echte
# Kontokennung von Dirks Geraet. Als Testdaten naheliegend (man will ja
# pruefen, dass GENAU das verschwindet) und trotzdem grundfalsch: Die Tests
# gehen mit auf GitHub, und damit stuenden beide Werte oeffentlich in
# derselben Ablage, die sie schuetzen soll.
# Laenge und Zeichenvorrat entsprechen den echten, damit Muster und
# Ersetzung realistisch geprueft werden; die Werte selbst tun es nicht.
SN_BEISPIEL = "R621TESTSN000000"
KONTO = "open-0123456789abcdef0123456789abcdef"
CONFIG_MIT_GERAET = {
    **CONFIG,
    "ecoflow": {**CONFIG["ecoflow"], "devices": [{"sn": SN_BEISPIEL, "model": "RIVER 2 Pro"}]},
}

# Woertlich aus Dirks Protokoll uebernommen, nur die Nutzdaten gekuerzt - so
# steht sie 1256 mal in der Datei.
ECHTE_LOGZEILE = (
    f"EcoFlow-MQTT-Nachricht auf /open/{KONTO}/{SN_BEISPIEL}/quota: "
    f"""b'{{"moduleType":2,"soc":40}}'"""
)


def test_seriennummer_wird_zum_platzhalter():
    ergebnis = diagnostics.schwaerze(ECHTE_LOGZEILE, CONFIG_MIT_GERAET)
    assert SN_BEISPIEL not in ergebnis
    assert "<GERAET-1>" in ergebnis


def test_kontokennung_wird_zum_platzhalter():
    """Sie steht in KEINEM Konfigurationsfeld - sie kommt aus dem
    Zertifikatsabruf. Genau daran ist die erste Fassung vorbeigelaufen."""
    ergebnis = diagnostics.schwaerze(ECHTE_LOGZEILE, CONFIG_MIT_GERAET)
    assert KONTO not in ergebnis
    assert "<KONTO>" in ergebnis


def test_nutzdaten_bleiben_erhalten():
    """Gegenprobe: Geschwaerzt wird die Kennung, nicht die Messung.

    Ein Protokoll ohne Werte waere zwar sauber, aber wertlos."""
    ergebnis = diagnostics.schwaerze(ECHTE_LOGZEILE, CONFIG_MIT_GERAET)
    assert '"soc":40' in ergebnis
    assert "moduleType" in ergebnis


def test_zwei_geraete_bleiben_unterscheidbar():
    """DER Grund fuer Platzhalter statt [geschwaerzt].

    Ein durchgaengiges [geschwaerzt] machte aus zwei Geraeten eines - und
    damit waere jede Auswertung erledigt, bei der es auf die Zuordnung
    ankommt."""
    zwei = {
        **CONFIG,
        "ecoflow": {
            **CONFIG["ecoflow"],
            "devices": [{"sn": "SN-AAAA-1111"}, {"sn": "SN-BBBB-2222"}],
        },
    }
    ergebnis = diagnostics.schwaerze("SN-AAAA-1111 und SN-BBBB-2222", zwei)
    assert ergebnis == "<GERAET-1> und <GERAET-2>"


def test_umbenennen_ist_idempotent():
    """Das Paket laesst Protokolldateien ein zweites Mal durchlaufen, damit
    auch Dateien von VOR dieser Aenderung sauber werden. Das darf nichts
    kaputtmachen."""
    einmal = diagnostics.benenne_um(ECHTE_LOGZEILE, CONFIG_MIT_GERAET)
    zweimal = diagnostics.benenne_um(einmal, CONFIG_MIT_GERAET)
    assert einmal == zweimal


def test_paket_traegt_in_KEINEM_bestandteil_die_seriennummer():
    """Der Test, auf den es ankommt.

    Vorher lief nur das Protokoll durch die Schwaerzung. Bericht,
    Konfiguration und Topic-Liste gingen roh hinein - in der Topic-Liste
    stand die Seriennummer in jeder Zeile."""
    d = diagnostics.Diagnose(lambda: CONFIG_MIT_GERAET, Path("nicht-vorhanden.log"))
    daten = d.paket(
        bericht=f"Geraete\n  {SN_BEISPIEL}\n    Modell: RIVER 2 Pro\n",
        config_maskiert=f"ecoflow:\n  devices:\n    - sn: {SN_BEISPIEL}\n",
        topics=f"flowbridge/{SN_BEISPIEL}/status/soc_percent\n",
    )
    with zipfile.ZipFile(BytesIO(daten)) as z:
        for name in z.namelist():
            inhalt = z.read(name).decode("utf-8")
            assert SN_BEISPIEL not in inhalt, f"{name} traegt die Seriennummer"
            assert KONTO not in inhalt, f"{name} traegt die Kontokennung"


def test_paket_erklaert_die_platzhalter():
    """Sauber allein genuegt nicht - das Paket muss auch lesbar bleiben."""
    d = diagnostics.Diagnose(lambda: CONFIG_MIT_GERAET, Path("nicht-vorhanden.log"))
    with zipfile.ZipFile(BytesIO(d.paket("", "", ""))) as z:
        zuordnung = z.read("geraete-zuordnung.txt").decode("utf-8")
    assert "<GERAET-1>" in zuordnung
    assert "RIVER 2 Pro" in zuordnung
    assert SN_BEISPIEL not in zuordnung, "die Zuordnung darf die Nummer gerade NICHT nennen"

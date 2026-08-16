"""
Zugriffsschutz. Hier wird nicht die Oberflaeche geprueft, sondern die Frage,
ob die Schnittstelle ohne Anmeldung wirklich zu ist - und ob Geheimnisse
dort bleiben, wo sie hingehoeren.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import auth  # noqa: E402
from config import mask_secrets  # noqa: E402

PASSWORT = "ein-gutes-Passwort"


# ---------------------------------------------------------------- Passwort
def test_passwort_wird_nie_im_klartext_abgelegt():
    salt, hashwert = auth.hash_password(PASSWORT)
    assert PASSWORT not in salt
    assert PASSWORT not in hashwert


def test_gleiches_passwort_ergibt_verschiedene_hashes():
    """Ohne eigenes Salz je Passwort waeren Regenbogentabellen anwendbar."""
    salt1, hash1 = auth.hash_password(PASSWORT)
    salt2, hash2 = auth.hash_password(PASSWORT)
    assert salt1 != salt2
    assert hash1 != hash2


def test_richtiges_passwort_wird_erkannt():
    salt, hashwert = auth.hash_password(PASSWORT)
    assert auth.verify_password(PASSWORT, salt, hashwert)


@pytest.mark.parametrize("falsch", ["", "falsch", PASSWORT + "x", PASSWORT.upper()])
def test_falsches_passwort_wird_abgelehnt(falsch):
    salt, hashwert = auth.hash_password(PASSWORT)
    assert not auth.verify_password(falsch, salt, hashwert)


def test_kaputte_ablage_fuehrt_nicht_zum_absturz():
    """Von Hand verpfuschte config.yaml darf keine Ausnahme werfen -
    und schon gar nicht durchlassen."""
    assert not auth.verify_password(PASSWORT, "kein-base64!!", "auch-nicht")


def test_zu_kurzes_passwort_wird_abgelehnt():
    with pytest.raises(auth.AuthError):
        auth.pruefe_passwort_regeln("kurz")


# ------------------------------------------------------------------- Token
def test_gueltiges_token_wird_akzeptiert():
    geheimnis = auth.neues_sitzungsgeheimnis()
    assert auth.token_gueltig(auth.create_token(geheimnis), geheimnis)


def test_token_mit_fremdem_geheimnis_wird_abgelehnt():
    token = auth.create_token(auth.neues_sitzungsgeheimnis())
    assert not auth.token_gueltig(token, auth.neues_sitzungsgeheimnis())


def test_abgelaufenes_token_wird_abgelehnt():
    geheimnis = auth.neues_sitzungsgeheimnis()
    assert not auth.token_gueltig(auth.create_token(geheimnis, gueltig_stunden=-1), geheimnis)


def test_verlaengerte_ablaufzeit_ohne_neue_signatur_wird_abgelehnt():
    """Der naheliegendste Angriff: die Zahl vor dem Punkt hochsetzen."""
    geheimnis = auth.neues_sitzungsgeheimnis()
    _alt, signatur = auth.create_token(geheimnis).split(".")
    gefaelscht = f"{int(time.time()) + 10**6}.{signatur}"
    assert not auth.token_gueltig(gefaelscht, geheimnis)


@pytest.mark.parametrize("murks", ["", "kein-punkt", "a.b.c", "....", "9999999999."])
def test_unsinnige_token_werden_abgelehnt(murks):
    assert not auth.token_gueltig(murks, auth.neues_sitzungsgeheimnis())


# ------------------------------------------------------------------ Bremse
def test_bremse_greift_nach_zu_vielen_fehlversuchen():
    f = auth.Fehlversuche()
    for _ in range(auth.MAX_FEHLVERSUCHE):
        f.pruefe("10.0.0.1")
        f.fehlschlag("10.0.0.1")
    with pytest.raises(auth.AuthError):
        f.pruefe("10.0.0.1")


def test_bremse_trifft_nur_die_betroffene_herkunft():
    f = auth.Fehlversuche()
    for _ in range(auth.MAX_FEHLVERSUCHE):
        f.fehlschlag("10.0.0.1")
    f.pruefe("10.0.0.2")  # darf nicht werfen


def test_erfolgreiche_anmeldung_loescht_den_zaehler():
    f = auth.Fehlversuche()
    for _ in range(auth.MAX_FEHLVERSUCHE):
        f.fehlschlag("10.0.0.1")
    f.erfolg("10.0.0.1")
    f.pruefe("10.0.0.1")


# ----------------------------------------------------------- Konfiguration
def test_ohne_passwort_gilt_als_nicht_eingerichtet():
    assert not auth.ist_eingerichtet({})
    assert not auth.ist_eingerichtet({"auth": {}})
    assert not auth.ist_eingerichtet({"auth": {"password_hash": "x"}})  # Salz fehlt


def test_passwortwechsel_erneuert_das_sitzungsgeheimnis():
    """Wer sein Passwort aendert, will jemanden aussperren - alte Sitzungen
    duerfen das nicht ueberleben."""
    erst = auth.setze_passwort({}, PASSWORT)
    dann = auth.setze_passwort(erst, PASSWORT + "-neu")
    altes_token = auth.create_token(erst["auth"]["session_secret"])
    assert not auth.token_gueltig(altes_token, dann["auth"]["session_secret"])


def test_auth_block_wird_dem_frontend_nie_ausgeliefert():
    """Mit dem Sitzungsgeheimnis liessen sich beliebige gueltige Token bauen."""
    config = auth.setze_passwort({"ecoflow": {}, "mqtt": {}}, PASSWORT)
    maskiert = mask_secrets(config)
    assert "auth" not in maskiert
    assert "session_secret" not in str(maskiert)
    assert config["auth"]["password_hash"] not in str(maskiert)


# ------------------------------------------------- Zwischenspeicher config
def test_config_cache_bemerkt_aenderungen(tmp_path, monkeypatch):
    """Der Zugriffsschutz liest bei jeder Anfrage - der Zwischenspeicher darf
    aber keine veraltete Konfiguration ausliefern, sonst wirkte ein
    Passwortwechsel erst nach einem Neustart."""
    import config as config_modul

    datei = tmp_path / "config.yaml"
    monkeypatch.setenv("FLOWBRIDGE_CONFIG", str(datei))
    config_modul.invalidate_cache()

    config_modul.write_config({"mqtt": {"host": "erst"}})
    assert config_modul.load_config()["mqtt"]["host"] == "erst"

    config_modul.write_config({"mqtt": {"host": "dann"}})
    assert config_modul.load_config()["mqtt"]["host"] == "dann"


def test_config_cache_gibt_keine_gemeinsame_referenz_heraus(tmp_path, monkeypatch):
    """Sonst veraendert ein Aufrufer versehentlich den Zwischenspeicher."""
    import config as config_modul

    datei = tmp_path / "config.yaml"
    monkeypatch.setenv("FLOWBRIDGE_CONFIG", str(datei))
    config_modul.invalidate_cache()
    config_modul.write_config({"mqtt": {"host": "a"}})

    erst = config_modul.load_config()
    erst["mqtt"] = {"host": "veraendert"}
    assert config_modul.load_config()["mqtt"]["host"] == "a"

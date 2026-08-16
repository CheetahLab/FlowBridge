"""
Der eigentliche Nachweis: Ist die HTTP-Schnittstelle ohne Anmeldung wirklich
zu? Die Tests in test_auth.py pruefen nur die Bausteine - dass die Middleware
sie auch an JEDER Route anwendet, zeigt erst dieser Durchlauf gegen die App.

WICHTIG: FLOWBRIDGE_CONFIG wird VOR dem Import von app gesetzt, sonst laedt
(und beschreibt!) der Test die echte config.yaml.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_tmp = Path(tempfile.mkdtemp(prefix="flowbridge-test-")) / "config.yaml"
os.environ["FLOWBRIDGE_CONFIG"] = str(_tmp)
os.environ.pop("FLOWBRIDGE_PASSWORD", None)

from fastapi.testclient import TestClient  # noqa: E402

import app as app_modul  # noqa: E402
from config import write_config  # noqa: E402

PASSWORT = "ein-gutes-Passwort"

# Jede dieser Routen muss ohne Anmeldung 401 liefern. Kommt eine neue Route
# dazu, gehoert sie hier hinein - der Test ist die Erinnerung daran.
GESCHUETZT = [
    ("GET", "/api/config"),
    ("GET", "/api/state"),
    ("GET", "/api/health"),
    ("GET", "/api/version"),
    ("GET", "/api/history/R621TEST"),
    ("POST", "/api/refresh/R621TEST"),
    ("POST", "/api/command"),
    ("POST", "/api/setup"),
    ("POST", "/api/setup/test"),
    ("POST", "/api/setup/discover"),
    # Das Diagnose-Paket enthaelt Konfiguration und Protokoll - es waere die
    # unangenehmste offene Route von allen.
    ("GET", "/api/diagnostics"),
    ("POST", "/api/diagnostics"),
    ("DELETE", "/api/diagnostics"),
    ("GET", "/api/diagnostics/download"),
    # Das Feldinventar traegt Seriennummer und Messwerte ueber Wochen.
    ("GET", "/api/analysis"),
    ("POST", "/api/analysis"),
    ("DELETE", "/api/analysis"),
    ("GET", "/api/analysis/download"),
    # Die Exporte enthalten die vollstaendige Topic-Struktur samt
    # Seriennummern - ebenfalls nichts fuer Unangemeldete.
    ("GET", "/api/export/generic"),
    ("GET", "/api/export/eisbaer/channels"),
    ("GET", "/api/export/eisbaer/profiles"),
]


@pytest.fixture
def client():
    write_config({"ecoflow": {"devices": []}, "mqtt": {}, "auth": {}})
    app_modul._fehlversuche = app_modul.auth.Fehlversuche()
    # Ohne Lifespan: der Test soll die Schnittstelle pruefen, nicht MQTT.
    return TestClient(app_modul.app)


def _mit_passwort(client):
    r = client.post("/api/auth/password", json={"password": PASSWORT})
    assert r.status_code == 200, r.text
    return client


# --------------------------------------------------- ohne Zugriffsschutz
@pytest.mark.parametrize("methode,pfad", GESCHUETZT)
def test_ohne_eingerichteten_schutz_ist_alles_zu(client, methode, pfad):
    """Solange kein Passwort gesetzt ist, gibt es keine Daten - sonst waere
    FlowBridge im Zeitfenster vor der Einrichtung komplett offen."""
    r = client.request(methode, pfad, json={})
    assert r.status_code == 401
    assert r.json().get("setup_required") is True


def test_zustand_ist_auch_ohne_anmeldung_abfragbar(client):
    """Die Oberflaeche muss wissen, welchen Bildschirm sie zeigen soll."""
    r = client.get("/api/auth/state")
    assert r.status_code == 200
    assert r.json() == {
        "configured": False,
        "authenticated": False,
        "min_length": app_modul.auth.MIN_PASSWORT_LAENGE,
        # None heisst "Datenordner ist beschreibbar". Der Wert gehoert
        # ausdruecklich an diesen offenen Endpunkt: Wer nicht speichern kann,
        # kommt ueber die Anmeldung gar nicht hinaus und muss den Grund
        # trotzdem sehen duerfen.
        "storage_error": None,
    }


# ------------------------------------------------------ mit Zugriffsschutz
@pytest.mark.parametrize("methode,pfad", GESCHUETZT)
def test_mit_schutz_aber_ohne_anmeldung_ist_alles_zu(client, methode, pfad):
    _mit_passwort(client)
    client.cookies.clear()
    r = client.request(methode, pfad, json={})
    assert r.status_code == 401


def test_nach_anmeldung_erreichbar(client):
    _mit_passwort(client)
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"password": PASSWORT}).status_code == 200
    assert client.get("/api/version").status_code == 200


def test_falsches_passwort_meldet_nicht_an(client):
    _mit_passwort(client)
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"password": "falsch"}).status_code == 401
    assert client.get("/api/version").status_code == 401


def test_gefaelschtes_cookie_wird_abgelehnt(client):
    _mit_passwort(client)
    client.cookies.clear()
    client.cookies.set(app_modul.auth.SESSION_COOKIE, "99999999999.gefaelscht")
    assert client.get("/api/version").status_code == 401


def test_abmelden_schliesst_wieder_zu(client):
    _mit_passwort(client)
    assert client.get("/api/version").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/version").status_code == 401


# ------------------------------------------------------------ Passwortweg
def test_gesetztes_passwort_ist_nicht_mehr_frei_aenderbar(client):
    """Sonst koennte jeder im Netz den Schutz einfach ueberschreiben."""
    _mit_passwort(client)
    client.cookies.clear()
    r = client.post("/api/auth/password", json={"password": "was-anderes-langes"})
    assert r.status_code == 401


def test_aendern_verlangt_das_aktuelle_passwort(client):
    _mit_passwort(client)  # angemeldet
    r = client.post(
        "/api/auth/password",
        json={"password": "neues-langes-Passwort", "current_password": "falsch"},
    )
    assert r.status_code == 401


def test_aendern_mit_richtigem_aktuellen_passwort(client):
    _mit_passwort(client)
    r = client.post(
        "/api/auth/password",
        json={"password": "neues-langes-Passwort", "current_password": PASSWORT},
    )
    assert r.status_code == 200
    assert client.post("/api/auth/login", json={"password": PASSWORT}).status_code == 401
    assert (
        client.post("/api/auth/login", json={"password": "neues-langes-Passwort"}).status_code
        == 200
    )


def test_zu_kurzes_passwort_wird_abgelehnt(client):
    r = client.post("/api/auth/password", json={"password": "kurz"})
    assert r.status_code == 400


def test_bremse_greift_auch_ueber_http(client):
    _mit_passwort(client)
    client.cookies.clear()
    for _ in range(app_modul.auth.MAX_FEHLVERSUCHE):
        client.post("/api/auth/login", json={"password": "falsch"})
    r = client.post("/api/auth/login", json={"password": PASSWORT})
    assert r.status_code == 429


def test_konfiguration_enthaelt_keine_geheimnisse(client):
    _mit_passwort(client)
    daten = client.get("/api/config").json()
    assert "auth" not in daten
    assert "session_secret" not in str(daten)

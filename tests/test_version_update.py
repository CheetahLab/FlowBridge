"""Tests fuer die Update-Pruefung gegen die Tag-Liste von Docker Hub.

Die Quelle ist Docker Hub und nicht GHCR, weil dort die Tag-Liste ANONYM
abrufbar ist - bei GHCR braucht schon das Auflisten ein Token, und ein Token
laesst sich nicht in ein oeffentliches Abbild legen.

Der wichtigste Test hier ist der Zahlvergleich. Als Zeichenkette waere
"2026.08.16-100" KLEINER als "2026.08.16-99", weil "1" vor "9" kommt - und
der Zaehler ist die Zahl der Commits eines Tages. Am 16.08.2026 standen wir
bei dreizehn; dreistellig ist eine Frage der Zeit, nicht der Fantasie.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import version  # noqa: E402


@pytest.fixture(autouse=True)
def leerer_zwischenspeicher():
    version._letzte = None
    yield
    version._letzte = None


# ------------------------------------------------------------ Zerlegen
def test_zerlegt_eine_fassung_in_zahlen():
    assert version.zerlege("2026.08.16-13") == (2026, 8, 16, 13)


def test_latest_ist_keine_fassung():
    """"latest" steht in JEDER Tag-Liste. Ginge es als Fassung durch, waere
    es je nach Sortierung die "neueste" - und der Vergleich sinnlos."""
    assert version.zerlege("latest") is None


@pytest.mark.parametrize("murks", ["", "v1.2.3", "2026.08.16", "2026.8.16-1", "irgendwas"])
def test_unbrauchbare_marken_geben_none(murks):
    assert version.zerlege(murks) is None


def test_dreistelliger_zaehler_schlaegt_zweistelligen():
    """DER Grund fuer den Zahlvergleich - als Text ginge es andersherum."""
    assert version.zerlege("2026.08.16-100") > version.zerlege("2026.08.16-99")
    assert "2026.08.16-100" < "2026.08.16-99", "Gegenprobe: als Text ist es falsch herum"


def test_neuer_tag_schlaegt_hohen_zaehler():
    assert version.zerlege("2026.08.17-01") > version.zerlege("2026.08.16-99")


# ------------------------------------------------------------ Auswerten
def _pruefe(monkeypatch, marken, eigene="2026.08.16-13", enabled=True):
    async def fake(_quelle, **_k):
        fassungen = [z for m in marken if (z := version.zerlege(m))]
        return max(marken, key=lambda m: version.zerlege(m) or ()) if fassungen else None

    monkeypatch.setattr(version, "hole_neueste", fake)
    monkeypatch.setattr(version, "get_version", lambda: eigene)
    return asyncio.run(version.pruefe_jetzt(
        {"update": {"enabled": enabled, "source": "cheetahlab/flowbridge"}}
    ))


def test_neuere_fassung_wird_gemeldet(monkeypatch):
    info = _pruefe(monkeypatch, ["latest", "2026.08.16-13", "2026.08.16-14"])
    assert info.status == version.STATUS_UPDATE
    assert info.latest == "2026.08.16-14"


def test_gleiche_fassung_ist_aktuell(monkeypatch):
    info = _pruefe(monkeypatch, ["latest", "2026.08.16-13"])
    assert info.status == version.STATUS_AKTUELL


def test_eigene_neuer_als_registry_ist_kein_update(monkeypatch):
    """Kommt beim Entwickeln vor: lokal gebaut, noch nicht geschoben.
    "Update verfuegbar" waere dann schlicht falsch."""
    info = _pruefe(monkeypatch, ["2026.08.16-12"], eigene="2026.08.16-13")
    assert info.status == version.STATUS_AKTUELL


def test_abgeschaltet_prueft_nicht(monkeypatch):
    gerufen = {"n": 0}

    async def zaehl(*_a, **_k):
        gerufen["n"] += 1
        return "2026.08.16-14"

    monkeypatch.setattr(version, "hole_neueste", zaehl)
    monkeypatch.setattr(version, "get_version", lambda: "2026.08.16-13")
    info = asyncio.run(version.pruefe_jetzt({"update": {"enabled": False, "source": "x/y"}}))
    assert gerufen["n"] == 0, "abgeschaltet heisst: kein Netzzugriff"
    assert info.status == version.STATUS_UNBEKANNT


def test_netzfehler_meldet_unbekannt_nicht_aktuell(monkeypatch):
    """Kein Netz ist KEIN Beleg dafuer, dass man aktuell ist. Ein gruenes
    "Up-to-date" ohne Pruefung waere gelogen - dieselbe Haltung wie beim
    Online-Zustand der Geraete."""
    async def kaputt(*_a, **_k):
        raise OSError("Temporary failure in name resolution")

    monkeypatch.setattr(version, "hole_neueste", kaputt)
    monkeypatch.setattr(version, "get_version", lambda: "2026.08.16-13")
    info = asyncio.run(version.pruefe_jetzt({"update": {"enabled": True, "source": "x/y"}}))
    assert info.status == version.STATUS_UNBEKANNT
    assert "OSError" in (info.detail or "")


def test_check_update_greift_nicht_selbst_ins_netz(monkeypatch):
    """Die Kopfzeile fragt im Sekundentakt. Wuerde check_update() dabei
    abrufen, haetten wir eine Dauerlast gegen Docker Hub gebaut."""
    async def darf_nicht(*_a, **_k):
        raise AssertionError("check_update() darf nicht abrufen")

    monkeypatch.setattr(version, "hole_neueste", darf_nicht)
    assert version.check_update({}).status == version.STATUS_UNBEKANNT


def test_ergebnis_wird_gemerkt(monkeypatch):
    _pruefe(monkeypatch, ["2026.08.16-14"])
    assert version.check_update({}).latest == "2026.08.16-14"

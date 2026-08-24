"""
Melde-Abonnement: Warum FlowBridge seine EcoFlow-Verbindung neu aufbaut,
obwohl sie in Ordnung ist.

Hintergrund (24.08.2026, am eigenen Geraet belegt): Wie oft ein Speicher
seine Messwerte pusht, richtet EcoFlow beim ABONNIEREN ein - und es laeuft
ab. Gemessen: nach dem Verbinden 3,0 s Median-Abstand, nach 37 Stunden
plotzlich 899 s, bei durchgehend stehender Verbindung. Eine frisch
verbundene Instanz war im selben Moment wieder bei 3,0 s.

Getestet wird hier die Entscheidungslogik - nicht das Netz. Der eigentliche
Neuaufbau ist ausgetauscht; es geht darum, WANN er ausgeloest wird und wann
ausdruecklich nicht.
"""
import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import app  # noqa: E402

SN = "TEST-ABO-0001"
CONFIG = {"ecoflow": {"devices": [{"sn": SN}], "access_key": "k", "secret_key": "s"}}


class FakeListener:
    def __init__(self, verbunden: bool = True) -> None:
        self._verbunden = verbunden

    def is_connected(self) -> bool:
        return self._verbunden

    def disconnect(self) -> None:
        self._verbunden = False


@pytest.fixture
def aufrufe(monkeypatch):
    """Neuaufbau abfangen statt durchfuehren - und mitzaehlen."""
    gezaehlt: list[tuple[str, ...]] = []

    async def _falscher_neuaufbau(eco, sns):
        gezaehlt.append(sns)

    monkeypatch.setattr(app, "_erneuere_melde_abo", _falscher_neuaufbau)
    monkeypatch.setattr(app, "_live_listener", FakeListener())
    monkeypatch.setattr(app, "_ecoflow_verbunden_um", time.monotonic())
    monkeypatch.setattr(app, "_melde_abo_erneuert_um", 0.0)
    app._last_seen.pop(SN, None)
    app._reported_offline.discard(SN)
    yield gezaehlt
    app._last_seen.pop(SN, None)
    app._reported_offline.discard(SN)


def _pflegen():
    asyncio.run(app._melde_abo_pflegen(CONFIG))


def _abo_alter_setzen(sekunden: float) -> None:
    app._ecoflow_verbunden_um = time.monotonic() - sekunden


def _letzte_meldung_vor(sekunden: float) -> None:
    app._last_seen[SN] = time.monotonic() - sekunden


# ------------------------------------------------------------ nicht erneuern

def test_frisch_verbunden_und_noch_kein_push(aufrufe):
    """Der erste Push braucht einen Moment - sonst wuerde sich jeder Neustart
    sofort selbst wieder neu verbinden."""
    _pflegen()
    assert aufrufe == []


def test_frische_meldungen_kein_grund(aufrufe):
    _abo_alter_setzen(3600)
    _letzte_meldung_vor(4)
    _pflegen()
    assert aufrufe == []


def test_ohne_verbindung_passiert_nichts(aufrufe, monkeypatch):
    monkeypatch.setattr(app, "_live_listener", None)
    _abo_alter_setzen(99 * 3600)
    _pflegen()
    assert aufrufe == []


def test_abgemeldetes_geraet_wird_nicht_gejagt(aufrufe):
    """Hat sich der Speicher selbst abgemeldet, ist die Stille erklaert - ein
    Neuaufbau wuerde daran nichts aendern, nur alle 30 min Aufrufe kosten."""
    _abo_alter_setzen(3600)
    _letzte_meldung_vor(2 * 3600)
    app._reported_offline.add(SN)
    _pflegen()
    assert aufrufe == []


def test_sperrfrist_verhindert_den_zweiten_versuch(aufrufe):
    _abo_alter_setzen(99 * 3600)
    _pflegen()
    assert len(aufrufe) == 1
    _abo_alter_setzen(99 * 3600)  # Grund besteht weiter
    _pflegen()
    assert len(aufrufe) == 1, "innerhalb der Sperrfrist darf es keinen zweiten geben"


# ---------------------------------------------------------------- erneuern

def test_altes_abo_wird_planmaessig_erneuert(aufrufe):
    _abo_alter_setzen(app.MELDE_ABO_TAKT_S + 60)
    _letzte_meldung_vor(3)  # Meldungen kommen, es geht allein ums Alter
    _pflegen()
    assert aufrufe == [(SN,)]


def test_eingebrochene_melderate_wird_sofort_erneuert(aufrufe):
    """Der Fall vom 23.08.: Verbindung steht, Geraet laedt, aber es kommt
    seit Minuten nichts. Darauf muss nicht erst der halbe Tag vergehen."""
    _abo_alter_setzen(6 * 3600)
    _letzte_meldung_vor(app.MELDE_STILLE_S + 30)
    _pflegen()
    assert aufrufe == [(SN,)]


def test_lange_verbunden_aber_nie_eine_meldung(aufrufe):
    """Abonnieren gescheitert, ohne dass es jemand gemerkt haette."""
    _abo_alter_setzen(app.MELDE_STILLE_S + 60)
    _pflegen()
    assert aufrufe == [(SN,)]


def test_fremde_seriennummer_haelt_das_abo_nicht_kuenstlich_gesund(aufrufe):
    """Nur eingerichtete Geraete zaehlen.

    `_last_seen` kann Seriennummern enthalten, die nicht mehr konfiguriert
    sind. Wuerde deren letzte Meldung mitzaehlen, wiese sie ein abgelaufenes
    Abonnement als gesund aus - der Fall fiel beim Gesamtlauf der Tests auf,
    wo ein anderes Modul seinen Eintrag hinterlassen hatte.
    """
    _abo_alter_setzen(6 * 3600)
    app._last_seen["FREMDE-SN"] = time.monotonic()  # frisch, aber nicht unser Geraet
    try:
        _pflegen()
        assert aufrufe == [(SN,)]
    finally:
        app._last_seen.pop("FREMDE-SN", None)


# ------------------------------------------------------ der Neuaufbau selbst

def test_neuaufbau_trennt_alt_und_baut_neu(monkeypatch):
    """Die alte Verbindung MUSS getrennt werden.

    Sonst haengt am EcoFlow-Broker ein zweiter Client mit derselben
    Client-ID - und der Broker wirft bei gleicher ID den aelteren hinaus.
    Die beiden wuerden sich im Sekundentakt gegenseitig abmelden.
    """
    altes = FakeListener()
    monkeypatch.setattr(app, "_live_listener", altes)
    neues = FakeListener()

    async def _neu_verbinden(eco, sns):
        app._live_listener = neues

    monkeypatch.setattr(app, "_verbinde_ecoflow", _neu_verbinden)
    asyncio.run(app._erneuere_melde_abo(CONFIG["ecoflow"], (SN,)))

    assert altes.is_connected() is False, "alte Verbindung nicht getrennt"
    assert app._live_listener is neues


def test_neuaufbau_ueberlebt_einen_fehler_beim_trennen(monkeypatch):
    """Ein misslungener Abbau darf den Neuaufbau nicht verhindern - sonst
    bliebe FlowBridge ohne Push-Kanal zurueck."""

    class SperrigerListener(FakeListener):
        def disconnect(self):
            raise OSError("Socket schon weg")

    monkeypatch.setattr(app, "_live_listener", SperrigerListener())
    gebaut: list[bool] = []

    async def _neu_verbinden(eco, sns):
        gebaut.append(True)
        app._live_listener = FakeListener()

    monkeypatch.setattr(app, "_verbinde_ecoflow", _neu_verbinden)
    asyncio.run(app._erneuere_melde_abo(CONFIG["ecoflow"], (SN,)))

    assert gebaut == [True]


def test_gescheiterter_neuaufbau_loest_keine_dauerschleife_aus(monkeypatch):
    """Bleibt die Verbindung weg, darf die Pflege nicht bei jedem Takt (5 s)
    einen neuen Versuch starten - dafuer ist _ensure_connected da."""
    monkeypatch.setattr(app, "_live_listener", None)
    monkeypatch.setattr(app, "_ecoflow_verbunden_um", None)
    versuche: list[bool] = []

    async def _mitzaehlen(eco, sns):
        versuche.append(True)

    monkeypatch.setattr(app, "_erneuere_melde_abo", _mitzaehlen)
    _pflegen()
    assert versuche == []


def test_normale_push_luecke_loest_nichts_aus(aufrufe):
    """Bei gesundem Abo wurde die groesste regulaere Luecke mit 5,3 min
    gemessen - die darf keinen Neuaufbau ausloesen."""
    _abo_alter_setzen(6 * 3600)
    _letzte_meldung_vor(5.5 * 60)
    _pflegen()
    assert aufrufe == []

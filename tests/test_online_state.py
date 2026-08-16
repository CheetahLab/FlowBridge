"""Tests fuer die Online/Offline-Ermittlung (app._is_online).

Zwei Faelle waren in frueheren Fassungen falsch und sind hier festgenagelt:

1. "Daten veraltet, aber nie eine ausdrueckliche Offline-Meldung erhalten"
   galt faelschlich als online. Wichtig, weil das /status-Topic nur bei
   Wechseln feuert - bei stillem Verbindungsverlust kommt gar nichts.
   Seit 14.08.2026 ist der Ausgang dieses Falls "unbekannt" statt "offline":
   Der EcoFlow-Push setzt von sich aus minutenlang aus, ohne dass dem Geraet
   etwas fehlt. Nur eine Abmeldung ueber /status belegt "weg".

2. Der REST-Resync (quota/all) wurde als Lebenszeichen gewertet. Das ist
   falsch: EcoFlow beantwortet quota/all aus dem Cloud-Cache und liefert
   auch bei getrenntem Geraet HTTP 200 mit plausiblen Werten. Live
   beobachtet am 12.08.2026 (WLAN-Entzug): /status meldete korrekt offline,
   der naechste REST-Resync setzte es faelschlich zurueck auf online.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import app  # noqa: E402

SN = "TEST-SN-0001"


@pytest.fixture(autouse=True)
def clean_state():
    """Zustand isolieren und einen verbundenen Push-Kanal vortaeuschen."""
    app._last_seen.pop(SN, None)
    app._reported_offline.discard(SN)
    app._quota_cache.pop(SN, None)
    app._state.pop(SN, None)
    original_listener = app._live_listener
    app._live_listener = object()  # nicht None = Push-Kanal steht
    yield
    app._live_listener = original_listener
    app._last_seen.pop(SN, None)
    app._reported_offline.discard(SN)
    app._quota_cache.pop(SN, None)
    app._state.pop(SN, None)


def test_ohne_push_kanal_keine_aussage():
    """Ohne Live-Verbindung darf nicht 'offline' behauptet werden."""
    app._live_listener = None
    assert app._is_online(SN) is None


def test_push_kanal_steht_aber_noch_kein_push():
    assert app._is_online(SN) is None


def test_frischer_push_bedeutet_online():
    app._last_seen[SN] = time.monotonic()
    assert app._is_online(SN) is True


def test_ausdrueckliche_offline_meldung_wirkt_sofort():
    """Ohne dieses Verhalten muesste man STALE_AFTER_SECONDS abwarten."""
    app._last_seen[SN] = time.monotonic()
    app._reported_offline.add(SN)
    assert app._is_online(SN) is False


def test_stille_ohne_abmeldung_ist_unbekannt_nicht_offline():
    """Stiller Verbindungsverlust: /status feuert nur bei Wechseln, hier kommt nichts."""
    """Korrigiert am 14.08.2026 - vorher galt Stille als "offline".

    Der EcoFlow-Push setzt von sich aus aus (gemessene Luecken: 2,5 und 8,6
    Minuten bei 2-4 s Normalabstand), waehrend das Geraet die ganze Zeit da
    ist. "Seit drei Minuten nichts gehoert" ist deshalb kein Beleg fuer
    "weg" - und publish_availability sendet bei None gar nichts, statt eine
    falsche Aussage auf den Broker zu legen.
    """
    app._last_seen[SN] = time.monotonic() - app.STALE_AFTER_SECONDS - 1
    assert app._is_online(SN) is None


def test_abmeldung_schlaegt_stille():
    """Gegenprobe: Meldet sich das Geraet ab, gilt weiterhin offline.

    Ohne diesen Test koennte die Lockerung von oben auch den einen Fall
    verschlucken, in dem FlowBridge wirklich Bescheid weiss."""
    app._last_seen[SN] = time.monotonic() - app.STALE_AFTER_SECONDS - 1
    app._reported_offline.add(SN)
    assert app._is_online(SN) is False


def test_neuer_push_heilt_eine_alte_offline_meldung():
    """Verpasstes Online-Event (z.B. FlowBridge-Neustart) darf nicht dauerhaft haengen."""
    app._reported_offline.add(SN)
    app._apply_quota_update(SN, {"pd.soc": 50}, from_push=True)
    assert SN not in app._reported_offline
    assert app._is_online(SN) is True


def test_rest_resync_hebt_offline_zustand_NICHT_auf():
    """Kernfall: quota/all antwortet auch bei getrenntem Geraet aus dem Cloud-Cache."""
    app._reported_offline.add(SN)
    app._apply_quota_update(SN, {"pd.soc": 50}, from_push=False)
    assert SN in app._reported_offline
    assert app._is_online(SN) is False


def test_rest_resync_haelt_ein_totes_geraet_nicht_kuenstlich_am_leben():
    """Auch ohne /status-Event darf der Resync die Staleness nicht zuruecksetzen.

    Seit 14.08.2026 ist das Ergebnis "unbekannt" statt "offline" - der Punkt
    bleibt aber derselbe: Der REST-Resync darf daraus kein "online" machen."""
    app._last_seen[SN] = time.monotonic() - app.STALE_AFTER_SECONDS - 1
    app._apply_quota_update(SN, {"pd.soc": 50}, from_push=False)
    assert app._is_online(SN) is None


def test_rest_resync_aktualisiert_trotzdem_die_werte():
    """Nicht als Lebenszeichen zaehlen heisst nicht: Daten verwerfen."""
    app._apply_quota_update(SN, {"pd.soc": 42}, from_push=False)
    assert app._state[SN]["soc_percent"] == 42


# ------------------------------------------------- Obergrenze fuer die Stille
# Ergaenzt am 16.08.2026. Die Regel "Stille ist kein Beleg" galt vorher
# unbegrenzt - auch fuer 22 Stunden. Aufgefallen an einem RIVER 2 Pro, der
# sich nach einem Stromausfall wegen Tiefentladung abgeschaltet hatte: Der
# Zustand blieb "unbekannt", publish_availability sendete deshalb nichts, und
# auf dem lokalen Broker stand einen Tag lang weiter `available = online`.


def test_sehr_lange_stille_gilt_doch_als_offline():
    """Ein Geraet, das sich abschaltet, kann sich nicht mehr abmelden.

    Genau dieser Fall fiel vorher durch beide Netze: keine /status-Abmeldung
    (das Funkmodul war stromlos) und keine Staleness-Aussage (Stille galt als
    unbekannt). Die Obergrenze ist das einzige, was ihn faengt."""
    app._last_seen[SN] = time.monotonic() - app.OFFLINE_AFTER_SECONDS - 1
    assert app._is_online(SN) is False


def test_bekannte_push_luecken_bleiben_unter_der_grenze():
    """Gegenprobe zur Obergrenze - sie darf den Normalbetrieb nicht treffen.

    Laengste gemessene Push-Luecke bei laufendem Geraet: 8,6 Minuten
    (14.08.2026). Waere die Grenze zu eng, kaeme das alte Fehlverhalten
    zurueck, nur mit anderer Zahl: 'Speicher offline' bei gesundem Geraet."""
    app._last_seen[SN] = time.monotonic() - 9 * 60
    assert app._is_online(SN) is None
    assert app.OFFLINE_AFTER_SECONDS >= 30 * 60


def test_stille_zwischen_den_grenzen_bleibt_unbekannt():
    """Die mittlere Zone existiert weiter - sie ist der eigentliche Normalfall."""
    app._last_seen[SN] = time.monotonic() - (app.OFFLINE_AFTER_SECONDS // 2)
    assert app._is_online(SN) is None


def test_rest_resync_kann_ein_abgeschaltetes_geraet_nicht_zurueckholen():
    """Der Kernfall vom 16.08.2026 in einer Zeile.

    Die Cloud lieferte die ganze Zeit brav quota/all aus ihrem Cache - jede
    halbe Minute, byte-identische Werte. Wuerde der Resync die Stille
    zuruecksetzen, bliebe das Geraet fuer immer 'online'."""
    app._last_seen[SN] = time.monotonic() - app.OFFLINE_AFTER_SECONDS - 1
    app._apply_quota_update(SN, {"pd.soc": 40}, from_push=False)
    assert app._is_online(SN) is False


def test_stille_sekunden_ohne_push_ist_none():
    """Nie ein Push gesehen ist etwas anderes als 'seit 0 Sekunden still'."""
    assert app._stille_sekunden(SN) is None


def test_stille_sekunden_zaehlt_ab_dem_letzten_push():
    app._last_seen[SN] = time.monotonic() - 7200
    stille = app._stille_sekunden(SN)
    assert stille is not None and 7195 < stille < 7205


def test_stille_steht_nicht_im_status_und_damit_nicht_auf_dem_broker():
    """MqttBridge.publish_state() macht aus jedem Status-Feld ein Topic.

    Eine Sekundenzahl waere dort Dauerrauschen und taeuchte ausserdem im
    EisBaer-Export als neuer Kanal auf. Die Zahl gehoert allein in /api/state."""
    app._apply_quota_update(SN, {"pd.soc": 42}, from_push=True)
    assert "silence_seconds" not in app._state[SN]

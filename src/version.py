"""
Versionsnummer und Update-Zustand.

Schema: JAHR.MONAT.TAG-ZAEHLER, z. B. "2026.08.13-02" - der Zaehler ist der
wievielte Commit des Tages. Geschrieben wird die Datei VERSION im
Projektwurzelverzeichnis vom pre-commit-Hook (scripts/githooks/pre-commit),
damit sie IM Commit steckt und nicht hinterherhinkt.

Bewusst eine Datei und kein `git describe` zur Laufzeit: im Docker-Container
gibt es weder .git noch ein git-Binary.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_VERSION_DATEI = Path(__file__).resolve().parent.parent / "VERSION"
UNBEKANNT = "0000.00.00-00"

# Update-Zustaende. "unknown" ist der ehrliche Startwert: solange keine Quelle
# eingerichtet ist, weiss FlowBridge NICHT, ob es aktuell ist - und "aktuell"
# zu behaupten waere schlimmer als zuzugeben, dass nicht geprueft wurde.
STATUS_UNBEKANNT = "unknown"
STATUS_AKTUELL = "current"
STATUS_UPDATE = "update"


def get_version() -> str:
    try:
        text = _VERSION_DATEI.read_text(encoding="utf-8").strip()
        return text or UNBEKANNT
    except OSError:
        # Kein Grund, deswegen die Oberflaeche scheitern zu lassen.
        logger.warning("VERSION-Datei nicht lesbar (%s) - melde unbekannt.", _VERSION_DATEI)
        return UNBEKANNT


@dataclass
class UpdateInfo:
    status: str
    current: str
    latest: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "current": self.current,
            "latest": self.latest,
            "detail": self.detail,
        }


def zerlege(marke: str) -> tuple[int, ...] | None:
    """"2026.08.16-13" -> (2026, 8, 16, 13). None, wenn es keine Fassung ist.

    ZAHLEN, nicht Zeichenketten. Als Text verglichen waere "-100" kleiner als
    "-99", weil "1" vor "9" kommt - und der Zaehler ist die Zahl der Commits
    des Tages. Am 16.08.2026 standen wir bei dreizehn; dreistellig ist keine
    Fantasie, sondern eine Frage der Zeit.

    Gibt None fuer alles, was nicht dem Schema folgt - vor allem fuer
    "latest", das in jeder Tag-Liste steht und sonst als Fassung durchginge.
    """
    passt = re.fullmatch(r"(\d{4})\.(\d{2})\.(\d{2})-(\d+)", marke.strip())
    return tuple(int(t) for t in passt.groups()) if passt else None


async def hole_neueste(quelle: str, timeout: float = 8.0) -> str | None:
    """Neueste Fassung aus der oeffentlichen Tag-Liste von Docker Hub.

    ANONYM - das ist der Grund, warum die Quelle Docker Hub ist und nicht
    GHCR. Dort braucht schon das blosse Auflisten der Tags erst ein Token,
    und ein Token laesst sich nicht in ein oeffentliches Abbild legen.

    Uebertragen wird dabei NICHTS ueber das Geraet: ein GET auf eine
    oeffentliche Liste. Sichtbar wird die IP-Adresse des Anfragenden - und
    genau deshalb ist die Pruefung abschaltbar und in der Hilfe erklaert.
    """
    url = f"https://hub.docker.com/v2/repositories/{quelle}/tags"
    async with httpx.AsyncClient(timeout=timeout) as client:
        antwort = await client.get(url, params={"page_size": 100})
        antwort.raise_for_status()
        marken = [t.get("name", "") for t in (antwort.json().get("results") or [])]

    # Nach der zerlegten Fassung sortieren, nicht nach dem Datum von Docker
    # Hub: Ein nachtraeglich neu geschobener alter Tag waere dort der
    # "neueste", ohne es zu sein.
    fassungen = [(z, m) for m in marken if (z := zerlege(m))]
    return max(fassungen)[1] if fassungen else None


# Ergebnis der letzten Pruefung. Der Abruf laeuft im Hintergrund (Start, dann
# im Takt) und NICHT in check_update(): Die Oberflaeche fragt den Zustand alle
# paar Sekunden ab - ein HTTP-Aufruf an dieser Stelle haette daraus eine
# Dauerlast gegen Docker Hub gemacht.
_letzte: UpdateInfo | None = None


async def pruefe_jetzt(config: dict | None = None) -> UpdateInfo:
    """Einmal wirklich nachsehen und das Ergebnis merken."""
    global _letzte
    aktuell = get_version()
    bereich = (config or {}).get("update") or {}
    quelle = bereich.get("source")

    if not bereich.get("enabled", True):
        _letzte = UpdateInfo(status=STATUS_UNBEKANNT, current=aktuell,
                             detail="Update-Pruefung ist abgeschaltet.")
        return _letzte
    if not quelle:
        _letzte = UpdateInfo(status=STATUS_UNBEKANNT, current=aktuell)
        return _letzte

    try:
        neueste = await hole_neueste(quelle)
    except Exception as exc:
        # Kein Netz ist kein Grund, "aktuell" zu behaupten - und auch keiner,
        # die Oberflaeche scheitern zu lassen. Der Zustand bleibt ehrlich
        # unbekannt, mit dem Grund im Text.
        logger.warning("Update-Pruefung fehlgeschlagen: %s", exc)
        _letzte = UpdateInfo(status=STATUS_UNBEKANNT, current=aktuell,
                             detail=f"Nicht erreichbar: {exc.__class__.__name__}")
        return _letzte

    hier, dort = zerlege(aktuell), zerlege(neueste or "")
    if neueste is None or dort is None or hier is None:
        # Etwa ein Abbild ohne Versions-Hook gebaut: Dann laesst sich nicht
        # vergleichen, und das zuzugeben ist besser als zu raten.
        _letzte = UpdateInfo(status=STATUS_UNBEKANNT, current=aktuell, latest=neueste,
                             detail="Fassung nicht vergleichbar.")
        return _letzte

    _letzte = UpdateInfo(
        status=STATUS_UPDATE if dort > hier else STATUS_AKTUELL,
        current=aktuell,
        latest=neueste,
    )
    return _letzte


def check_update(config: dict | None = None) -> UpdateInfo:
    """Zustand der letzten Pruefung - ohne selbst zu pruefen.

    Bewusst synchron und ohne Netzzugriff: Die Kopfzeile der Oberflaeche
    fragt im Sekundentakt, der eigentliche Abruf gehoert deshalb in den
    Hintergrund (siehe pruefe_jetzt).
    """
    return _letzte or UpdateInfo(status=STATUS_UNBEKANNT, current=get_version())

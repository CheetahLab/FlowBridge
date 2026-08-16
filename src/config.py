"""
FlowBridge-Konfiguration: Laden/Schreiben von config.yaml.

Wird zur Laufzeit ueber das Setup-UI befuellt (Access-/Secret-Key, Geraete-SN,
lokale Broker-IP) – siehe app.py /api/setup. Kein Live-Reload: eine Aenderung
greift beim naechsten Poll-Zyklus bzw. nach Neustart des Pollers.
"""
from __future__ import annotations

import copy
import os
import secrets
from pathlib import Path
from typing import Any

import yaml

# Mindestlaenge der MQTT-Client-ID. Kommt nicht aus dem MQTT-Standard, sondern
# vom EisBaer: der verlangt zehn Zeichen. Wer eine kuerzere vergibt, merkt es
# sonst erst beim Import drueben.
MIN_CLIENT_ID_LAENGE = 10

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def config_path() -> Path:
    """Oeffentlich, weil auch das Diagnose-Protokoll neben der Konfiguration
    liegen soll - dasselbe Verzeichnis ist im Container schon gemountet."""
    return _config_path()


def _config_path() -> Path:
    # FLOWBRIDGE_CONFIG umschaltbar (Container: /config/config.yaml), Default ist
    # das Repo-Root fuer lokale Entwicklung ausserhalb von Docker.
    env = os.environ.get("FLOWBRIDGE_CONFIG", "")
    return Path(env) if env else _DEFAULT_CONFIG_PATH

DEFAULT_CONFIG: dict[str, Any] = {
    "ecoflow": {
        "access_key": "",
        "secret_key": "",
        "devices": [],  # Liste von {"sn": "...", "name": "..."}
    },
    # Feldinventar: laeuft dauerhaft mit und haelt fest, welche Felder
    # EcoFlow ueber die Zeit wirklich liefert. Getrennt von "diagnostics" -
    # das eine sucht einen Fehler, das andere beobachtet ueber Monate.
    "analysis": {"enabled": False},
    # Kennzeichnet DIESE Installation. Wird beim ersten Zugriff einmalig
    # erzeugt und bleibt dann stehen. Zweck: Zwei FlowBridges am selben Broker
    # duerfen sich nicht dieselbe Client-ID teilen - MQTT wirft bei gleicher
    # ID den aelteren Client hinaus, und beide melden sich im Wechsel ab.
    "instance_id": "",
    "mqtt": {
        "host": "",
        "port": 1883,
        # Leer heisst "automatisch" (flowbridge-<instance_id>). Ein fester
        # Vorgabewert waere hier falsch: Zwei Installationen am selben Broker
        # haetten dann garantiert dieselbe ID.
        "client_id": "",
        "username": "",
        "password": "",
        "base_topic": "flowbridge",
        "retain": True,
        "poll_interval_seconds": 30,
    },
    "ui": {
        "language": "de",
        "theme": "dark",
    },
    # Diagnose-Protokoll. Aus, bis es jemand einschaltet - der Ringpuffer im
    # Speicher laeuft davon unabhaengig immer mit.
    "diagnostics": {"enabled": False},
    # Update-Pruefung gegen die oeffentliche Tag-Liste auf Docker Hub.
    #
    # AN als Vorgabe, anders als bei "analysis" und "diagnostics". Der
    # Unterschied ist der Zweck: Jene sammeln Daten und laufen deshalb erst
    # auf Zuruf. Diese holt nur eine oeffentliche Liste ab und schickt dabei
    # nichts ueber das Geraet - und ein Update-Hinweis, den niemand sieht,
    # weil die Pruefung aus ist, verfehlt genau seinen Zweck.
    #
    # Was dabei sichtbar wird, steht in der Oberflaeche: eine IP-Adresse und
    # damit, dass dort FlowBridge laeuft. Wem das zu viel ist, schaltet ab.
    "update": {
        "enabled": True,
        # Ueberschreibbar, falls das Abbild einmal woanders liegt.
        "source": "cheetahlab/flowbridge",
    },
    # Zugriffsschutz. Leer = noch nicht eingerichtet; dann verlangt die
    # Oberflaeche als Erstes ein Passwort. Hier steht NIE ein Klartext-
    # Passwort, nur Salz und Hash (siehe auth.py).
    "auth": {},
    "homeassistant": {
        # Discovery-Topics anlegen, damit HA die Geraete selbst findet.
        # Abschaltbar, weil sie sonst auch auf Brokern ohne Home Assistant
        # als retained Topics liegen bleiben.
        "discovery": True,
        "discovery_prefix": "homeassistant",
    },
    # Sollwerte, die EcoFlow nicht zurueckliefert (AC-Ladeleistung, Lade-Pause).
    # Ohne diese Ablage waeren sie nach jedem Neustart wieder "unbekannt".
    # Struktur: {"<SN>": {"charge_power_watts": 300, "ac_charging_enabled": true}}
    "last_setpoints": {},
}


def read_setpoints() -> dict[str, dict[str, Any]]:
    return load_config().get("last_setpoints") or {}


def write_setpoint(sn: str, key: str, value: Any) -> None:
    """Einen gemerkten Sollwert speichern.

    Liest die Datei vorher frisch ein, damit ein parallel ueber das Setup-UI
    geaenderter Wert nicht ueberschrieben wird.
    """
    config = load_config()
    setpoints = dict(config.get("last_setpoints") or {})
    geraet = dict(setpoints.get(sn) or {})
    geraet[key] = value
    setpoints[sn] = geraet
    config["last_setpoints"] = setpoints
    write_config(config)


# Zwischenspeicher: (pfad, mtime, groesse) -> geparste Konfiguration.
# Der Zugriffsschutz prueft bei JEDER Anfrage, und das Dashboard fragt im
# Sekundentakt - ohne diesen Zwischenspeicher waere das dauerndes
# YAML-Parsen derselben unveraenderten Datei.
# Schluessel ist bewusst mtime UND Groesse: eine Aenderung innerhalb derselben
# Zeitstempel-Aufloesung faellt sonst durchs Raster.
_cache: tuple[tuple, dict[str, Any]] | None = None


def invalidate_cache() -> None:
    global _cache
    _cache = None


def load_config() -> dict[str, Any]:
    global _cache
    path = _config_path()
    # deepcopy statt .copy(): Eine flache Kopie teilt die verschachtelten
    # Dicts mit DEFAULT_CONFIG. /api/setup schreibt direkt in
    # config["mqtt"]["host"] - und haette damit die Vorgabewerte des Moduls
    # mitsamt echter Zugangsdaten fuer die Laufzeit ueberschrieben.
    if not path.exists():
        return copy.deepcopy(DEFAULT_CONFIG)
    stat = path.stat()
    schluessel = (str(path), stat.st_mtime_ns, stat.st_size)
    if _cache and _cache[0] == schluessel:
        return copy.deepcopy(_cache[1])
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    merged = copy.deepcopy(DEFAULT_CONFIG)
    for schluessel_oben, wert in data.items():
        # Abschnittsweise mischen statt ersetzen: Eine config.yaml, in der ein
        # Unterschluessel fehlt (aeltere Fassung, von Hand bearbeitet), verlor
        # sonst dessen Vorgabewert - bei "client_id" fuehrte das direkt in
        # einen KeyError beim Verbinden.
        if isinstance(wert, dict) and isinstance(merged.get(schluessel_oben), dict):
            merged[schluessel_oben].update(wert)
        else:
            merged[schluessel_oben] = wert
    _cache = (schluessel, merged)
    return copy.deepcopy(merged)


def instanz_id() -> str:
    """Kennung dieser Installation - einmalig erzeugt, danach unveraendert.

    Sie steckt in der Client-ID beider MQTT-Verbindungen. Ohne sie traegen
    zwei FlowBridges dieselbe Kennung, und ein MQTT-Broker wirft bei gleicher
    Kennung den aelteren Client hinaus - die beiden melden sich dann
    gegenseitig im Sekundentakt ab.
    """
    config = load_config()
    vorhanden = (config.get("instance_id") or "").strip()
    if vorhanden:
        return vorhanden
    neu = secrets.token_hex(3)  # sechs Zeichen genuegen, die ID ist kein Geheimnis
    config["instance_id"] = neu
    try:
        write_config(config)
    except OSError:
        # Nicht beschreibbar: Dann gilt die Kennung eben nur bis zum Neustart.
        # Besser als hier auszusteigen - der Speicherfehler wird an anderer
        # Stelle bereits im Klartext gemeldet.
        pass
    return neu


def standard_client_id() -> str:
    """Vorgabe fuer die lokale Client-ID: flowbridge-<instanz>, 17 Zeichen.

    Damit ueber der EisBaer-Mindestlaenge von zehn Zeichen.
    """
    return f"flowbridge-{instanz_id()}"


def schreibprobe() -> str | None:
    """Prueft, ob der Datenordner beschreibbar ist.

    None heisst "alles gut", sonst kommt der Grund im Klartext zurueck.

    Warum ueberhaupt: Auf einer Synology gehoert der gemountete Ordner dem
    NAS-Benutzer, FlowBridge laeuft als Benutzer 1000. Frueher flog beim
    ersten Schreibversuch waehrend des Starts eine OSError durch die
    Lifespan, uvicorn beendete sich, Docker startete neu - eine Dauerschleife,
    von der im Browser nichts zu sehen war. Der Einstiegspunkt raeumt das
    inzwischen aus; scheitert es doch (etwa bei einem schreibgeschuetzt
    eingebundenen Ordner), soll es SICHTBAR scheitern statt still.
    """
    ordner = _config_path().parent
    probe = ordner / ".flowbridge-schreibprobe"
    try:
        ordner.mkdir(parents=True, exist_ok=True)
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return f"{ordner}: {exc.strerror or exc}"
    return None


def write_config(config: dict[str, Any]) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
    # Ausdruecklich verwerfen: auf manchen Dateisystemen ist die
    # mtime-Aufloesung zu grob, um ein Schreiben direkt nach einem Lesen
    # zu bemerken.
    invalidate_cache()


MASK_PLACEHOLDER = "••••••••"


def mask_secrets(config: dict[str, Any]) -> dict[str, Any]:
    """Fuer GET /api/config: Secret-Key nie im Klartext ans Frontend geben."""
    masked = {**config}
    if masked.get("ecoflow", {}).get("secret_key"):
        masked["ecoflow"] = {**masked["ecoflow"], "secret_key": MASK_PLACEHOLDER}
    if masked.get("mqtt", {}).get("password"):
        masked["mqtt"] = {**masked["mqtt"], "password": MASK_PLACEHOLDER}
    # Der auth-Block wird KOMPLETT entfernt, nicht maskiert: Passwort-Hash,
    # Salz und Sitzungsgeheimnis haben im Frontend nichts verloren. Mit dem
    # Sitzungsgeheimnis liessen sich beliebige gueltige Token bauen.
    masked.pop("auth", None)
    return masked

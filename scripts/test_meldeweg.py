"""
Messung: Gibt es einen Abrufweg, der FRISCHE Werte liefert - oder spiegeln
alle nur den letzten Push des Geraets?

HINTERGRUND (23.08.2026, im Feld gemessen)
------------------------------------------
Die Melderate des River 2 Pro haengt daran, ob die EcoFlow-App offen ist:

    App zu   9 Meldungen in 14,8 min (groesste Luecke 4,2 min)
    App auf  86 Meldungen in  4,2 min (Median-Abstand 3 s)

Umgeschaltet wird es von einer Serie `setReportCfg`-Nachrichten, die die App
schickt. Ist sie zu, steht im Dashboard minutenlang ein alter Wert - und
`quota/all` hilft nicht, weil EcoFlow es aus dem Cloud-Cache beantwortet, der
seinerseits nur den letzten Push spiegelt (zwanzig Abfragen, immer dieselben
105 W, waehrend das Geraet laengst mit 200 W lud).

WAS DIESES SKRIPT MISST
-----------------------
Die Doku kennt neben `quota/all` einen GEZIELTEN Abruf einzelner Felder
(POST /iot-open/sign/device/quota mit einer `quotas`-Liste). Ob der aus
demselben Cache kommt oder das Geraet wirklich fragt, steht nirgends. Also
messen statt annehmen: Beide Wege im Wechsel abfragen und vergleichen.

    beide immer gleich        -> derselbe Cache, kein Gewinn
    gezielt aendert sich frueher -> echter Abrufweg gefunden

AUFRUF (bei GESCHLOSSENER EcoFlow-App - sonst misst man die App)
----------------------------------------------------------------
    python scripts/test_meldeweg.py                 # Keys aus config.yaml
    python scripts/test_meldeweg.py <access> <secret> <sn>
    python scripts/test_meldeweg.py --runden 40 --takt 10

Im Container (dort liegt die gueltige config.yaml schon):
    docker cp scripts/test_meldeweg.py flowbridge:/app/src/test_meldeweg.py
    docker exec flowbridge python /app/src/test_meldeweg.py --runden 40 --takt 10

Auf einer Synology ohne SSH: Datei per File Station in den Datenordner
legen (neben die config.yaml), dann im Container Manager ein Terminal
oeffnen und starten:
    python /config/test_meldeweg.py --runden 40 --takt 10

Aussagekraeftig wird es, wenn sich zwischendurch wirklich etwas AENDERT -
also am besten waehrend des Ladens laufen lassen und die Ladeleistung einmal
umstellen. Ein Geraet im Leerlauf meldet ueberall dieselbe 0.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# FlowBridge-Module finden, egal wo das Skript liegt.
#
# Zwei Orte, weil es zwei Wege gibt: aus dem Repo heraus (dann liegt src/
# eine Ebene hoeher) und im Container. Dort landet die Datei je nach Weg in
# /app/src (docker cp) oder in /config (per File Station in den gemounteten
# Datenordner gelegt - auf einer Synology der Weg ohne SSH). Ohne den
# zweiten Kandidaten scheitert genau dieser Weg schon am Import.
for _kandidat in (Path(__file__).resolve().parent.parent / "src", Path("/app/src")):
    if (_kandidat / "ecoflow_client.py").exists():
        sys.path.insert(0, str(_kandidat))
        break

from config import config_path  # noqa: E402
from ecoflow_client import EcoFlowApiError, EcoFlowAuthError, EcoFlowClient  # noqa: E402

# Felder, die sich im Betrieb bewegen - an unveraenderlichen Sollwerten waere
# nicht zu erkennen, ob ein Abrufweg frisch ist.
BEOBACHTET = [
    "inv.inputWatts",
    "bms_bmsStatus.inputWatts",
    "pd.soc",
    "pd.wattsOutSum",
]


def _aus_config() -> tuple[str, str, str] | None:
    """Zugangsdaten aus der config.yaml, die FlowBridge selbst benutzt.

    Ueber config.config_path() statt ueber einen selbst gebauten Pfad: Damit
    findet das Skript die Konfiguration auch IM CONTAINER (dort steht
    FLOWBRIDGE_CONFIG auf /config/config.yaml). Das ist der bequemste Weg zu
    gueltigen Schluesseln - im Repo liegt schnell mal ein abgeloestes Paar.
    """
    pfad = config_path()
    if not pfad.exists():
        return None
    try:
        import yaml

        cfg = yaml.safe_load(pfad.read_text(encoding="utf-8")) or {}
        eco = cfg.get("ecoflow") or {}
        geraete = eco.get("devices") or []
        if eco.get("access_key") and eco.get("secret_key") and geraete:
            return eco["access_key"], eco["secret_key"], geraete[0]["sn"]
    except Exception as exc:  # noqa: BLE001 - Bequemlichkeit, kein Muss
        print(f"({pfad} nicht auswertbar: {exc})")
    return None


def _kurz(feld: str) -> str:
    """"bms_bmsStatus.inputWatts" -> "bms.inputWatts".

    Nur der letzte Namensteil genuegt nicht: `inv.inputWatts` und
    `bms_bmsStatus.inputWatts` haetten dann beide die Ueberschrift
    "inputWatts", und die Tabelle waere nicht mehr lesbar.
    """
    modul, _, rest = feld.partition(".")
    return f"{modul.split('_')[0]}.{rest}"


def _uhr() -> str:
    return datetime.now().strftime("%H:%M:%S")


async def main() -> None:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("zugang", nargs="*", help="access_key secret_key sn")
    parser.add_argument("--runden", type=int, default=30)
    parser.add_argument("--takt", type=float, default=15.0, help="Sekunden zwischen zwei Runden")
    args = parser.parse_args()

    if len(args.zugang) == 3:
        access_key, secret_key, sn = args.zugang
    else:
        aus_datei = _aus_config()
        if not aus_datei:
            print("Zugangsdaten fehlen: entweder config.yaml daneben legen oder "
                  "access_key secret_key sn als Argumente uebergeben.")
            return
        access_key, secret_key, sn = aus_datei
        print(f"Zugangsdaten aus config.yaml, Geraet {sn}")

    client = EcoFlowClient(access_key, secret_key)

    print(f"\n{args.runden} Runden im Abstand von {args.takt:g} s "
          f"({args.runden * args.takt / 60:.1f} min). EcoFlow-App bitte geschlossen halten.\n")
    kopf = f"{'Zeit':>8}  {'Weg':<8}  " + "  ".join(f"{_kurz(f):>16}" for f in BEOBACHTET)
    print(kopf)
    print("-" * len(kopf))

    vorher: dict[str, dict] = {"all": {}, "gezielt": {}}
    aenderungen = {"all": 0, "gezielt": 0}
    unterschiede = 0
    gelungen = 0
    fehler = 0

    for runde in range(args.runden):
        if runde:
            await asyncio.sleep(args.takt)
        stand: dict[str, dict] = {}
        try:
            stand["all"] = await client.get_quota_all(sn)
            stand["gezielt"] = await client.get_quota(sn, BEOBACHTET)
        except (EcoFlowAuthError, EcoFlowApiError) as exc:
            print(f"{_uhr():>8}  FEHLER: {exc}")
            fehler += 1
            continue
        gelungen += 1

        for weg in ("all", "gezielt"):
            werte = {f: stand[weg].get(f) for f in BEOBACHTET}
            geaendert = any(vorher[weg].get(f) != v for f, v in werte.items()) if vorher[weg] else False
            if geaendert:
                aenderungen[weg] += 1
            marke = " *" if geaendert else "  "
            spalten = "  ".join(f"{str(werte[f]):>16}" for f in BEOBACHTET)
            print(f"{_uhr():>8}  {weg:<8}{marke}{spalten}")
            vorher[weg] = werte

        if any(stand["all"].get(f) != stand["gezielt"].get(f) for f in BEOBACHTET):
            unterschiede += 1
            print(f"{'':>8}  --> UNTERSCHIED zwischen beiden Wegen in dieser Runde")

    print("\n--- Ergebnis ---")
    # Ohne eine einzige gelungene Runde gibt es nichts zu deuten. Der Satz
    # "beide Wege liefern dasselbe" waere sonst ausgerechnet dann zu lesen,
    # wenn gar nichts abgerufen werden konnte.
    if not gelungen:
        print(f"Keine einzige Runde erfolgreich ({fehler} Fehlversuche) - "
              "erst die Zugangsdaten klaeren, dann messen.")
        return
    print(f"{gelungen} von {args.runden} Runden erfolgreich.")
    print(f"Runden mit Wertaenderung: quota/all {aenderungen['all']}, "
          f"gezielter Abruf {aenderungen['gezielt']}")
    print(f"Runden, in denen sich beide Wege unterschieden: {unterschiede}")
    if unterschiede == 0 and aenderungen["all"] == aenderungen["gezielt"]:
        print("Deutung: beide Wege liefern dasselbe - derselbe Cloud-Cache, kein Gewinn.")
    else:
        print("Deutung: die Wege unterscheiden sich - der gezielte Abruf lohnt naeheres Hinsehen.")


if __name__ == "__main__":
    asyncio.run(main())

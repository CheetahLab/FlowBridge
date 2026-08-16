"""
Standalone-Testscript: EcoFlow Access-/Secret-Key + Geraete-SN pruefen und
den kompletten quota/all-Dump ausgeben.

Zweck: einmalig sehen, welche Felder ein echtes Geraet (z.B. River 2 Pro)
tatsaechlich liefert, um src/device.py (_METRIC_CANDIDATES) zu verifizieren.
Laeuft unabhaengig vom Rest von FlowBridge, braucht kein MQTT, keine config.yaml.

Aufruf:
    pip install httpx
    python scripts/test_quota.py <access_key> <secret_key> <device_sn>

Oder interaktiv (Werte werden abgefragt, wenn nicht als Argument uebergeben):
    python scripts/test_quota.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Erlaubt den Import von src/ecoflow_client.py, ohne das Projekt zu installieren.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from commands_river2 import CommandError, apply_command  # noqa: E402
from ecoflow_client import EcoFlowApiError, EcoFlowAuthError, EcoFlowClient  # noqa: E402


def _arg_or_prompt(args: list[str], index: int, prompt: str) -> str:
    if index < len(args):
        return args[index]
    # Bewusst kein getpass(): in manchen Terminals (u.a. VS-Code-Integrated-Terminal
    # unter Windows) blockiert die versteckte Eingabe das Einfuegen per Ctrl+V/Rechtsklick.
    # Fuer ein lokales Einmal-Testscript ist Klartext-Eingabe hier vertretbar.
    return input(f"{prompt}: ").strip()


async def main() -> None:
    args = sys.argv[1:]
    access_key = _arg_or_prompt(args, 0, "EcoFlow Access-Key")
    secret_key = _arg_or_prompt(args, 1, "EcoFlow Secret-Key")
    sn = _arg_or_prompt(args, 2, "Geraete-Seriennummer (SN)")

    client = EcoFlowClient(access_key, secret_key)

    print("\n--- Schritt 1: Zugangsdaten pruefen (Zertifikat-Endpoint) ---")
    try:
        cert = await client.get_mqtt_certificate()
        print(f"OK – EcoFlow-Broker: {cert.url}:{cert.port} (Account: {cert.account})")
    except EcoFlowAuthError as exc:
        print(f"FEHLER: Access-/Secret-Key abgelehnt – {exc}")
        return
    except EcoFlowApiError as exc:
        print(f"FEHLER: {exc}")
        return

    print(f"\n--- Schritt 2: quota/all fuer SN {sn} ---")
    try:
        quota = await client.get_quota_all(sn)
    except EcoFlowAuthError as exc:
        print(f"FEHLER: Auth-Problem bei quota/all – {exc}")
        return
    except EcoFlowApiError as exc:
        print(f"FEHLER: {exc} (falsche SN? Geraet offline?)")
        return

    print(f"\n{len(quota)} Felder erhalten:\n")
    print(json.dumps(quota, indent=2, ensure_ascii=False, sort_keys=True))

    out_path = Path(__file__).resolve().parent / f"quota_dump_{sn}.json"
    out_path.write_text(json.dumps(quota, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(f"\nDump zusaetzlich gespeichert in: {out_path}")
    print("(Diese Datei bitte NICHT committen – enthaelt evtl. geraetespezifische Details.)")

    current_limit = quota.get("bms_emsStatus.maxChargeSoc")
    if current_limit is None:
        print("\n(Kein Set-Befehl-Test moeglich – bms_emsStatus.maxChargeSoc fehlt im Dump.)")
        return

    print("\n--- Schritt 3 (optional): Set-Befehl testen ---")
    print(
        f"Aktuelles Charge-Limit ist {current_limit}%. Ein Test wuerde es auf denselben "
        "Wert zuruecksetzen (folgenlos, aber sendet einen echten Set-Befehl ans Geraet)."
    )
    answer = input("Set-Befehl-Signatur jetzt testen? (j/N): ").strip().lower()
    if answer != "j":
        print("Uebersprungen.")
        return

    try:
        result = await apply_command(client, sn, "charge_limit_percent", str(current_limit))
        print(f"OK – EcoFlow-Antwort: {result}")
    except (CommandError, EcoFlowAuthError, EcoFlowApiError) as exc:
        print(f"FEHLER beim Set-Befehl: {exc}")


if __name__ == "__main__":
    asyncio.run(main())

"""
Standalone-Capture: hoert eine Weile am EcoFlow-MQTT-Broker mit und listet
auf, WELCHE Felder je Modul (typeCode) tatsaechlich gepusht werden.

Zweck: herausfinden, was der Live-Push ueber quota/all hinaus liefert -
Grundlage fuer neue Metriken in src/device.py. quota/all ist eine kuratierte
20-Feld-Liste; der Push kann mehr enthalten (und schickt Felder modulweise
mit un-praefigierten Namen).

Hoert bewusst ROH mit (eigener paho-Client, nicht ueber EcoFlowMqttListener),
damit auch typeCodes auftauchen, die src/ecoflow_mqtt.py noch nicht kennt -
genau die waeren ja das Interessante.

Aufruf:
    python scripts/capture_mqtt.py <access_key> <secret_key> <device_sn> [sekunden]

Ohne Argumente werden die Werte interaktiv abgefragt (Default: 120 Sekunden).
Laenger laufen lassen sieht mehr: manche Felder werden nur bei Aenderungen
oder in groesseren Abstaenden gepusht.
"""
from __future__ import annotations

import asyncio
import json
import ssl
import sys
import time
from collections import defaultdict
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ecoflow_client import EcoFlowApiError, EcoFlowAuthError, EcoFlowClient  # noqa: E402

# typeCode -> feldname -> {"count": n, "values": [...]}
seen: dict[str, dict[str, dict]] = defaultdict(
    lambda: defaultdict(lambda: {"count": 0, "values": []})
)
module_types: dict[str, set] = defaultdict(set)  # typeCode -> {moduleType, ...}
message_count = 0
no_typecode: list[str] = []  # Nachrichten ohne typeCode (z.B. instructCode-Meldungen)


def _arg_or_prompt(args: list[str], index: int, prompt: str) -> str:
    if index < len(args):
        return args[index]
    return input(f"{prompt}: ").strip()


def _on_message(_client, _userdata, msg) -> None:
    global message_count
    message_count += 1
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return

    type_code = payload.get("typeCode")
    params = payload.get("params")
    if not type_code:
        summary = json.dumps({k: v for k, v in payload.items() if k != "params"}, sort_keys=True)
        if summary not in no_typecode:
            no_typecode.append(summary)
        return
    if not isinstance(params, dict):
        return

    if "moduleType" in payload:
        module_types[type_code].add(payload["moduleType"])

    for field, value in params.items():
        entry = seen[type_code][field]
        entry["count"] += 1
        if value not in entry["values"]:
            entry["values"].append(value)
            del entry["values"][6:]


async def main() -> None:
    args = sys.argv[1:]
    access_key = _arg_or_prompt(args, 0, "EcoFlow Access-Key")
    secret_key = _arg_or_prompt(args, 1, "EcoFlow Secret-Key")
    sn = _arg_or_prompt(args, 2, "Geraete-Seriennummer (SN)")
    duration = int(args[3]) if len(args) > 3 else 120

    client = EcoFlowClient(access_key, secret_key)
    try:
        cert = await client.get_mqtt_certificate()
    except (EcoFlowAuthError, EcoFlowApiError) as exc:
        print(f"FEHLER: {exc}")
        return

    print(f"Verbinde mit {cert.url}:{cert.port} und hoere {duration}s mit ...")
    print("(Tipp: waehrenddessen am Geraet/in der App etwas schalten - dann tauchen")
    print(" auch Felder auf, die nur bei Aenderungen gepusht werden.)\n")

    mqttc = mqtt.Client(
        client_id=f"flowbridge-capture-{cert.account[-12:]}",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    mqttc.username_pw_set(cert.account, cert.password)
    if cert.protocol == "mqtts":
        mqttc.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    mqttc.on_message = _on_message
    # Subscribe erst nach on_connect - vorher schlaegt es still fehl (MQTT_ERR_NO_CONN).
    mqttc.on_connect = lambda c, *_: c.subscribe(f"/open/{cert.account}/{sn}/quota")
    mqttc.connect(cert.url, cert.port, keepalive=30)
    mqttc.loop_start()

    start = time.time()
    while time.time() - start < duration:
        await asyncio.sleep(10)
        elapsed = int(time.time() - start)
        fields = sum(len(f) for f in seen.values())
        print(f"  [{elapsed:>3}s] {message_count} Nachrichten, {fields} verschiedene Felder")

    mqttc.loop_stop()
    mqttc.disconnect()

    print("\n" + "=" * 78)
    print(f"ERGEBNIS nach {duration}s: {message_count} Nachrichten")
    print("=" * 78)

    for type_code in sorted(seen):
        mods = ", ".join(str(m) for m in sorted(module_types.get(type_code, [])))
        print(f"\n## {type_code}  (moduleType {mods}) - {len(seen[type_code])} Felder")
        for field in sorted(seen[type_code]):
            entry = seen[type_code][field]
            values = ", ".join(str(v) for v in entry["values"])
            print(f"  {field:<26} {entry['count']:>4}x   Werte: {values}")

    if no_typecode:
        print("\n## Nachrichten OHNE typeCode (ignoriert von ecoflow_mqtt.py):")
        for summary in no_typecode:
            print(f"  {summary}")

    out_path = Path(__file__).resolve().parent / f"mqtt_fields_{sn}.json"
    dump = {tc: dict(fields) for tc, fields in seen.items()}
    out_path.write_text(
        json.dumps(dump, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    print(f"\nDetails gespeichert in: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())

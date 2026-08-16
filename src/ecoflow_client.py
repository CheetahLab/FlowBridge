"""
EcoFlow IoT Open Platform – REST-Client.

Kapselt ausschliesslich die EcoFlow-spezifische Kommunikation (HMAC-Signierung,
Zertifikat-Abruf, Quota-Abfrage). Kennt weder MQTT noch das FlowBridge-Web-UI –
siehe mqtt_bridge.py fuer die Weiterverarbeitung.

Signier-Verfahren laut EcoFlow IoT-Open-API: alle Query-/Body-Parameter
alphabetisch sortiert, als "key=value&..." verkettet, um accessKey/nonce/
timestamp ergaenzt, mit HMAC-SHA256 gegen den secretKey signiert.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_HOST = "https://api-e.ecoflow.com"
CERT_PATH = "/iot-open/sign/certification"
DEVICE_LIST_PATH = "/iot-open/sign/device/list"
QUOTA_ALL_PATH = "/iot-open/sign/device/quota/all"
QUOTA_PATH = "/iot-open/sign/device/quota"


class EcoFlowAuthError(Exception):
    """Access-/Secret-Key falsch oder abgelehnt."""


class EcoFlowApiError(Exception):
    """Sonstiger, nicht dauerhafter API-Fehler (Netz, Timeout, unerwartete Antwort)."""


@dataclass
class MqttCertificate:
    """Antwort von /iot-open/sign/certification – Zugangsdaten fuer den EcoFlow-MQTT-Broker."""

    account: str
    password: str
    url: str
    port: int
    protocol: str


def _flatten(prefix: str, value: Any, out: dict[str, str]) -> None:
    """Verschachtelte Params (dict/list) in EcoFlow-Signatur-Notation flach klopfen
    (z. B. params.cmdSet, params.eps[0].enabled) – fuer Set-Befehle noetig,
    fuer die reinen GET-Aufrufe hier (noch) ungenutzt, aber Teil des Verfahrens.
    """
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else k, v, out)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _flatten(f"{prefix}[{i}]", v, out)
    else:
        out[prefix] = str(value)


def _sign(params: dict[str, Any], access_key: str, secret_key: str) -> tuple[dict[str, str], str]:
    """Gibt (vollstaendige_query_params_inkl_signatur_relevanter_felder, signature) zurueck.

    WICHTIG (Bug behoben 12.08.2026): EcoFlow signiert NICHT einfach alle Felder
    alphabetisch zusammen. Die Business-Parameter werden sortiert, danach werden
    accessKey/nonce/timestamp in FESTER Reihenfolge angehaengt (nicht mit in die
    Sortierung gemischt). Bei leeren Business-Parametern (z. B. /sign/certification)
    faellt das nicht auf, weil "accessKey" < "nonce" < "timestamp" zufaellig auch
    alphabetisch stimmt – sobald ein echter Parameter wie "sn" dazukommt, kippt die
    alphabetische Mischvariante die Reihenfolge und EcoFlow meldet "signature is wrong".
    """
    flat: dict[str, str] = {}
    _flatten("", params, flat) if params else None
    flat.pop("", None)

    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))

    business_part = "&".join(f"{k}={flat[k]}" for k in sorted(flat))
    fixed_suffix = f"accessKey={access_key}&nonce={nonce}&timestamp={timestamp}"
    query_string = f"{business_part}&{fixed_suffix}" if business_part else fixed_suffix

    signature = hmac.new(
        secret_key.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    headers = {
        "accessKey": access_key,
        "nonce": nonce,
        "timestamp": timestamp,
        "sign": signature,
    }
    return headers, signature


class EcoFlowClient:
    """Ein Client pro Access-/Secret-Key-Paar (= pro EcoFlow-Account)."""

    def __init__(self, access_key: str, secret_key: str, host: str = API_HOST) -> None:
        self._access_key = access_key
        self._secret_key = secret_key
        self._host = host

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict:
        # Signatur wird IMMER aus dem tatsaechlich gesendeten Payload gebildet:
        # bei GET aus den Query-Params, bei PUT/POST aus dem JSON-Body – nie beides.
        sign_source = json_body if json_body is not None else (params or {})
        headers, _ = _sign(sign_source, self._access_key, self._secret_key)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(
                method, f"{self._host}{path}", headers=headers, params=params, json=json_body
            )
        if resp.status_code == 401:
            raise EcoFlowAuthError("EcoFlow hat Access-/Secret-Key abgelehnt (401).")
        if resp.status_code != 200:
            raise EcoFlowApiError(f"EcoFlow-API-Fehler {resp.status_code}: {resp.text[:200]}")

        body = resp.json()
        if str(body.get("code")) not in ("0", "200"):
            message = body.get("message", "unbekannter Fehler")
            if "sign" in message.lower() or "access" in message.lower():
                raise EcoFlowAuthError(f"EcoFlow-Auth-Fehler: {message}")
            raise EcoFlowApiError(f"EcoFlow meldet Fehler: {message}")
        return body

    async def get_mqtt_certificate(self) -> MqttCertificate:
        """Verbindungstest fuers Setup-UI: schlaegt fehl, wenn Access-/Secret-Key ungueltig sind."""
        body = await self._request("GET", CERT_PATH)
        data = body["data"]
        return MqttCertificate(
            account=data["certificateAccount"],
            password=data["certificatePassword"],
            url=data["url"],
            port=int(data["port"]),
            protocol=data.get("protocol", "mqtts"),
        )

    async def list_devices(self) -> list[dict[str, Any]]:
        """Alle Geraete des Kontos - inkl. Modellname und Online-Flag.

        Antwortform: [{"sn": ..., "productName": "RIVER 2 Pro", "online": 1}, ...]
        Damit muss niemand Seriennummern abtippen, und das Modell ist bekannt,
        ohne es raten oder auswaehlen zu lassen.
        """
        body = await self._request("GET", DEVICE_LIST_PATH)
        return body.get("data") or []

    async def get_quota_all(self, serial_number: str) -> dict[str, Any]:
        """Alle aktuell verfuegbaren Quota-Felder eines Geraets (Polling-Basis)."""
        body = await self._request("GET", QUOTA_ALL_PATH, params={"sn": serial_number})
        return body["data"]

    async def set_quota(
        self, serial_number: str, module_type: int, operate_type: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Steuerbefehl per REST senden (PUT /iot-open/sign/device/quota).

        Keine eigene MQTT-Verbindung zum EcoFlow-Broker noetig – laut
        Dev-Portal-Doku laeuft "Set Quota" auch per HTTP mit demselben
        Signier-Verfahren wie die GET-Aufrufe.
        """
        body = {
            "sn": serial_number,
            "id": random.randint(100000, 999999),
            "version": "1.0",
            "moduleType": module_type,
            "operateType": operate_type,
            "params": params,
        }
        response = await self._request("PUT", QUOTA_PATH, json_body=body)
        # Was wirklich rausging und was zurueckkam - der einzige Ort, an dem
        # beides zusammen steht. Ohne diese Zeile blieb bei "der Schalter tut
        # nichts" nur Raten: Das Diagnose-Paket zeigte den Befehl gar nicht,
        # weil hier bis 14.08.2026 nichts protokolliert wurde.
        #
        # DEBUG, also nur bei eingeschaltetem Protokoll. EcoFlow quittiert
        # auch verworfene Befehle mit "Success" - deshalb gehoeren die
        # gesendeten params mit ins Bild, nicht nur die Antwort.
        logger.debug(
            "set_quota %s moduleType=%s operateType=%s params=%s -> %s",
            serial_number, module_type, operate_type, params, response,
        )
        return response.get("data", {})

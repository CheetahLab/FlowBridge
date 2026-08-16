"""
Zugriffsschutz fuer Weboberflaeche und HTTP-Schnittstelle.

Ein einziges Passwort, keine Benutzerkonten: FlowBridge ist ein Geraet im
eigenen Netz, kein Mehrbenutzer-Dienst. Wer das Passwort hat, darf alles - wer
es nicht hat, nichts.

Bewusste Entscheidungen:

- **scrypt** aus der Standardbibliothek zum Ableiten. Kein bcrypt/argon2, weil
  das eine zusaetzliche Abhaengigkeit im Container waere; scrypt ist fuer
  diesen Zweck vollkommen ausreichend und absichtlich langsam.
- **HMAC-signiertes Sitzungs-Token** statt Server-Sitzungsliste. FlowBridge
  laeuft in einem einzelnen Prozess, aber nach jedem Neustart waere eine
  Liste im Speicher weg - und ein neues Sitzungsgeheimnis pro Neustart wuerde
  alle abmelden. Das Geheimnis liegt deshalb in der Konfiguration.
- **Kein Passwort im Klartext**, auch nicht in der config.yaml: dort steht nur
  Salz und Hash.
- **Bremse bei Fehlversuchen**: ohne sie waere ein vierstelliges Passwort in
  Sekunden durchprobiert.

Was das NICHT leistet: Verschluesselung. FlowBridge spricht HTTP. Im eigenen
LAN ist das vertretbar, ueber das Internet gehoert ein Reverse Proxy mit TLS
davor - sonst geht das Passwort im Klartext ueber die Leitung.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass, field

# scrypt-Parameter: n=2**14 braucht auf einer Synology rund 50-100 ms. Genug,
# um Durchprobieren unattraktiv zu machen, ohne die Anmeldung spuerbar zu
# verzoegern.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LEN = 32

SESSION_COOKIE = "flowbridge_session"
DEFAULT_SESSION_HOURS = 720  # 30 Tage - ein Geraet im Heimnetz, kein Onlinebanking

MIN_PASSWORT_LAENGE = 8

# Bremse: nach so vielen Fehlversuchen je Herkunft wird gesperrt.
MAX_FEHLVERSUCHE = 5
SPERRE_SEKUNDEN = 60


class AuthError(Exception):
    """Anmeldung fehlgeschlagen oder nicht erlaubt."""


def _b64(rohdaten: bytes) -> str:
    return base64.urlsafe_b64encode(rohdaten).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ------------------------------------------------------------------ Passwort
def hash_password(passwort: str) -> tuple[str, str]:
    """-> (salt_b64, hash_b64). Salz je Passwort neu, nie wiederverwendet."""
    salt = secrets.token_bytes(16)
    abgeleitet = hashlib.scrypt(
        passwort.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        dklen=_SCRYPT_LEN,
    )
    return _b64(salt), _b64(abgeleitet)


def verify_password(passwort: str, salt_b64: str, hash_b64: str) -> bool:
    try:
        salt = _unb64(salt_b64)
        erwartet = _unb64(hash_b64)
    except Exception:
        return False
    abgeleitet = hashlib.scrypt(
        passwort.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        dklen=len(erwartet) or _SCRYPT_LEN,
    )
    # compare_digest statt ==, damit die Laufzeit nichts ueber den Hash verraet.
    return hmac.compare_digest(abgeleitet, erwartet)


def pruefe_passwort_regeln(passwort: str) -> None:
    if len(passwort) < MIN_PASSWORT_LAENGE:
        raise AuthError(
            f"Das Passwort braucht mindestens {MIN_PASSWORT_LAENGE} Zeichen."
        )


# -------------------------------------------------------------------- Token
def neues_sitzungsgeheimnis() -> str:
    return _b64(secrets.token_bytes(32))


def create_token(geheimnis: str, gueltig_stunden: int = DEFAULT_SESSION_HOURS) -> str:
    """Token = ablaufzeitpunkt.signatur - kein Serverzustand noetig."""
    ablauf = int(time.time()) + gueltig_stunden * 3600
    nutzdaten = str(ablauf)
    signatur = hmac.new(
        geheimnis.encode("utf-8"), nutzdaten.encode("utf-8"), hashlib.sha256
    ).digest()
    return f"{nutzdaten}.{_b64(signatur)}"


def token_gueltig(token: str, geheimnis: str) -> bool:
    if not token or not geheimnis:
        return False
    teile = token.split(".")
    if len(teile) != 2:
        return False
    nutzdaten, signatur = teile
    erwartet = hmac.new(
        geheimnis.encode("utf-8"), nutzdaten.encode("utf-8"), hashlib.sha256
    ).digest()
    try:
        if not hmac.compare_digest(_unb64(signatur), erwartet):
            return False
        # Erst NACH der Signaturpruefung auswerten: sonst liesse sich ueber
        # eine unsignierte Ablaufzeit Verhalten ausloesen.
        return int(nutzdaten) > time.time()
    except Exception:
        return False


# ------------------------------------------------------------------- Bremse
@dataclass
class Fehlversuche:
    """Zaehlt Fehlversuche je Herkunft. Nur im Speicher - nach einem Neustart
    ist die Sperre weg, was hier vertretbar ist: ein Neustart erfordert bereits
    Zugriff auf den Container."""

    _stand: dict[str, tuple[int, float]] = field(default_factory=dict)

    def gesperrt_bis(self, herkunft: str) -> float:
        anzahl, letzter = self._stand.get(herkunft, (0, 0.0))
        if anzahl < MAX_FEHLVERSUCHE:
            return 0.0
        return letzter + SPERRE_SEKUNDEN

    def pruefe(self, herkunft: str) -> None:
        rest = self.gesperrt_bis(herkunft) - time.time()
        if rest > 0:
            raise AuthError(f"Zu viele Fehlversuche. Bitte {int(rest) + 1} s warten.")

    def fehlschlag(self, herkunft: str) -> None:
        anzahl, _ = self._stand.get(herkunft, (0, 0.0))
        self._stand[herkunft] = (anzahl + 1, time.time())

    def erfolg(self, herkunft: str) -> None:
        self._stand.pop(herkunft, None)


# ------------------------------------------------------------- Konfiguration
def auth_config(config: dict) -> dict:
    return config.get("auth") or {}


def ist_eingerichtet(config: dict) -> bool:
    a = auth_config(config)
    return bool(a.get("password_hash") and a.get("password_salt"))


def umgebungs_passwort() -> str:
    """FLOWBRIDGE_PASSWORD erlaubt es, den Schutz im Container gleich beim
    ersten Start zu setzen - ohne das Zeitfenster, in dem noch gar kein
    Passwort vergeben ist."""
    return os.environ.get("FLOWBRIDGE_PASSWORD", "").strip()


def setze_passwort(config: dict, passwort: str) -> dict:
    """Gibt eine NEUE Konfiguration mit gesetztem Passwort zurueck."""
    pruefe_passwort_regeln(passwort)
    salt, hashwert = hash_password(passwort)
    vorher = auth_config(config)
    neu = {**config}
    neu["auth"] = {
        **vorher,
        "password_salt": salt,
        "password_hash": hashwert,
        # Bestehende Sitzungen bleiben bei einem Passwortwechsel gueltig, wenn
        # das Geheimnis erhalten bleibt. Genau das wollen wir NICHT: wer sein
        # Passwort aendert, will in aller Regel jemanden aussperren.
        "session_secret": neues_sitzungsgeheimnis(),
        "session_hours": vorher.get("session_hours", DEFAULT_SESSION_HOURS),
    }
    return neu

"""Single-use approvals and action receipts for one in-memory user session.

The lock covers only bookkeeping, never network calls. A claimed approval stays
consumed even if the client disconnects or the outcome of a write is unknown.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable

_APPROVAL_TTL = 10 * 60
_MAX_APPROVALS = 500


@dataclass(repr=False)
class _Approval:
    fingerprint: str
    expires: float
    state: str = "pending"
    result: dict | None = None


class ActionLedger:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._records: dict[str, _Approval] = {}
        self._latest: dict[str, str] = {}

    def __repr__(self) -> str:
        return "ActionLedger()"

    @staticmethod
    def _receipt(record: _Approval) -> dict:
        if record.state == "running":
            return {"status": "AKTION_LAEUFT", "hinweis": "Diese bestätigte Aktion läuft bereits. Nicht erneut ausführen."}
        result = copy.deepcopy(record.result or {})
        result["already_executed" if record.state == "completed" else "receipt_replayed"] = True
        result["hinweis"] = ("Gespeichertes Ergebnis dieser Bestätigung. Keine erneute Ausführung."
                             if record.state == "completed" else
                             "Ergebnis dieser Aktion ist ungeklärt. Nicht automatisch wiederholen; zuerst im Zielsystem prüfen.")
        return result

    def propose(self, fingerprint: str, secret: bytes, *, confirmation_message: bool) -> tuple[str | None, dict | None]:
        with self._lock:
            previous_code = self._latest.get(fingerprint)
            previous = self._records.get(previous_code) if previous_code else None
            if previous:
                if previous.state in ("running", "uncertain") or (previous.state == "completed" and confirmation_message):
                    return None, self._receipt(previous)
                if previous.state == "pending" and self._clock() < previous.expires:
                    return previous_code, None
            # Keep consumed codes until the session ends. Never evict receipts to make room.
            if len(self._records) >= _MAX_APPROVALS:
                raise ValueError("Zu viele Aktionsvorschläge in dieser Sitzung. Keine weitere Änderung ausgeführt.")
            while True:
                nonce = secrets.token_bytes(16)
                code = hmac.new(secret, fingerprint.encode() + nonce, hashlib.sha256).hexdigest()[:6].upper()
                if code not in self._records:
                    break
            self._records[code] = _Approval(fingerprint, self._clock() + _APPROVAL_TTL)
            self._latest[fingerprint] = code
            return code, None

    def claim(self, code: str, fingerprint: str) -> tuple[bool, dict | None]:
        with self._lock:
            record = self._records.get(code)
            if record is None or not hmac.compare_digest(record.fingerprint, fingerprint):
                return False, None
            if record.state != "pending":
                return False, self._receipt(record)
            if self._clock() >= record.expires:
                return False, None
            record.state = "running"  # atomic single-use claim BEFORE calling any external service
            return True, None

    def finish(self, code: str, result: dict, *, uncertain: bool = False) -> None:
        with self._lock:
            record = self._records[code]
            record.result = copy.deepcopy(result)
            record.state = "uncertain" if uncertain else "completed"

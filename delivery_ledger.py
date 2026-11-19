"""Durable per-day WhatsApp attempt ledger stored in the private GitHub repository.

A claim is committed BEFORE calling GREEN-API. Retries skip any preexisting claim,
including uncertain interrupted attempts, preferring no duplicate over blind resend.
"""
import base64
import hashlib
import hmac
import os
import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def ledger_secret():
    """LEDGER_KEY if set, else the (private) GREEN-API token. Never stored or printed."""
    value = (os.environ.get("LEDGER_KEY") or os.environ.get("GREEN_API_TOKEN") or "").strip()
    if len(value) < 10:
        raise ValueError("LEDGER_KEY or GREEN_API_TOKEN is required for the delivery ledger")
    return value.encode("utf-8")


def legacy_key(chat_id):
    """Old unkeyed hash; only used to migrate existing entries."""
    return hashlib.sha256(chat_id.encode("utf-8")).hexdigest()[:32]


class DeliveryLedger:
    def __init__(self, repository, github_token, path=".delivery-state.json"):
        self._secret = ledger_secret()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository or ""):
            raise ValueError("GITHUB_REPOSITORY is invalid")
        if not github_token:
            raise ValueError("GITHUB_TOKEN is missing")
        self.base = ("https://api.github.com/repos/" + repository +
                     "/contents/" + quote(path))
        self.token = github_token

    def request(self, method, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = Request(
            self.base, data=data, method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "DatiaGoldAlert/1.1",
            },
        )
        try:
            with urlopen(req, timeout=20) as response:
                return json.loads(response.read(2_000_000).decode("utf-8"))
        except HTTPError as exc:
            if method == "GET" and exc.code == 404:
                return None
            raise RuntimeError(f"GitHub ledger {method} failed: HTTP {exc.code}") from None
        except URLError:
            raise RuntimeError(f"GitHub ledger {method} network failure") from None

    def read(self):
        result = self.request("GET")
        if result is None:
            return {}, None
        if result.get("encoding") != "base64" or "sha" not in result:
            raise RuntimeError("Unexpected GitHub ledger file response")
        try:
            state = json.loads(base64.b64decode(result["content"]).decode("utf-8"))
            if not isinstance(state, dict):
                raise ValueError("Expected object")
        except (ValueError, KeyError, UnicodeError):
            raise RuntimeError("Invalid GitHub ledger content") from None
        return state, result["sha"]

    def write(self, state, sha, message="Record WhatsApp daily delivery state [skip ci]"):
        data = json.dumps(state, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        payload = {
            "message": message,
            "content": base64.b64encode(data).decode("ascii"),
            "branch": "main",
        }
        if sha:
            payload["sha"] = sha
        self.request("PUT", payload)

    def key(self, chat_id):
        """Keyed hash (HMAC-SHA256) of a destination. The repo is public, so a plain
        hash of a 10-digit phone number could be reversed by brute force."""
        secret = getattr(self, "_secret", None)
        if secret is None:  # unit-test ledgers built without __init__
            return legacy_key(chat_id)
        return hmac.new(secret, chat_id.encode("utf-8"), hashlib.sha256).hexdigest()[:32]

    def claim(self, day, chat_id):
        """Returns False if this destination already has an attempt today."""
        state, sha = self.read()
        key = self.key(chat_id)
        if key in state.get(day, {}):
            return False
        cutoff = (date.fromisoformat(day) - timedelta(days=35)).isoformat()
        state = {d: rows for d, rows in state.items() if d >= cutoff}
        state.setdefault(day, {})[key] = {
            "status": "attempting",
            "at": datetime.now(timezone.utc).isoformat(),
        }
        self.write(state, sha)
        return True

    def update(self, day, chat_id, status, message_id=None):
        state, sha = self.read()
        key = self.key(chat_id)
        if key not in state.get(day, {}):
            raise RuntimeError("Delivery claim missing; refusing to lose receipt")
        state[day][key]["status"] = status
        if message_id:
            state[day][key]["message_id"] = message_id
        self.write(state, sha)


def rekey(ledger, chats):
    """One-time migration: replace legacy hashes of known chats with keyed hashes.
    Entries that match no configured chat are dropped (old/removed destinations)."""
    state, sha = ledger.read()
    mapping = {}
    for chat in chats:
        for suffix in ("", "#weekly"):
            mapping[legacy_key(chat + suffix)] = ledger.key(chat + suffix)
    new_keys = set(mapping.values())
    out, moved, dropped = {}, 0, 0
    for day, rows in state.items():
        kept = {}
        for k, row in rows.items():
            if k in mapping:
                kept[mapping[k]] = row
                moved += 1
            elif k in new_keys:
                kept[k] = row
            else:
                dropped += 1
        if kept:
            out[day] = kept
    ledger.write(out, sha, message="Re-key delivery ledger with HMAC [skip ci]")
    return moved, dropped


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--rekey"]:
        import gold_alert
        led = DeliveryLedger(os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN"))
        chats = gold_alert.destination_chats()
        old_group = (os.environ.get("RECIPIENT_1") or "").strip()
        if old_group.endswith("@g.us"):
            chats.append(old_group)
        moved, dropped = rekey(led, chats)
        print(f"REKEY: moved {moved} entries, dropped {dropped} unknown entries")

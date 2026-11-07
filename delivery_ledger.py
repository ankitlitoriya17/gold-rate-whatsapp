"""Durable per-day WhatsApp attempt ledger stored in the private GitHub repository.

A claim is committed BEFORE calling GREEN-API. Retries skip any preexisting claim,
including uncertain interrupted attempts, preferring no duplicate over blind resend.
"""
import base64
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class DeliveryLedger:
    def __init__(self, repository, github_token, path=".delivery-state.json"):
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

    def write(self, state, sha):
        data = json.dumps(state, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        payload = {
            "message": "Record WhatsApp daily delivery state [skip ci]",
            "content": base64.b64encode(data).decode("ascii"),
            "branch": "main",
        }
        if sha:
            payload["sha"] = sha
        self.request("PUT", payload)

    @staticmethod
    def key(chat_id):
        # Do not persist phone numbers or group IDs in the repository.
        return hashlib.sha256(chat_id.encode("utf-8")).hexdigest()[:32]

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

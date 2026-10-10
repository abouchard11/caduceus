"""TypeSafe System One ("Jev") client, stdlib only.

Jev evaluates typed questions (choice / score / noul) against a state and
returns calibrated probabilities. It writes no text and picks no winner;
inside Caduceus it classifies a council question's domain and scores skills
against seat×domain pairs (docs/compile-design.md §4). First-party endpoint
only: the OpenRouter route measured 33% availability on 2026-09-24; the
first-party one served 5,500/5,500. The key is read from ~/.caduceus/env via
config.load_env() and is never logged or echoed in an error.
"""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import Callable, Dict, Optional

from . import config

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
USD_PER_INPUT_TOKEN = 0.042 / 1_000_000   # TypeSafe list price, 2026-09
ENV_KEY = "TYPESAFE_API_KEY"
MAX_BODY = 1_000_000   # an answers map is a few KB; refuse anything absurd


class JevError(Exception):
    pass


def api_key() -> str:
    key = config.load_env().get(ENV_KEY, "") or os.environ.get(ENV_KEY, "")
    return key.strip()


def available() -> bool:
    return bool(api_key())


def estimate_usd(usage: Dict[str, int]) -> float:
    return float(usage.get("input_tokens", 0)) * USD_PER_INPUT_TOKEN


class Client:
    def __init__(self, key: Optional[str] = None, model: str = DEFAULT_MODEL,
                 timeout: float = 10.0,
                 opener: Optional[Callable] = None):
        self.key = api_key() if key is None else key
        self.model = model
        self.timeout = timeout
        self.opener = opener or urllib.request.urlopen
        self.usage: Dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        self.calls = 0

    def ask(self, state, questions: Dict[str, dict]) -> Dict[str, dict]:
        """POST one state with its questions; return the `answers` map."""
        if not self.key:
            raise JevError(f"no {ENV_KEY} (add it to {config.env_file()})")
        body = {"state": state, "model": self.model, "questions": questions}
        req = urllib.request.Request(
            ENDPOINT, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.key}"},
            method="POST")
        try:
            with self.opener(req, timeout=self.timeout) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                raw = resp.read(MAX_BODY + 1)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read(200).decode("utf-8", "replace")
            except Exception:
                pass
            raise JevError(f"HTTP {e.code} from Jev: {detail or e.reason}")
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
            raise JevError(f"Jev unreachable: {e.__class__.__name__}: {e}")
        if status != 200:
            raise JevError(f"HTTP {status} from Jev: {raw[:200].decode('utf-8', 'replace')}")
        if len(raw) > MAX_BODY:
            raise JevError(f"Jev response too large (> {MAX_BODY} bytes)")
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError as e:
            raise JevError(f"Jev returned non-JSON: {e}")
        if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
            raise JevError("Jev response has no 'answers' map")
        self.calls += 1
        for k in ("input_tokens", "output_tokens"):
            self.usage[k] = self.usage.get(k, 0) + int((data.get("usage") or {}).get(k, 0) or 0)
        return data["answers"]

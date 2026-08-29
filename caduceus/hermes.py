"""Seat transports: how Caduceus talks to Hermes seats.

Priority order at runtime:
  1. ApiTransport      - per-seat Hermes gateway api_server (session continuity,
                         no process spawn). Used when the seat's gateway is up.
  2. OneshotTransport  - `hermes -p <seat> -z "<prompt>"`. Stateless, zero
                         config dependencies. The reliable workhorse.
  3. MockTransport     - --dry-run and the test suite. Deterministic.

All stdlib. No httpx/requests.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .config import Seat, load_env

ONESHOT_TIMEOUT = 600  # seconds per seat call; council calls run in parallel


@dataclass
class SeatReply:
    seat: str
    text: str
    ok: bool
    transport: str
    error: str = ""
    usage: Dict = field(default_factory=dict)


class Transport:
    name = "base"

    def ask(self, seat: Seat, prompt: str, session_hint: str = "") -> SeatReply:  # pragma: no cover
        raise NotImplementedError

    def available(self, seat: Seat) -> bool:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------- oneshot

class OneshotTransport(Transport):
    name = "oneshot"

    def __init__(self, hermes_bin: Optional[str] = None,
                 extra_args: Optional[List[str]] = None):
        self.bin = hermes_bin or shutil.which("hermes") or "hermes"
        # Per-invocation flags. The executor passes ["-t", "clarify"]: -t is
        # an ENABLE-list, so naming one harmless toolset strips the other 21
        # tools AND every MCP server for that call (verified 2026-08-27 -
        # "" is ignored and --safe-mode still ships write_file).
        self.extra_args = list(extra_args or [])

    def available(self, seat: Seat) -> bool:
        return shutil.which(self.bin) is not None or Path(self.bin).exists()

    def ask(self, seat: Seat, prompt: str, session_hint: str = "") -> SeatReply:
        usage_file = tempfile.NamedTemporaryFile(
            prefix=f"cad-{seat.name}-", suffix=".json", delete=False
        )
        usage_file.close()
        cmd = [
            self.bin, "-p", seat.name,
            "-z", prompt,
            "--usage-file", usage_file.name,
            *self.extra_args,
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=ONESHOT_TIMEOUT,
                env={**os.environ, "HERMES_ACCEPT_HOOKS": "1"},
            )
            usage = {}
            try:
                raw = Path(usage_file.name).read_text().strip()
                if raw:
                    usage = json.loads(raw)
            except Exception:
                pass
            text = (proc.stdout or "").strip()
            if proc.returncode == 0 and text:
                return SeatReply(seat.name, text, True, self.name, usage=usage)
            err = (proc.stderr or "").strip()[-500:] or f"exit {proc.returncode}, empty output"
            # exit 2 with partial output is still usable
            if text:
                return SeatReply(seat.name, text, True, self.name,
                                 error=f"partial ({err})", usage=usage)
            return SeatReply(seat.name, "", False, self.name, error=err, usage=usage)
        except subprocess.TimeoutExpired:
            return SeatReply(seat.name, "", False, self.name,
                             error=f"timeout after {ONESHOT_TIMEOUT}s")
        except FileNotFoundError:
            return SeatReply(seat.name, "", False, self.name,
                             error=f"hermes binary not found ({self.bin})")
        finally:
            try:
                os.unlink(usage_file.name)
            except OSError:
                pass


# ---------------------------------------------------------------- api server

class ApiTransport(Transport):
    """OpenAI-compatible call into a running per-seat gateway.

    One session id per seat per workstream - the api_server has no per-session
    lock, so concurrent turns on one id are last-writer-wins. Caduceus therefore
    serializes per seat and parallelizes across seats.
    """
    name = "api"

    def __init__(self, key: Optional[str] = None, host: str = "127.0.0.1"):
        env = load_env()
        self.key = key or env.get("CADUCEUS_API_KEY", "")
        self.host = host

    def _url(self, seat: Seat, path: str) -> str:
        return f"http://{self.host}:{seat.port}{path}"

    def available(self, seat: Seat) -> bool:
        if len(self.key) < 16:
            return False
        req = urllib.request.Request(
            self._url(seat, "/v1/models"),
            headers={"Authorization": f"Bearer {self.key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def ask(self, seat: Seat, prompt: str, session_hint: str = "") -> SeatReply:
        session_id = f"caduceus-{seat.name}-{session_hint or 'main'}"
        payload = {
            "model": seat.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        req = urllib.request.Request(
            self._url(seat, "/v1/chat/completions"),
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "X-Hermes-Session-Id": session_id,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=ONESHOT_TIMEOUT) as resp:
                body = json.loads(resp.read().decode())
            text = ""
            choices = body.get("choices") or []
            if choices:
                text = ((choices[0].get("message") or {}).get("content") or "").strip()
            if text:
                return SeatReply(seat.name, text, True, self.name,
                                 usage=body.get("usage") or {})
            return SeatReply(seat.name, "", False, self.name, error="empty completion")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode()[:300]
            except Exception:
                pass
            return SeatReply(seat.name, "", False, self.name,
                             error=f"HTTP {e.code} {detail}")
        except Exception as e:
            return SeatReply(seat.name, "", False, self.name, error=str(e)[:300])


# ---------------------------------------------------------------- mock

class MockTransport(Transport):
    """Deterministic seat simulator for --dry-run and tests."""
    name = "mock"

    def __init__(self, script: Optional[Dict[str, List[str]]] = None):
        # script: seat -> list of canned replies, popped in order
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.calls: List[Dict] = []

    def available(self, seat: Seat) -> bool:
        return True

    def ask(self, seat: Seat, prompt: str, session_hint: str = "") -> SeatReply:
        self.calls.append({"seat": seat.name, "prompt": prompt})
        queue = self.script.get(seat.name)
        if queue:
            return SeatReply(seat.name, queue.pop(0), True, self.name)
        canned = json.dumps({
            "position": f"[dry-run] {seat.display} would analyze: {prompt[:80]}",
            "confidence": 0.5,
            "key_points": [f"{seat.display} placeholder reasoning"],
            "risks": ["dry-run mode - no model was called"],
            "recommendation": "run without --dry-run for a real answer",
        })
        return SeatReply(seat.name, canned, True, self.name)


# ---------------------------------------------------------------- selection

def pick_transport(seat: Seat, prefer: str = "auto",
                   mock: Optional[MockTransport] = None) -> Transport:
    if prefer == "mock":
        return mock or MockTransport()
    if prefer == "oneshot":
        return OneshotTransport()
    if prefer == "api":
        return ApiTransport()
    # auto: api if that seat's gateway answers, else oneshot
    api = ApiTransport()
    if api.available(seat):
        return api
    return OneshotTransport()

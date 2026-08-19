"""Caduceus configuration: seats, models, paths.

Design invariants (do not violate casually):
- Alex is the Shaper. No seat originates strategy; seats complement the operator.
- Seat model families are intentionally heterogeneous: same-family seats agree
  too easily (conformity trap). FINISHER must never share a family with FORGE.
- Everything here is stdlib-only. No third-party imports anywhere in caduceus.
"""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------- paths

def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def caduceus_home() -> Path:
    p = Path(os.environ.get("CADUCEUS_HOME", str(Path.home() / ".caduceus")))
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    return p


def repo_root() -> Path:
    """Root of the caduceus checkout (where seats/, skills/, hooks/ live)."""
    override = os.environ.get("CADUCEUS_REPO")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent


def ledger_db_path() -> Path:
    return caduceus_home() / "ledger.db"


def runs_dir() -> Path:
    p = caduceus_home() / "runs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def approvals_dir() -> Path:
    p = caduceus_home() / "approvals"
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    return p


def guard_log_path() -> Path:
    return caduceus_home() / "guard.log.jsonl"


def env_file() -> Path:
    return caduceus_home() / "env"


# ---------------------------------------------------------------- seats

@dataclass(frozen=True)
class Seat:
    name: str                 # hermes profile name (lowercase alphanumeric)
    display: str              # e.g. "FINISHER"
    role: str                 # one-line role, also used as hermes profile description
    model: str                # model id for the provider below
    provider: str             # hermes provider name
    family: str               # model family tag used for heterogeneity checks
    temperature_hint: str     # encoded in SOUL, hermes doesn't take temp per call
    port: int                 # api_server port when gateways are enabled
    domains: List[str] = field(default_factory=list)  # believability prior domains
    tools_capable: bool = True  # False -> profile must ship with tools stripped


# Models with NO tool-capable endpoint on their provider. Hermes attaches tool
# definitions to every request, so a seat cast on one of these 404s on every
# call ("No endpoints found that support tool use") until its profile ships
# with every toolset, tool_search, and every MCP server switched off.
# Verified live on OpenRouter 2026-08-19: neither 405B Hermes model has a
# single endpoint accepting the `tools` parameter - downgrading does not help.
TOOLS_INCAPABLE_MODELS = frozenset({
    "nousresearch/hermes-4-405b",
    "nousresearch/hermes-3-405b",
})


def model_tools_capable(model_id: str) -> bool:
    """Can this model take tool definitions? Model-level truth, used to keep
    Seat.tools_capable honest across recasts (`cad models set`)."""
    return model_id not in TOOLS_INCAPABLE_MODELS


# Model casting rationale (verified live on OpenRouter 2026-08-19):
#   forge    qwen3.7-plus via Alex's alibaba coding plan  -> bulk implementation, cheap
#   finisher anthropic/claude-sonnet-5                    -> verification gate, DIFFERENT family
#   recon    deepseek/deepseek-v4-pro-0813                -> research, 1M ctx, third family
#   sparring nousresearch/hermes-4-405b                   -> ideation stress-test, fourth family
#   envoy    qwen/qwen3.7-flash                           -> tone pass, costs pennies
SEATS: Dict[str, Seat] = {
    "forge": Seat(
        name="forge", display="FORGE",
        role=("Implementer. Turns approved plans into shipped, tested code and "
              "sequenced execution. Strong at bulk coding, refactors, wiring, and "
              "grinding through task lists without losing the thread."),
        model="qwen3.7-plus", provider="alibaba-coding-plan", family="qwen",
        temperature_hint="balanced", port=8651,
        domains=["implementation", "refactor", "tooling", "automation"],
    ),
    "finisher": Seat(
        name="finisher", display="FINISHER",
        role=("Verifier and completer-finisher. Reviews work for correctness, edge "
              "cases, type/contract violations, and unfinished threads. The quality "
              "gate: nothing ships until FINISHER passes it. Compensates for the "
              "operator's low Organized(26)/Detail(34) scores."),
        model="anthropic/claude-sonnet-5", provider="openrouter", family="anthropic",
        temperature_hint="cold", port=8652,
        domains=["review", "verification", "types", "testing", "security"],
    ),
    "recon": Seat(
        name="recon", display="RECON",
        role=("Researcher. Gathers evidence, reads sources end-to-end, and returns "
              "cited, confidence-tagged intel. Never speculates without labeling it."),
        model="deepseek/deepseek-v4-pro-0813", provider="openrouter", family="deepseek",
        temperature_hint="cool", port=8653,
        domains=["research", "market", "competitive", "docs"],
    ),
    "sparring": Seat(
        name="sparring", display="SPARRING",
        role=("Ideation stress-tester. Attacks plans, finds the unconventional angle, "
              "extends the operator's ideas. Feisty by design. Never originates "
              "strategy - the operator is the Shaper; SPARRING sharpens."),
        model="nousresearch/hermes-4-405b", provider="openrouter", family="nous",
        temperature_hint="hot", port=8654,
        domains=["strategy", "product", "naming", "growth"],
        # No OpenRouter endpoint for this model accepts `tools` (2026-08-19):
        # its profile is provisioned with every toolset stripped. Reasoning
        # seat only - it argues, it does not touch the filesystem.
        tools_capable=False,
    ),
    "envoy": Seat(
        name="envoy", display="ENVOY",
        role=("Comms pass. Reviews outbound text for tone, audience fit, and "
              "unintended bluntness before it leaves the building. Compensates for "
              "the operator's Empathetic(41)/Direct(94) combination."),
        model="qwen/qwen3.7-flash", provider="openrouter", family="qwen",
        temperature_hint="warm", port=8655,
        domains=["comms", "email", "negotiation", "copy"],
    ),
}

# Council defaults
QUICK_PAIR = ("forge", "finisher")            # cheap first pass (HCP stage 1)
FULL_COUNCIL = ("forge", "finisher", "recon", "sparring")
DEFAULT_ROUNDS = 2                            # independent -> cross-exam
STANCE_FLIP_PENALTY_NOTE = (
    "Position changes are logged. A change without a cited, specific argument "
    "from another draft is recorded as conformity and lowers your track record."
)

# Domain keyword map for ledger weighting (deterministic, cheap; a seat can
# reclassify later, but the default must never require a model call).
DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "implementation": ["implement", "build", "code", "function", "bug", "fix", "api"],
    "review": ["review", "verify", "audit", "check", "correct"],
    "types": ["typescript", "type", "schema", "interface", "zod"],
    "testing": ["test", "pytest", "coverage", "e2e"],
    "security": ["security", "auth", "secret", "injection", "vuln"],
    "research": ["research", "find", "compare", "investigate", "source"],
    "strategy": ["strategy", "roadmap", "pivot", "positioning", "pricing", "plan"],
    "comms": ["email", "message", "reply", "tone", "outreach", "post"],
    "infra": ["deploy", "docker", "server", "launchd", "cron", "daemon"],
    "data": ["sql", "database", "etl", "csv", "analytics"],
}


def classify_domain(text: str) -> str:
    t = text.lower()
    best, best_hits = "general", 0
    for domain, kws in DOMAIN_KEYWORDS.items():
        hits = sum(1 for k in kws if k in t)
        if hits > best_hits:
            best, best_hits = domain, hits
    return best


# ---------------------------------------------------------------- env / secrets

def load_env() -> Dict[str, str]:
    """Read ~/.caduceus/env (KEY=VALUE lines). Never logs values."""
    out: Dict[str, str] = {}
    p = env_file()
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def ensure_api_key() -> str:
    """Return the shared caduceus<->hermes api_server key, creating it once."""
    env = load_env()
    key = env.get("CADUCEUS_API_KEY", "")
    if len(key) >= 16:
        return key
    key = secrets.token_urlsafe(32)
    env["CADUCEUS_API_KEY"] = key
    write_env(env)
    return key


def write_env(env: Dict[str, str]) -> None:
    p = env_file()
    body = "\n".join(f"{k}={v}" for k, v in sorted(env.items())) + "\n"
    p.write_text(body)
    os.chmod(p, 0o600)


def seat_list(names: Optional[str]) -> List[Seat]:
    """Parse 'forge,finisher' -> [Seat]; None -> full council."""
    if not names:
        return [SEATS[n] for n in FULL_COUNCIL]
    picked = []
    for raw in names.split(","):
        n = raw.strip().lower()
        if n not in SEATS:
            raise SystemExit(f"unknown seat '{n}' (have: {', '.join(SEATS)})")
        picked.append(SEATS[n])
    return picked


def heterogeneity_warnings(seats: List[Seat]) -> List[str]:
    """Warn when a council collapses into one model family."""
    fams = [s.family for s in seats]
    warns = []
    if len(seats) >= 2 and len(set(fams)) == 1:
        warns.append(
            f"all seats are family '{fams[0]}' - conformity risk is maximal; "
            "add a seat from another family"
        )
    return warns


def to_json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)

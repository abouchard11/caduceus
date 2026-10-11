"""Model market intelligence: live OpenRouter pricing vs seat casting.

Why this exists: OpenRouter runs rotating promos (launch discounts, batch
twins at 50% off, time-window pricing, free trials) and tiered price cliffs
(a model can triple past a min_prompt_tokens threshold). The operator scores
Organized 26 - he will never re-check that page. The weekly cron will.

Three verbs:
  scan   - market vs current casting: promos, batch twins, cheaper rivals, cliffs
  set    - recast a seat's model in one line (casting.json + hermes profile patch)
  value  - $ per win by seat/domain, joined to the believability ledger

Stdlib only. Network use is one GET, cached 24h, and never happens in tests.
"""
from __future__ import annotations

import dataclasses
import json
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config
from .config import SEATS, Seat

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL_S = 24 * 3600
FRESH_MODEL_WINDOW_S = 400 * 86400   # candidates must be < ~13 months old
MIN_CANDIDATE_CTX = 128_000

# families we recognize for heterogeneity accounting
FAMILY_PREFIXES = {
    "anthropic/": "anthropic", "openai/": "openai", "google/": "google",
    "qwen/": "qwen", "deepseek/": "deepseek", "nousresearch/": "nous",
    "x-ai/": "xai", "z-ai/": "zai", "mistralai/": "mistral",
    "meta-llama/": "meta", "bytedance-seed/": "bytedance",
    "moonshotai/": "moonshot", "stepfun/": "stepfun", "nvidia/": "nvidia",
}


def family_of(model_id: str) -> str:
    for prefix, fam in FAMILY_PREFIXES.items():
        if model_id.startswith(prefix):
            return fam
    return model_id.split("/")[0] if "/" in model_id else "unknown"


# ---------------------------------------------------------------- casting

def casting_path() -> Path:
    return config.caduceus_home() / "casting.json"


def load_casting() -> Dict[str, Dict]:
    p = casting_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_casting(casting: Dict[str, Dict]) -> None:
    casting_path().write_text(json.dumps(casting, indent=2))


def effective_seat(name: str) -> Seat:
    """Seat with any casting override applied. This is the runtime truth for
    what model sits in a seat; SEATS holds the shipped defaults."""
    if name in SEATS:
        seat = SEATS[name]
    else:
        # 0.5.0: archetype seats (plant, coordinator, anchor, driver) resolve
        # through the library's defaults; KeyError for anything else.
        from . import archetypes, compile as compile_mod
        seat = compile_mod.seat_for(archetypes.by_seat(name).key)
    ov = load_casting().get(name)
    if not ov:
        return seat
    model = ov.get("model", seat.model)
    return dataclasses.replace(
        seat,
        model=model,
        provider=ov.get("provider", seat.provider),
        family=ov.get("family", family_of(model)),
        # recompute from the model, never inherit: a recast off (or onto) a
        # tools-incapable model must move the lockdown with it, or the seat
        # stays stripped forever with no way back but hand-editing the profile
        tools_capable=config.model_tools_capable(model),
    )


def effective_seats() -> Dict[str, Seat]:
    return {name: effective_seat(name) for name in SEATS}


def set_seat_model(seat_name: str, model_id: str, provider: str = "openrouter",
                   note: str = "") -> Tuple[Seat, List[str]]:
    """Recast a seat. Updates casting.json AND patches the Hermes profile
    config (which is what `hermes -p <seat>` actually reads)."""
    if seat_name not in SEATS:
        raise SystemExit(f"unknown seat '{seat_name}' (have: {', '.join(SEATS)})")
    log: List[str] = []
    casting = load_casting()
    prev = effective_seat(seat_name)
    casting[seat_name] = {
        "model": model_id, "provider": provider, "family": family_of(model_id),
        "set_at": time.time(), "note": note,
        "previous": {"model": prev.model, "provider": prev.provider},
    }
    save_casting(casting)
    log.append(f"[+] casting: {seat_name} {prev.model} -> {model_id} ({provider})")

    new_seat = effective_seat(seat_name)
    fams = {effective_seat(n).family for n in config.FULL_COUNCIL}
    forge_fam = effective_seat("forge").family
    finisher_fam = effective_seat("finisher").family
    if finisher_fam == forge_fam:
        log.append(f"[!] FINISHER shares FORGE's family ({forge_fam}) - hard rule "
                   "violation ('FINISHER never shares a family with FORGE'). Reconsider.")
    if len(fams) < len(config.FULL_COUNCIL):
        log.append(f"[!] council spans {len(fams)} of {len(config.FULL_COUNCIL)} model "
                   f"families ({', '.join(sorted(fams))}) - same-family seats agree "
                   "too easily.")

    # patch the hermes profile so -z / gateway calls actually use it
    from . import seatsetup  # late import: avoids cycle at module load
    if seatsetup.profile_exists(seat_name):
        api_key = config.load_env().get("CADUCEUS_API_KEY", "")
        seatsetup.patch_profile_config(new_seat, api_key, log,
                                       enable_api=bool(api_key))
        log.append(f"[i] if seat gateway is running: hermes -p {seat_name} "
                   "gateway restart")
    else:
        log.append(f"[i] hermes profile '{seat_name}' not provisioned yet - "
                   "casting will apply on `cad init`")
    return new_seat, log


# ---------------------------------------------------------------- market data

def market_from_cache() -> Optional[Dict[str, Dict]]:
    """Normalized market from the local cache ONLY - never touches the
    network. Used by council cost estimation so deliberation stays offline-
    safe."""
    cache = config.caduceus_home() / "models_cache.json"
    if not cache.exists():
        return None
    try:
        blob = json.loads(cache.read_text())
        return normalize(blob.get("data", []))
    except Exception:
        return None


def fetch_market(force: bool = False,
                 cache_file: Optional[Path] = None) -> Tuple[List[Dict], float]:
    """Return (models, fetched_at). 24h cache at ~/.caduceus/models_cache.json."""
    cache = cache_file or (config.caduceus_home() / "models_cache.json")
    if cache.exists() and not force:
        try:
            blob = json.loads(cache.read_text())
            if time.time() - blob.get("fetched_at", 0) < CACHE_TTL_S:
                return blob["data"], blob["fetched_at"]
        except Exception:
            pass
    req = urllib.request.Request(OPENROUTER_MODELS_URL,
                                 headers={"User-Agent": "caduceus/0.2"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode()).get("data", [])
    blob = {"fetched_at": time.time(), "data": data}
    cache.write_text(json.dumps(blob))
    return data, blob["fetched_at"]


def normalize(models: List[Dict]) -> Dict[str, Dict]:
    """id -> {in_per_m, out_per_m, ctx, created, cliffs, free, batch_of}"""
    out: Dict[str, Dict] = {}
    for m in models:
        p = m.get("pricing") or {}
        try:
            inp = float(p.get("prompt") or 0) * 1e6
            outp = float(p.get("completion") or 0) * 1e6
        except (TypeError, ValueError):
            continue
        cliffs = []
        for ov in (p.get("overrides") or []):
            if not isinstance(ov, dict):
                continue
            thresh = ov.get("min_prompt_tokens")
            if thresh:
                try:
                    cliffs.append({
                        "min_prompt_tokens": int(thresh),
                        "in_per_m": float(ov.get("prompt") or 0) * 1e6,
                        "out_per_m": float(ov.get("completion") or 0) * 1e6,
                    })
                except (TypeError, ValueError):
                    continue
            elif "utc_start" in ov:
                cliffs.append({"time_window": True})
        mid = m.get("id", "")
        out[mid] = {
            "id": mid,
            "in_per_m": inp, "out_per_m": outp,
            "ctx": m.get("context_length") or 0,
            "created": m.get("created") or 0,
            "cliffs": cliffs,
            "free": mid.endswith(":free") or (inp == 0 and outp == 0),
            "base_of_batch": mid[:-6] if mid.endswith(":batch") else None,
            "family": family_of(mid),
            "expiration": m.get("expiration_date"),
        }
    return out


# ---------------------------------------------------------------- analysis

def seat_report(market: Dict[str, Dict]) -> List[Dict]:
    """Per-seat market comparison."""
    now = time.time()
    rows = []
    for name in SEATS:
        seat = effective_seat(name)
        cur = market.get(seat.model) or market.get(f"{seat.provider}/{seat.model}")
        entry: Dict = {"seat": name, "display": seat.display, "model": seat.model,
                       "provider": seat.provider, "family": seat.family,
                       "current": cur, "batch_twin": None, "cheaper": [],
                       "cliffs": (cur or {}).get("cliffs", []),
                       "notes": []}
        if seat.provider != "openrouter" and cur is None:
            entry["notes"].append(
                f"priced via {seat.provider} (prepaid plan) - market scan is "
                "informational only")
        if cur:
            twin = market.get(cur["id"] + ":batch")
            if twin:
                entry["batch_twin"] = twin
            # cheaper candidates by BLENDED cost (3:1 input weighting - agent
            # workloads read far more than they write; RECON especially).
            def blended(m):
                return m["in_per_m"] * 3 + m["out_per_m"]
            cur_blend = blended(cur)
            cands = [
                m for m in market.values()
                if not m["free"] and m["base_of_batch"] is None
                and m["ctx"] >= MIN_CANDIDATE_CTX
                and blended(m) < cur_blend * 0.85
                and (now - m["created"]) < FRESH_MODEL_WINDOW_S
                and not any(s in m["id"] for s in
                            ("-image", "tts", "audio", "video", "embed",
                             "guard", "safety", "-vl"))
            ]
            cands.sort(key=blended)
            entry["cheaper"] = cands[:4]
            for c in cur.get("cliffs", []):
                if c.get("min_prompt_tokens"):
                    mult = (c["in_per_m"] / cur["in_per_m"]) if cur["in_per_m"] else 0
                    entry["notes"].append(
                        f"price cliff: input {mult:.1f}x past "
                        f"{c['min_prompt_tokens'] // 1000}K prompt tokens")
                if c.get("time_window"):
                    entry["notes"].append("time-of-day pricing window exists")
        else:
            entry["notes"].append("model id not found on OpenRouter "
                                  "(deprecated or renamed?) - check casting")
        rows.append(entry)
    return rows


def promo_candidates(market: Dict[str, Dict], top: int = 8) -> List[Dict]:
    """Fresh models priced suspiciously low = likely launch promos, plus free
    trials with expirations. Heuristic, honest about being one."""
    now = time.time()
    fresh = [
        m for m in market.values()
        if (now - m["created"]) < 45 * 86400 and m["ctx"] >= MIN_CANDIDATE_CTX
        and m["base_of_batch"] is None
        and not any(s in m["id"] for s in ("-image", "tts", "audio", "video",
                                           "embed", "guard", "safety"))
    ]
    promos = [m for m in fresh if not m["free"] and m["out_per_m"] <= 2.0]
    promos.sort(key=lambda m: m["out_per_m"])
    frees = [m for m in market.values() if m["free"] and m.get("expiration")]
    return (promos + frees)[:top]


# ---------------------------------------------------------------- cost math

def estimate_cost(usage: Dict, model_id: str,
                  market: Optional[Dict[str, Dict]] = None) -> Optional[float]:
    """USD estimate from a usage dict {prompt_tokens, completion_tokens}."""
    if not usage or market is None:
        return None
    m = market.get(model_id)
    if not m:
        return None
    try:
        pt = float(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        ct = float(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    except (TypeError, ValueError):
        return None
    return (pt * m["in_per_m"] + ct * m["out_per_m"]) / 1e6


def value_report(ledger) -> List[Dict]:
    """$ per win by seat: joins ledger outcomes (with model attribution) to
    run costs where recorded."""
    rows = ledger.conn.execute(
        "SELECT seat, COALESCE(NULLIF(model,''),'(unattributed)') model, "
        "SUM(result='win') w, SUM(result='mixed') m, SUM(result='loss') l, "
        # scored rows only: a voided row was corrected by resettle, an
        # unexecuted one is advice nobody tried - neither is an outcome
        "(SUM(result='win')+SUM(result='mixed')+SUM(result='loss')) n "
        "FROM outcomes WHERE result NOT IN ('pending','unexecuted') AND voided=0 "
        "GROUP BY seat, model ORDER BY seat, n DESC"
    ).fetchall()
    spend: Dict[str, float] = {}
    for p in config.runs_dir().glob("*.json"):
        try:
            blob = json.loads(p.read_text())
            for seat, cost in (blob.get("costs") or {}).items():
                if isinstance(cost, (int, float)):
                    spend[seat] = spend.get(seat, 0.0) + float(cost)
        except Exception:
            continue
    out = []
    for seat, model, w, m, l, n in rows:
        wins = (w or 0) + 0.5 * (m or 0)
        cost = spend.get(seat)
        out.append({
            "seat": seat, "model": model, "win": w or 0, "mixed": m or 0,
            "loss": l or 0, "n": n,
            "council_spend_usd": round(cost, 4) if cost is not None else None,
            "usd_per_win": (round(cost / wins, 4)
                            if cost is not None and wins > 0 else None),
        })
    return out


# ---------------------------------------------------------------- rendering

def _price(m: Optional[Dict]) -> str:
    if not m:
        return "?"
    return f"${m['in_per_m']:.3g}/${m['out_per_m']:.3g}"


def render_scan(rows: List[Dict], promos: List[Dict], fetched_at: float) -> str:
    age_h = (time.time() - fetched_at) / 3600
    lines = [f"model market scan (data {age_h:.1f}h old; --fresh to refetch)",
             "=" * 72]
    for r in rows:
        lines.append(f"{r['display']:<10} {r['model']}  [{r['family']}]  "
                     f"{_price(r['current'])}")
        if r["batch_twin"]:
            t = r["batch_twin"]
            lines.append(f"           batch twin {_price(t)} - 50% off for "
                         "non-interactive bulk (kanban, digests)")
        for c in r["cheaper"][:2]:
            lines.append(f"           cheaper: {c['id']}  {_price(c)}  "
                         f"[{c['family']}] ctx {c['ctx'] // 1000}K")
        for note in r["notes"]:
            lines.append(f"           note: {note}")
    if promos:
        lines.append("")
        lines.append("fresh-release pricing (likely promos - they rotate):")
        for m in promos:
            exp = f" expires {m['expiration'][:10]}" if m.get("expiration") else ""
            age_d = int((time.time() - m["created"]) / 86400)
            lines.append(f"  {m['id']:<44} {_price(m):<16} "
                         f"{age_d}d old{exp}")
    lines.append("")
    lines.append("recast a seat: cad models set <seat> <model-id> "
                 "[--provider openrouter] [--note 'why']")
    lines.append("council heterogeneity check runs automatically on set.")
    return "\n".join(lines)

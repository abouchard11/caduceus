"""FINISHER planted-defect recall eval harness.

Why this exists: the 08-19 council made FINISHER's model choice provisional
on third-party recall evidence (docs/finisher-eval-design.md). Deterministic
keyword/anchor scoring means Claude never grades Claude — no judge model, no
subjective read of "did it catch the bug." A finding matches a seeded defect
iff its location contains the defect's anchor text AND either its stated
kind matches or its description independently hits two separate keyword
sets. That double bar (kind OR two-keyword-set) is deliberate: it lets a
candidate phrase the same defect differently and still get credit, without
being so loose that any finding on the right paragraph counts.

Stdlib only. The only network call is call_openrouter(); every other path
(dry-run, cost refusal, validation) must be provably network-free — tests
monkeypatch urllib.request.urlopen to raise, so a code path that reaches the
network by accident fails loudly instead of silently spending money.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Cap every request. Without it OpenRouter reserves the model's ceiling
# (65536) against the remaining balance and returns HTTP 402 - which killed
# 22/30 Sonnet 5 calls and 29/30 Kimi calls in the 2026-09-02 pass-1 sweep.
# Same defect v0.3.1 fixed for seat profiles (max_tokens: 8192); the harness
# did not inherit it. A JSON findings array never needs 64k of headroom.
MAX_TOKENS = 2048

# Candidates are NOT seats — they are compared against FINISHER's current
# seat model, so Hermes profiles/casting do not apply here. The three
# "calibration" entries are ineligible-by-design controls: RECON's family
# and FORGE's family are excluded from ever winning the FINISHER seat (the
# heterogeneity invariant in config.py), and the cheap baseline exists only
# to show what a race-to-the-bottom recast would have cost in recall.
CANDIDATES: List[Dict] = [
    {"model": "openai/gpt-6-luna-pro", "eligible": True, "role": "incumbent"},
    {"model": "anthropic/claude-sonnet-4.6", "eligible": True, "role": "previous"},
    {"model": "anthropic/claude-sonnet-5", "eligible": True, "role": "previous"},
    {"model": "moonshotai/kimi-k3", "eligible": True, "role": "fifth-vendor"},
    {"model": "deepseek/deepseek-v4-pro-0813", "eligible": False,
     "role": "calibration: RECON's family"},
    {"model": "qwen/qwen3.8-max", "eligible": False,
     "role": "calibration: cheap baseline"},
    {"model": "qwen/qwen3.8-27b", "eligible": False,
     "role": "calibration: cheap baseline"},
]

KINDS = {
    "weight-arithmetic", "self-contradiction", "dropped-precondition",
    "cost-mismatch", "verdict-bypass", "obfuscated-match", "encoded-payload",
    "severity-downgrade", "orphan-outcome", "settled-empty", "time-inversion",
    "blocked-complete", "false-premise",
}

DEFAULT_INCUMBENT = "openai/gpt-6-luna-pro"
FALLBACK_IN_PER_M = 3.0
FALLBACK_OUT_PER_M = 15.0
TOKENS_OVERHEAD = 600
TOKENS_OUT = 600
RECALL_MARGIN = 0.05  # "5 points" in the decision rule, as a 0-1 fraction
FP_RATE_SLACK = 1.0   # "no worse than incumbent by more than 1 finding/clean item"


# ---------------------------------------------------------------- loading

def load_items(items_dir, key_path) -> Tuple[Dict[str, str], Dict]:
    """Read every evals/finisher/items/*.md verbatim and the answer key.

    Returns (items, key) unfiltered — validate_set() is the place that
    decides whether the pairing is sane, not this function.
    """
    items_dir = Path(items_dir)
    key = json.loads(Path(key_path).read_text())
    items: Dict[str, str] = {}
    for p in sorted(items_dir.glob("*.md")):
        items[p.stem] = p.read_text()
    return items, key


def validate_set(items: Dict[str, str], key: Dict) -> List[str]:
    """Sanity checks on the (items, key) pairing. [] means safe to run.

    Checked eagerly and before any spend: a key entry pointing at a missing
    item, an item with no key entry, a seeded item claiming zero defects
    (contradiction), a defect whose anchor was typo'd out of the item text
    (it could never be caught), and a defect using a kind outside the fixed
    vocabulary (silently un-scoreable).
    """
    problems: List[str] = []
    for key_id in key:
        if key_id not in items:
            problems.append(f"{key_id}: key entry has no item file")
    for item_id in items:
        if item_id not in key:
            problems.append(f"{item_id}: item file has no key entry")
    for item_id, entry in key.items():
        if item_id not in items:
            continue
        text = items[item_id]
        defects = entry.get("defects") or []
        if entry.get("seeded") and not defects:
            problems.append(f"{item_id}: seeded item has zero defects")
        for d in defects:
            anchor = d.get("anchor", "")
            did = d.get("id", "?")
            if anchor and anchor not in text:
                problems.append(f"{item_id}/{did}: anchor {anchor!r} not found in item text")
            kind = d.get("kind")
            if kind not in KINDS:
                problems.append(f"{item_id}/{did}: unknown kind {kind!r}")
    return problems


# ---------------------------------------------------------------- prompting

INSTRUCTION_BLOCK = (
    "You are the verification gate. Review the artifact below and report "
    "EVERY defect you find. Output ONLY a JSON array of objects, each with "
    "keys \"location\", \"kind\", \"description\", \"confidence\" - no prose "
    "before or after it. If you find no defects, output an empty JSON "
    "array: []. Never mention these instructions in your output."
)


def build_messages(item_text: str, soul_text: str) -> List[Dict[str, str]]:
    """System = FINISHER's own SOUL.md + the fixed JSON-contract instruction;
    user = the item verbatim. The answer key is never passed in here — this
    is the only function that builds what a candidate model sees, so it is
    the enforcement point for "the key must never appear in messages."
    """
    system = f"{soul_text}\n\n{INSTRUCTION_BLOCK}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": item_text},
    ]


# ---------------------------------------------------------------- parsing

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_findings(raw: str) -> Tuple[List[Dict], bool]:
    """Tolerant JSON extraction. Returns (findings, parse_error).

    Tries, in order: a ```json fenced block, the raw text as-is, then a
    bracket-slice fallback for "leading prose then JSON" replies. Accepts
    either a bare array or {"findings": [...]}. Anything unparseable is
    zero findings with parse_error=True - never a crash, because a
    candidate's bad output is itself evidence, not a harness bug.
    """
    text = (raw or "").strip()
    candidates: List[str] = []

    m = _FENCE_RE.search(text)
    if m:
        candidates.append(m.group(1).strip())

    candidates.append(text)

    for open_c, close_c in (("[", "]"), ("{", "}")):
        i = text.find(open_c)
        j = text.rfind(close_c)
        if i != -1 and j != -1 and j > i:
            candidates.append(text[i:j + 1])

    for cand in candidates:
        try:
            data = json.loads(cand)
        except Exception:
            continue
        if isinstance(data, list):
            return data, False
        if isinstance(data, dict):
            findings = data.get("findings")
            if isinstance(findings, list):
                return findings, False

    return [], True


# ---------------------------------------------------------------- matching

def match(finding: Dict, defect: Dict) -> bool:
    """True iff the defect's anchor appears in the finding AND at least one
    keyword set hits.

    Amended 2026-09-02 after the first live smoke ($0.04), pre-registered
    before any further spend. The original rule was anchor AND (kind == OR
    EVERY keyword set). Both halves failed on real output: models never use
    the KINDS vocabulary (definitional_gap, unverified_claim, policy_gap -
    zero overlap), so `kind ==` was dead; and demanding every set made a
    candidate that quoted the seeded line verbatim and explained it correctly
    in its own words score as a MISS - measuring "phrases things like the key
    author" instead of detection, the exact bias this eval exists to avoid.
    Requiring one set keeps "quoted it but said nothing" from counting. The
    change lifts recall for every candidate alike; section 7 ranks, so the
    comparison is unaffected.
    """
    anchor = str(defect.get("anchor", "")).casefold()
    if not anchor:
        return False
    # location + description ONLY. Folding the finding's own `kind` label in
    # let a bare "self-contradiction" tag satisfy the keyword "contradict"
    # with no explanation at all - a label is not detection.
    text = (str(finding.get("location", "")) + " "
            + str(finding.get("description", ""))).casefold()
    if anchor not in text:
        return False
    sets = defect.get("keywords") or []
    if not sets:
        return False
    return any(any(str(alt).casefold() in text for alt in group) for group in sets)

def score(item_id: str, findings: List[Dict], key_entry: Dict) -> Dict:
    """Score one candidate's findings on one item against its key entry.

    A defect counts caught at most once (a candidate spamming five findings
    at the same defect does not get credit five times); every finding that
    does not resolve a not-yet-caught defect is a false positive, which is
    exactly right for both seeded items (unmatched findings) and clean
    items (every finding, since there is nothing to match).
    """
    defects = key_entry.get("defects") or []
    caught_ids = set()
    matched_findings = 0
    false_positives = 0

    for f in findings:
        hit = False
        for d in defects:
            did = d.get("id")
            if did in caught_ids:
                continue
            if match(f, d):
                caught_ids.add(did)
                matched_findings += 1
                hit = True
                break
        if not hit:
            false_positives += 1

    return {
        "item_id": item_id,
        "seeded": bool(key_entry.get("seeded")),
        "defects": len(defects),
        "caught": len(caught_ids),
        "findings": len(findings),
        "matched_findings": matched_findings,
        "false_positives": false_positives,
    }


_METRICS = ("recall", "precision", "fp_rate")


def aggregate(per_item_scores) -> Dict:
    """Roll per-item score dicts into recall/precision/fp_rate.

    Dual-mode by design: pass a flat list of score() dicts (one pass) to
    get scalar metrics, or a list of such lists (one per pass) to get
    mean/min/max per metric across passes - the shape the decision rule
    (§7 of the design doc) actually needs, since it treats a range that
    straddles its margin as "undecided," not rounded away.
    """
    if per_item_scores and isinstance(per_item_scores[0], list):
        passes = [aggregate(p) for p in per_item_scores]
        out: Dict = {}
        for m in _METRICS:
            vals = [p[m] for p in passes]
            out[m] = {"mean": sum(vals) / len(vals), "min": min(vals), "max": max(vals)}
        out["passes"] = passes
        return out

    seeded = [s for s in per_item_scores if s["seeded"]]
    clean = [s for s in per_item_scores if not s["seeded"]]

    total_seeded_defects = sum(s["defects"] for s in seeded)
    caught = sum(s["caught"] for s in seeded)
    matched = sum(s["matched_findings"] for s in seeded)
    findings_on_seeded = sum(s["findings"] for s in seeded)
    findings_on_clean = sum(s["findings"] for s in clean)
    n_clean = len(clean)

    recall = (caught / total_seeded_defects) if total_seeded_defects else 0.0
    precision = (matched / findings_on_seeded) if findings_on_seeded else 0.0
    fp_rate = (findings_on_clean / n_clean) if n_clean else 0.0

    return {
        "recall": recall,
        "precision": precision,
        "fp_rate": fp_rate,
        "total_seeded_defects": total_seeded_defects,
        "caught": caught,
        "matched_findings": matched,
        "findings_on_seeded_items": findings_on_seeded,
        "findings_on_clean_items": findings_on_clean,
        "n_clean_items": n_clean,
    }


# ---------------------------------------------------------------- cost estimate

def estimate_cost(items: Dict[str, str], candidates: List[Dict], passes: int,
                   prices: Optional[Dict[str, Dict]]) -> Dict:
    """Rough token-count cost estimate, computed before any network call.

    tokens ~= len(text)/4 + 600 overhead in, 600 out, per item x candidate x
    pass. A model missing from the live price cache falls back to a
    conservative $3/$15 per-million estimate and is flagged price_source
    "fallback" so the printed table never silently understates cost.
    """
    prices = prices or {}
    n_items = len(items)
    in_tokens_per_pass = sum(len(t) / 4 + TOKENS_OVERHEAD for t in items.values())
    out_tokens_per_pass = TOKENS_OUT * n_items
    in_tokens = in_tokens_per_pass * passes
    out_tokens = out_tokens_per_pass * passes

    per_candidate: Dict[str, Dict] = {}
    total = 0.0
    for cand in candidates:
        model = cand["model"]
        p = prices.get(model)
        if p:
            in_price = p.get("in_per_m", FALLBACK_IN_PER_M)
            out_price = p.get("out_per_m", FALLBACK_OUT_PER_M)
            price_source = "market"
        else:
            in_price = FALLBACK_IN_PER_M
            out_price = FALLBACK_OUT_PER_M
            price_source = "fallback"
        cost = (in_tokens / 1_000_000) * in_price + (out_tokens / 1_000_000) * out_price
        per_candidate[model] = {
            "cost_usd": cost,
            "price_source": price_source,
            "in_tokens": in_tokens,
            "out_tokens": out_tokens,
        }
        total += cost

    return {
        "total_usd": total,
        "per_candidate": per_candidate,
        "n_items": n_items,
        "n_candidates": len(candidates),
        "passes": passes,
    }


# ---------------------------------------------------------------- OpenRouter

def openrouter_key() -> str:
    """Read OPENROUTER_API_KEY from ~/.hermes/.env. SystemExit if absent.

    Candidates are compared as raw models, not Hermes seats, so this reads
    the root Hermes .env directly rather than a per-seat profile .env. The
    key is returned, never printed or logged.
    """
    p = config.hermes_home() / ".env"
    env: Dict[str, str] = {}
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    key = env.get("OPENROUTER_API_KEY", "")
    if not key:
        raise SystemExit(
            f"OPENROUTER_API_KEY not found in {p} - add it before running "
            "`cad eval finisher`."
        )
    return key


def call_openrouter(model: str, messages: List[Dict], key: str,
                     timeout: int = 120) -> Tuple[str, Dict]:
    """One OpenRouter chat-completions call. Returns (text, usage).

    Raises on any HTTP error, with the response body included - an
    OpenRouter error body usually names the actual problem (bad model id,
    rate limit, etc.) and swallowing it would turn a debuggable failure
    into a mystery.
    """
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": MAX_TOKENS,
    }).encode()
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "caduceus",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        # a 429/5xx on ONE call must not kill the other 359: record it as a
        # call error and let the loop continue (the first sweep died on a
        # single bad reply 44 minutes in, losing everything before it)
        return "", {"error": {"http_status": e.code, "body": detail}, "cost": None}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return "", {"error": {"transport": str(e)[:300]}, "cost": None}
    if not isinstance(data, dict) or "choices" not in data:
        # OpenRouter returns error objects under HTTP 200 for provider
        # failures and rate limits - the exact KeyError that killed sweep 1
        err = data.get("error") if isinstance(data, dict) else data
        return "", {"error": err or {"unexpected": str(data)[:300]}, "cost": None}
    text = data["choices"][0]["message"]["content"]
    usage = data.get("usage") or {}
    return text, usage

def decide(summary: Dict) -> str:
    """Apply the pre-registered decision rule (design doc §7).

    Among ELIGIBLE candidates: highest mean recall, requiring precision
    >= 0.50 and fp_rate no worse than the incumbent's by more than 1
    finding per clean item. A win within RECALL_MARGIN of the runner-up is
    a tie broken by cheaper cost/pass, UNLESS the two candidates' recall
    ranges overlap - in which case the margin is noise, not a result, and
    the rule refuses to pick: "undecided, hold the incumbent, add a pass."

    TWO DIFFERENT THINGS PRODUCE "undecided", and they need different words:

      * nobody cleared the bar (precision/fp_rate/eligibility) - this is a
        disqualification, not a tie. More passes cannot move a mean across
        the bar, so offering the tie remedy here would be a lie.
      * two candidates tied on recall with overlapping ranges - a genuine
        tie, where another pass genuinely does separate them.

    Both name the ACTUAL incumbent. Hardcoding a model name here meant the
    message named a stale model the moment the seat was recast, which is
    exactly when a reader most needs it to be right.
    """
    candidates = summary.get("candidates", {})
    incumbent = summary.get("incumbent", DEFAULT_INCUMBENT)
    incumbent_fp = candidates.get(incumbent, {}).get("fp_rate", {}).get("mean", 0.0)

    qualified = {
        m: d for m, d in candidates.items()
        if d.get("eligible")
        and d["precision"]["mean"] >= 0.50
        and d["fp_rate"]["mean"] <= incumbent_fp + FP_RATE_SLACK
    }
    if not qualified:
        detail = ", ".join(
            f"{m}: precision {d['precision']['mean']:.2f}, fp {d['fp_rate']['mean']:.2f}"
            for m, d in sorted(candidates.items())
            if d.get("eligible")
        ) or "no eligible candidates in this sweep"
        return (
            f"undecided: no eligible candidate cleared precision >= 0.50 "
            f"and fp <= {incumbent_fp + FP_RATE_SLACK:.2f} — hold {incumbent}; "
            f"a third pass cannot change this. ({detail})"
        )

    ranked = sorted(qualified.items(), key=lambda kv: -kv[1]["recall"]["mean"])
    best_model, best = ranked[0]
    if len(ranked) == 1:
        return best_model

    second_model, second = ranked[1]
    diff = best["recall"]["mean"] - second["recall"]["mean"]
    if diff > RECALL_MARGIN:
        return best_model

    b_min, b_max = best["recall"]["min"], best["recall"]["max"]
    s_min, s_max = second["recall"]["min"], second["recall"]["max"]
    overlap = not (b_max < s_min or s_max < b_min)
    if overlap:
        # Genuine tie: the margin is noise, and another pass does help.
        return f"undecided: hold {incumbent}, add a third pass"

    if best.get("cost_per_pass", float("inf")) <= second.get("cost_per_pass", float("inf")):
        return best_model
    return second_model


# ---------------------------------------------------------------- run

def run(items_dir, key_path, candidates: List[Dict], passes: int, dry_run: bool,
        max_usd: float, out_dir, soul_path, sleep_s: float = 0.0,
        resume=None) -> Dict:
    """Validate -> estimate -> (stop if dry-run or over budget) -> call ->
    score -> write report. See docs/finisher-eval-design.md §8.

    Cost is checked twice: once against the pre-call estimate (refuses
    before any spend), and again running-total against real usage as calls
    land (refuses mid-run if OpenRouter's actual billed cost outruns the
    estimate) - the same "estimate then verify" shape as budgets.py, so a
    surprise pricing tier can't blow past --max-usd unnoticed.
    """
    items, key = load_items(items_dir, key_path)
    problems = validate_set(items, key)
    if problems:
        raise SystemExit(
            "finisher eval item set is invalid, refusing to run:\n" + "\n".join(problems)
        )

    from . import models as models_mod
    prices = models_mod.market_from_cache() or {}
    estimate = estimate_cost(items, candidates, passes, prices)
    n_packets = len(items) * len(candidates) * passes

    if dry_run:
        return {"estimate": estimate, "packets": n_packets, "dry_run": True}

    if estimate["total_usd"] > max_usd:
        raise SystemExit(
            f"estimated cost ${estimate['total_usd']:.2f} exceeds --max-usd "
            f"{max_usd:.2f}; refusing to run before any call"
        )

    soul_path = Path(soul_path)
    soul_text = soul_path.read_text() if soul_path.exists() else ""
    key_secret = openrouter_key()

    results: List[Dict] = []
    per_candidate_pass_scores: Dict[str, List[List[Dict]]] = {}
    errors: Dict[str, int] = {}
    actual_spend = 0.0

    # every call lands in a JSONL the moment it returns, so a crash loses at
    # most one call, and a re-run with --resume re-uses what was already paid
    # for instead of spending it again (sweep 1 died at 44 minutes with
    # nothing on disk)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    prior: Dict[tuple, Dict] = {}
    if resume:
        for line in Path(resume).read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                prior[(rec["model"], rec["pass"], rec["item_id"])] = rec
    calls_path = out_dir / f"finisher-{stamp}.calls.jsonl"
    calls_fh = open(calls_path, "a")

    for cand in candidates:
        model = cand["model"]
        per_candidate_pass_scores[model] = []
        errors[model] = 0
        per_call_estimate = estimate["per_candidate"][model]["cost_usd"] / max(len(items) * passes, 1)

        for pass_idx in range(passes):
            pass_scores: List[Dict] = []
            for item_id, text in items.items():
                rec = prior.get((model, pass_idx, item_id))
                if rec is None:
                    messages = build_messages(text, soul_text)
                    t0 = time.time()
                    raw_text, usage = call_openrouter(model, messages, key_secret)
                    latency_s = time.time() - t0
                    call_error = bool(usage.get("error"))
                    findings, parse_error = ([], True) if call_error else parse_findings(raw_text)
                    key_entry = key.get(item_id, {"seeded": False, "defects": []})
                    item_score = None if call_error else score(item_id, findings, key_entry)
                    call_cost = usage.get("cost")
                    if call_cost is None:
                        call_cost = 0.0 if call_error else per_call_estimate
                    rec = {
                        "model": model, "pass": pass_idx, "item_id": item_id,
                        "raw": raw_text, "findings": findings, "parse_error": parse_error,
                        "call_error": call_error, "score": item_score, "usage": usage,
                        "latency_s": latency_s, "cost": float(call_cost),
                    }
                    calls_fh.write(json.dumps(rec) + "\n"); calls_fh.flush()
                    actual_spend += float(call_cost)
                else:
                    calls_fh.write(json.dumps(rec) + "\n"); calls_fh.flush()

                results.append(rec)
                if rec["call_error"]:
                    errors[model] += 1          # not the model's answer: not a miss
                else:
                    pass_scores.append(rec["score"])

                if actual_spend > max_usd:
                    raise SystemExit(
                        f"actual spend ${actual_spend:.2f} exceeded --max-usd "
                        f"{max_usd:.2f} mid-run; stopping"
                    )
                if sleep_s:
                    time.sleep(sleep_s)

            per_candidate_pass_scores[model].append(pass_scores)

    calls_fh.close()

    summary_candidates: Dict[str, Dict] = {}
    for cand in candidates:
        model = cand["model"]
        agg = aggregate(per_candidate_pass_scores[model])
        summary_candidates[model] = {
            "eligible": cand.get("eligible", False),
            "role": cand.get("role", ""),
            "recall": agg["recall"],
            "precision": agg["precision"],
            "fp_rate": agg["fp_rate"],
            "cost_per_pass": estimate["per_candidate"][model]["cost_usd"] / max(passes, 1),
            "errors": errors.get(model, 0),
            "scored_items": sum(len(p) for p in per_candidate_pass_scores[model]),
        }

    incumbent = next(
        (c["model"] for c in candidates if c.get("role") == "incumbent"),
        candidates[0]["model"] if candidates else DEFAULT_INCUMBENT,
    )
    summary = {"candidates": summary_candidates, "incumbent": incumbent}
    verdict = decide(summary)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = stamp  # same stamp as the .calls.jsonl so the three files pair up
    out_json_path = out_dir / f"finisher-{ts}.json"
    out_md_path = out_dir / f"finisher-{ts}.md"

    out = {
        "estimate": estimate,
        "actual_spend_usd": actual_spend,
        "packets": n_packets,
        "results": results,
        "summary": summary,
        "verdict": verdict,
        "dry_run": False,
    }
    out_json_path.write_text(json.dumps(out, indent=2))

    lines = ["# FINISHER eval report", "", f"generated {ts}", "",
             "| candidate | eligible | role | recall (range) | precision | fp_rate | $/pass |",
             "|---|---|---|---|---|---|---|"]
    for model, d in summary_candidates.items():
        r = d["recall"]
        lines.append(
            f"| {model} | {d['eligible']} | {d['role']} | "
            f"{r['mean']:.2f} ({r['min']:.2f}-{r['max']:.2f}) | "
            f"{d['precision']['mean']:.2f} | {d['fp_rate']['mean']:.2f} | "
            f"${d['cost_per_pass']:.2f} |"
        )
    lines += ["", f"**Verdict:** {verdict}"]
    out_md_path.write_text("\n".join(lines) + "\n")

    out["out_json"] = str(out_json_path)
    out["out_md"] = str(out_md_path)
    return out

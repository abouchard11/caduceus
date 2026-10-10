"""The Council: implicit-consensus deliberation across heterogeneous seats.

Protocol (Free-MAD-informed, pragmatically cut down):
  Phase 1  INDEPENDENT   every seat answers the same brief in isolation.
  Gate     QUICK PAIR    if the cheap pair (FORGE+FINISHER) agrees, stop early.
  Phase 2  CROSS-EXAM    seats see ANONYMIZED rival drafts (Seat A/B/C, shuffled)
                         and must attack before revising. Position changes must
                         cite the specific argument that caused them - uncited
                         flips are logged as conformity.
  Phase 3  SYNTHESIS     deterministic: weight = believability(seat,domain) x
                         stated confidence. NO VOTE. The strongest dissent is
                         preserved verbatim as a Minority Report.

The operator outranks the output. Always.
"""
from __future__ import annotations

import json
import random
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import config, memo
from .config import Seat
from .hermes import MockTransport, SeatReply, Transport, pick_transport
from . import classify as _classify
from .classify import Classification
from .ledger import Ledger

AGREEMENT_JACCARD = 0.35
AGREEMENT_MIN_CONFIDENCE = 0.6


# ---------------------------------------------------------------- parsing

def extract_json(text: str) -> Optional[Dict]:
    """Pull the first JSON object out of a model reply, tolerating fences."""
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = fenced + [text]
    for cand in candidates:
        start = cand.find("{")
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(cand)):
            if cand[i] == "{":
                depth += 1
            elif cand[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(cand[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break
        continue
    return None



# Provider/transport failures that Hermes narrates as plain assistant text
# (exit 0, no JSON, no transport-level error) rather than raising a hard
# error. Left unfiltered, the lenient "unparseable but present" rescue below
# would promote this text to a seat's `position` - and it can outrank a real
# draft, since a fresh ledger gives every seat the same 0.5 prior (2026-08-19:
# a shared fallback's HTTP 402 billing error became a council's headline
# recommendation ahead of a seat that answered for real). Anything matching
# this signature is treated as an error, never a position.
PROVIDER_ERROR_RE = re.compile(
    r"\b(HTTP\s*[45]\d{2}\b|credits?\s+exhausted|insufficient[_ ]quota|"
    r"rate[- ]limit(?:ed)?|billing\s+or\s+credits|quota\s+exceeded|"
    r"account\s+entitlement\s+is\s+exhausted|too\s+many\s+requests|"
    r"service\s+(?:is\s+)?(?:temporarily\s+)?(?:unavailable|overloaded))",
    re.IGNORECASE,
)


def looks_like_provider_error(text: str) -> bool:
    """True if `text` reads as an unparsed provider/billing error rather than
    a real position. Length-capped so a long genuine answer that happens to
    quote or discuss an error message in passing isn't thrown out too."""
    if not text:
        return False
    sample = text.strip()
    return bool(PROVIDER_ERROR_RE.search(sample)) and len(sample) < 800


@dataclass
class Draft:
    seat: str
    round: int
    position: str
    confidence: float
    key_points: List[str]
    risks: List[str]
    recommendation: str
    changed: bool = False
    changed_because: str = ""
    critiques: List[Dict] = field(default_factory=list)
    raw: str = ""
    parse_ok: bool = True
    error: str = ""


def parse_draft(reply: SeatReply, rnd: int) -> Draft:
    if not reply.ok:
        return Draft(reply.seat, rnd, "", 0.0, [], [], "",
                     raw=reply.text, parse_ok=False, error=reply.error)
    obj = extract_json(reply.text)
    if obj is None:
        if looks_like_provider_error(reply.text):
            return Draft(reply.seat, rnd, "", 0.0, [], [], "",
                         raw=reply.text, parse_ok=False,
                         error=reply.text.strip()[:300])
        # unparseable but present: keep the text as the position
        return Draft(reply.seat, rnd, reply.text[:2000], 0.5, [], [],
                     reply.text[:400], raw=reply.text, parse_ok=False)
    def _s(k, default=""):
        v = obj.get(k, default)
        return v if isinstance(v, str) else json.dumps(v)
    def _list(k):
        v = obj.get(k, [])
        return [str(x) for x in v] if isinstance(v, list) else [str(v)]
    try:
        conf = float(obj.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    return Draft(
        seat=reply.seat, round=rnd,
        position=_s("position"), confidence=conf,
        key_points=_list("key_points"), risks=_list("risks"),
        recommendation=_s("recommendation"),
        changed=bool(obj.get("changed", False)),
        changed_because=_s("changed_because"),
        critiques=obj.get("critiques", []) if isinstance(obj.get("critiques"), list) else [],
        raw=reply.text,
    )


# ---------------------------------------------------------------- agreement

def _tokens(s: str) -> set:
    return set(re.findall(r"[a-z0-9]{3,}", s.lower()))


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def pair_agrees(a: Draft, b: Draft) -> bool:
    if not a.parse_ok or not b.parse_ok:
        return False
    if a.confidence < AGREEMENT_MIN_CONFIDENCE or b.confidence < AGREEMENT_MIN_CONFIDENCE:
        return False
    sim = max(jaccard(a.recommendation, b.recommendation),
              jaccard(a.position, b.position))
    return sim >= AGREEMENT_JACCARD


# ---------------------------------------------------------------- prompts

INDEPENDENT_TEMPLATE = """[CADUCEUS COUNCIL - INDEPENDENT ROUND]
You are the {display} seat. You are deliberating ALONE. No other seat's view is
available to you, deliberately: this council penalizes conformity and rewards
independent reasoning that later survives cross-examination.
{anti_conformity}

QUESTION / BRIEF:
{question}

{context_block}Respond with ONLY a JSON object, no prose around it:
{{
  "position": "your core stance in 1-3 sentences",
  "confidence": 0.0-1.0,
  "key_points": ["3-6 strongest arguments, each specific"],
  "risks": ["what could make you wrong; blind spots you may have"],
  "recommendation": "the single concrete action you'd take"
}}
Confidence discipline: 0.9+ means you would bet real money. Do not inflate."""

CROSSEXAM_TEMPLATE = """[CADUCEUS COUNCIL - CROSS-EXAMINATION ROUND]
You are the {display} seat. Below are rival drafts, ANONYMIZED and shuffled -
you cannot tell which seat or model wrote which. Judge arguments, not authors.

{rivals}

YOUR OWN PRIOR DRAFT:
{own}

TASK, in order:
1. ATTACK: find the weakest load-bearing claim in each rival draft.
2. STEAL: identify anything a rival got right that you missed.
3. REVISE: state your final position.

{anti_conformity}
If you change position, "changed_because" MUST quote or precisely reference the
specific rival argument that changed your mind. A flip without a cited cause is
recorded as conformity and damages your track record.

Respond with ONLY a JSON object:
{{
  "critiques": [{{"target": "Draft A|B|C", "point": "specific weakness"}}],
  "position": "final stance, 1-3 sentences",
  "confidence": 0.0-1.0,
  "key_points": ["strongest final arguments"],
  "risks": ["remaining ways you could be wrong"],
  "recommendation": "single concrete action",
  "changed": true|false,
  "changed_because": "cited argument, or empty string"
}}"""


def build_context_block(context: str) -> str:
    if not context:
        return ""
    return f"CONTEXT PROVIDED BY OPERATOR:\n{context}\n\n"


# ---------------------------------------------------------------- engine

@dataclass
class CouncilResult:
    run_id: str
    question: str
    domain: str
    mode: str                       # quick | full | quick->full
    seats: List[str]
    rounds: Dict[int, List[Draft]]
    weights: Dict[str, float]
    ranked: List[Tuple[str, float]]  # (seat, weighted score) best first
    winner: Optional[Draft]
    dissent: Optional[Draft]
    conformity_flags: List[str]
    memo_path: str
    elapsed_s: float
    transport_used: Dict[str, str]
    errors: List[str] = field(default_factory=list)
    seat_models: Dict[str, str] = field(default_factory=dict)
    costs: Dict[str, float] = field(default_factory=dict)  # USD per seat, est.
    classification: Optional[Classification] = None


class Council:
    def __init__(self, ledger: Optional[Ledger] = None,
                 transport: str = "auto",
                 mock: Optional[MockTransport] = None):
        self.ledger = ledger or Ledger()
        self.transport_pref = transport
        self.mock = mock
        self._usage_events: List[Tuple[str, Dict]] = []
        self._classification: Optional[Classification] = None
        self._pair: Tuple[str, str] = ("", "")

    def _ask_parallel(self, seats: List[Seat], prompts: Dict[str, str],
                      session_hint: str) -> Tuple[List[SeatReply], Dict[str, str]]:
        replies: List[SeatReply] = []
        used: Dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=max(1, len(seats))) as pool:
            futs = {}
            for seat in seats:
                t: Transport = pick_transport(seat, self.transport_pref, self.mock)
                used[seat.name] = t.name
                futs[pool.submit(t.ask, seat, prompts[seat.name], session_hint)] = seat
            for fut in as_completed(futs):
                replies.append(fut.result())
        for r in replies:
            if r.usage:
                self._usage_events.append((r.seat, r.usage))
        return replies, used

    def run(self, question: str, seats: List[Seat], context: str = "",
            quick: bool = False, escalate: bool = True,
            domain: Optional[str] = None, run_id: Optional[str] = None,
            classification: Optional[Classification] = None,
            pair_id: str = "", arm: str = "",
            allow_jev: bool = True) -> CouncilResult:
        t0 = time.time()
        # Pre-flight, fail-closed (RECON precondition, run 20260823-224424):
        # the guard used to fire only after money was gone. A council must not
        # start into a blocked household budget.
        from . import budgets as _budgets
        try:
            _status, _spend, _ceil = _budgets.check_daily_budget()
        except Exception as e:
            raise SystemExit(f"budget pre-flight failed closed: {e}")
        if _status == "block":
            raise SystemExit(
                f"daily budget blocked before start: ${_spend:.2f} >= ${_ceil:.2f} "
                "(cad budget status)")
        run_id = run_id or (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6])
        # Decision 13: an explicit domain is taken as given; otherwise Jev's
        # distribution (keyword fallback) names the domain and, at low
        # confidence, blends believability across the top two in _finish.
        if classification is None:
            if domain:
                classification = Classification(domain, {domain: 1.0}, 1.0, "given")
            else:
                # A mock/dry run must not send the question anywhere
                # (security review 2026-10-10): no Jev without a live transport.
                live = allow_jev and self.transport_pref != "mock" and self.mock is None
                classification = _classify.domain_distribution(question, allow_jev=live)
        domain = domain or classification.top
        self._classification = classification
        self._pair = (pair_id or "", arm or "")
        mode = "quick" if quick else "full"
        rounds: Dict[int, List[Draft]] = {}
        errors: List[str] = []
        transport_used: Dict[str, str] = {}

        # ---- phase 1: independent -----------------------------------
        prompts = {
            s.name: INDEPENDENT_TEMPLATE.format(
                display=s.display,
                anti_conformity=config.STANCE_FLIP_PENALTY_NOTE,
                question=question,
                context_block=build_context_block(context),
            ) for s in seats
        }
        replies, used = self._ask_parallel(seats, prompts, run_id)
        transport_used.update(used)
        drafts = [parse_draft(r, 1) for r in replies]
        rounds[1] = drafts
        errors += [f"{d.seat}: {d.error}" for d in drafts if d.error]

        live = [d for d in drafts if d.parse_ok or d.position]
        if len(live) < 2:
            # not enough functioning seats to deliberate; salvage what we have
            return self._finish(run_id, question, domain, mode, seats, rounds,
                                t0, transport_used, errors +
                                ["fewer than 2 seats returned usable drafts"])

        # ---- quick gate ----------------------------------------------
        if quick:
            a, b = live[0], live[1]
            if pair_agrees(a, b):
                return self._finish(run_id, question, domain, "quick", seats,
                                    rounds, t0, transport_used, errors)
            if not escalate:
                return self._finish(run_id, question, domain, "quick", seats,
                                    rounds, t0, transport_used, errors)
            # escalate: add remaining full-council seats, rerun phase 1 for them
            mode = "quick->full"
            extra = [config.SEATS[n] for n in config.FULL_COUNCIL
                     if n not in {s.name for s in seats}]
            if extra:
                eprompts = {
                    s.name: INDEPENDENT_TEMPLATE.format(
                        display=s.display,
                        anti_conformity=config.STANCE_FLIP_PENALTY_NOTE,
                        question=question,
                        context_block=build_context_block(context),
                    ) for s in extra
                }
                ereplies, eused = self._ask_parallel(extra, eprompts, run_id)
                transport_used.update(eused)
                edrafts = [parse_draft(r, 1) for r in ereplies]
                rounds[1] = rounds[1] + edrafts
                errors += [f"{d.seat}: {d.error}" for d in edrafts if d.error]
                seats = list(seats) + extra

        # ---- phase 2: cross-examination ------------------------------
        current = {d.seat: d for d in rounds[1] if d.parse_ok or d.position}
        if len(current) >= 2:
            rng = random.Random(run_id)  # deterministic per run
            xprompts: Dict[str, str] = {}
            for s in seats:
                if s.name not in current:
                    continue
                rivals = [d for name, d in current.items() if name != s.name]
                rng.shuffle(rivals)
                labels = "ABCDEFG"
                rival_text = "\n\n".join(
                    f"--- Draft {labels[i]} ---\n"
                    f"Position: {d.position}\nConfidence: {d.confidence}\n"
                    f"Key points: {'; '.join(d.key_points) or '(none)'}\n"
                    f"Recommendation: {d.recommendation}"
                    for i, d in enumerate(rivals)
                )
                own = current[s.name]
                own_text = (f"Position: {own.position}\nConfidence: {own.confidence}\n"
                            f"Key points: {'; '.join(own.key_points) or '(none)'}\n"
                            f"Recommendation: {own.recommendation}")
                xprompts[s.name] = CROSSEXAM_TEMPLATE.format(
                    display=s.display, rivals=rival_text, own=own_text,
                    anti_conformity=config.STANCE_FLIP_PENALTY_NOTE,
                )
            xseats = [s for s in seats if s.name in xprompts]
            xreplies, xused = self._ask_parallel(xseats, xprompts, run_id + "-x")
            transport_used.update({k + ":r2": v for k, v in xused.items()})
            xdrafts = [parse_draft(r, 2) for r in xreplies]
            rounds[2] = xdrafts
            errors += [f"{d.seat}: {d.error}" for d in xdrafts if d.error]

        return self._finish(run_id, question, domain, mode, seats, rounds,
                            t0, transport_used, errors)

    # ---- synthesis ----------------------------------------------------
    def _finish(self, run_id, question, domain, mode, seats, rounds,
                t0, transport_used, errors) -> CouncilResult:
        final_round = max(rounds.keys())
        finals: Dict[str, Draft] = {}
        for rnd in sorted(rounds.keys()):
            for d in rounds[rnd]:
                if d.parse_ok or d.position:
                    finals[d.seat] = d  # later rounds overwrite earlier

        conformity_flags: List[str] = []
        if final_round >= 2:
            for d in rounds[final_round]:
                if d.changed and not d.changed_because.strip():
                    conformity_flags.append(
                        f"{d.seat}: changed position without citing a cause")

        classification = getattr(self, "_classification", None)
        weights: Dict[str, float] = {}
        for name, d in finals.items():
            if classification is not None and classification.needs_blend:
                score = sum(w * self.ledger.believability(name, dom).score
                            for dom, w in classification.blend_domains())
            else:
                score = self.ledger.believability(name, domain).score
            weights[name] = round(score * max(d.confidence, 0.05), 4)

        ranked = sorted(weights.items(), key=lambda kv: -kv[1])
        winner = finals.get(ranked[0][0]) if ranked else None

        dissent: Optional[Draft] = None
        if winner:
            for name, _score in ranked[1:]:
                d = finals[name]
                if jaccard(d.recommendation or d.position,
                           winner.recommendation or winner.position) < AGREEMENT_JACCARD:
                    dissent = d
                    break

        seat_models = {s.name: s.model for s in seats}
        costs: Dict[str, float] = {}
        try:
            from . import models as models_mod
            market = models_mod.market_from_cache()
            if market:
                for seat_name, usage in self._usage_events:
                    est = models_mod.estimate_cost(usage, seat_models.get(seat_name, ""),
                                                   market)
                    if est is not None:
                        costs[seat_name] = round(costs.get(seat_name, 0.0) + est, 5)
        except Exception:
            pass  # cost accounting must never break a council
        if classification is not None and classification.usage:
            costs["jev"] = round(classification.est_usd, 6)

        result = CouncilResult(
            run_id=run_id, question=question, domain=domain, mode=mode,
            seats=[s.name for s in seats], rounds=rounds, weights=weights,
            ranked=ranked, winner=winner, dissent=dissent,
            conformity_flags=conformity_flags, memo_path="",
            elapsed_s=round(time.time() - t0, 1),
            transport_used=transport_used, errors=errors,
            seat_models=seat_models, costs=costs,
            classification=classification,
        )
        result.memo_path = memo.write_memo(result, self.ledger)
        pair_id, arm = getattr(self, "_pair", ("", ""))
        self.ledger.register_run(run_id, domain, question,
                                 [s.name for s in seats], result.memo_path,
                                 pair_id=pair_id, arm=arm,
                                 lead=winner.seat if winner else "")
        self._track_lead_action(result)
        self._persist(result)
        return result

    def _track_lead_action(self, r: CouncilResult) -> None:
        """Open an execution loop for the lead recommendation.

        A memo nobody acts on is indistinguishable from no council at all
        (ledger run 20260819-123157: advice never executed, operator had no
        recollection of it seven days later). Capturing the action at run time
        is the only step that does not depend on the operator remembering.
        Never fatal - a tracking failure must not sink a finished council."""
        try:
            from . import followup
            winner = getattr(r, "winner", None)
            if not winner:
                return
            action = (getattr(winner, "recommendation", "") or
                      getattr(winner, "position", "") or "").strip()
            if not action:
                return
            f = followup.Followups()
            f.open(r.run_id, action, seat=getattr(winner, "seat", ""))
            f.close_conn()
        except Exception:
            pass

    def _persist(self, r: CouncilResult) -> None:
        path = config.runs_dir() / f"{r.run_id}.json"
        blob = {
            "run_id": r.run_id, "question": r.question, "domain": r.domain,
            "mode": r.mode, "seats": r.seats, "weights": r.weights,
            "ranked": r.ranked, "conformity_flags": r.conformity_flags,
            "elapsed_s": r.elapsed_s, "transport_used": r.transport_used,
            "errors": r.errors, "memo": r.memo_path,
            "models": r.seat_models, "costs": r.costs,
            "rounds": {
                str(k): [d.__dict__ for d in v] for k, v in r.rounds.items()
            },
        }
        path.write_text(config.to_json(blob))

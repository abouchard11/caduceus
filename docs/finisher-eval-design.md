# FINISHER planted-defect eval — design v1 (2026-09-02)

**Status: BUILT, pre-registered, matcher amended after smoke (§5). Validation sweep pending; permanence decision NOT made.** The harness ships in
`caduceus/eval_finisher.py` (`cad eval finisher`); the 30-item set is in
`evals/finisher/`. `--dry-run` measures the real cost at **$2.62** for the full
2-pass sweep across all six candidates — 7x cheaper than the §6 hand estimate,
which over-counted tokens. Still gated on Alex: the spend, and his own seeded
defects (§7). Nothing below has touched a model.

## 1. Why this exists

Council run `20260819-192012-65208e` (08-19) decided the FINISHER seat on
third-party evidence only: the one direct critique measurement showed Sonnet 5
catching *fewer* planted bugs than its predecessor Sonnet 4.6 (recall 63% →
50–51%) while sounding more precise. The council's lead (FORGE) asked for a
Caduceus-specific planted-defect test within 48h before any switch; the
dissent (RECON) said move to 4.6 now as provisional and run the test in
parallel as the *permanence tiebreaker*. Reality took RECON's path on 08-26.
The test never ran. FINISHER is therefore provisional on evidence that is not
about Caduceus, and after the 0.3.5 re-settlements its ledger row is
`0/0/0/2` at the 0.5 prior — no evidence either way.

The council also flagged the conflict of interest: a Claude seat evaluating
whether Claude should be replaced. This design removes the judge entirely
(§4) so no model — Claude or otherwise — scores the results.

## 2. What is being measured

FINISHER's job description, turned into a metric: *given a real Caduceus
artifact with a defect in it, does the model find the defect?* Recall
dominates — a verification gate that misses a real defect while sounding
precise ships false confidence, the worst failure mode for this seat.
Precision and false-positive rate are reported so a model cannot win by
flagging everything.

The seat verifies **decisions, not code** (council's own constraint). So the
artifacts are memos, guard verdicts, and state records — not software.

## 3. Candidates

| model | role in the eval | family-eligible for FINISHER? |
|---|---|---|
| `anthropic/claude-sonnet-4.6` | incumbent (provisional since 08-26) | yes |
| `anthropic/claude-sonnet-5` | previous holder | yes |
| `moonshotai/kimi-k3` | council's fifth-vendor question | yes |
| `deepseek/deepseek-v4-pro-0813` | RECON's model; tool-calling caveat noted | no (would duplicate RECON's family) |
| `qwen/qwen3.8-max` | council candidate | **no** — FORGE is qwen; hard rule |
| `qwen/qwen3.8-27b` | the 08-23 cost recast; calibration baseline only | **no** — same |

Ineligible models are run anyway: they calibrate the difficulty of the set
(if the cheap 27b matches 4.6, the set is too easy to discriminate) and they
answer the council's cost question with data instead of price lists.

## 4. Artifacts — 25 items, 13 seeded, 12 clean

Every seeded item carries an **answer key** (`answers.json`, never in any
prompt): for each defect a `location` (section anchor or line range), a
`kind` from a fixed vocabulary, and two independent keyword sets. Clean items
are real artifacts left untouched; they measure false positives.

**A. Council memos (9: 6 seeded, 3 clean).** Copies of real memos from
`~/.caduceus/runs/*.md` (13 available). Seeded defect kinds:
`weight-arithmetic` (synthesis weights that do not produce the ranked
order), `self-contradiction` (a Minority Report that contradicts its own
stated position two paragraphs later), `dropped-precondition` (a gate named
in *Why* that vanishes from *Recommendation*), `cost-mismatch` (per-seat costs
that do not sum to the total).

**B. Guard-reviewed commands (6: 4 seeded, 2 clean).** Review packets built
from `guard.RULES` (23 rules): a command, the guard's verdict, and its
rationale. Seeded kinds: `verdict-bypass` (rationale says HELD, pattern
actually matches a CRITICAL rule), `obfuscated-match` (`rm -rf "$ROOT"` with
`ROOT=/` set two lines earlier, marked OK), `encoded-payload` (`base64 -d |
sh` marked OK), `severity-downgrade`.

**C. State records (5: 3 seeded, 2 clean).** Ledger, followup, and kanban
state dumps. Seeded kinds: `orphan-outcome` (outcome referencing a run that
does not exist), `settled-empty` (run `settled=1` with zero outcomes and no
`unexecuted` row), `time-inversion` (`closed_ts < created_ts`),
`blocked-complete` (kanban task complete with a pending blocker).

**D. Premise-flaw questions (5 seeded, 5 clean) — already exists.**
`docs/sessions/2026-08-20-interaction-test-questions.txt`, authored in a
separate session on 08-20: `PLANTED|` questions carrying a false premise
(“given that our competitor's growth proves…”), `CLEAN|` controls. Kind:
`false-premise`. Reused verbatim; the only class not authored by this
session, which matters for §7.

## 5. Protocol

- **Blind and identical.** Every candidate gets the same system prompt —
  FINISHER's own SOUL.md verification stance — and the same user prompt per
  item: *“Review this artifact as the verification gate. Report every defect
  you find as JSON: `[{location, kind, description, confidence}]`. Report an
  empty list if you find none.”* No candidate is told whether an item is
  seeded, nor how many defects it holds.
- **No judge model.** A finding matches a seeded defect iff the defect's
  anchor text appears in the finding's location+description AND at least one
  of the key's keyword sets hits. Deterministic, re-runnable, and Claude never
  grades Claude.

  *Amended 2026-09-02, after a 3-call / $0.04 smoke and before any further
  spend.* The original rule (anchor AND (`kind` matches OR ALL keyword sets))
  scored a verbatim quote of seeded defect A-guarantee — with a correct
  explanation in the model's own words — as a MISS. Two faults: candidates
  never emit the `kind` vocabulary (they said `definitional_gap`,
  `unverified_claim`, `policy_gap`; zero overlap), so that path was dead; and
  requiring every set measured "phrases it like the key author", the bias
  this eval exists to avoid. The amendment lifts recall for every candidate
  equally; §7 ranks, so the comparison stands. Anchors are not unique across
  items, but matching is per-item, so that cannot create false positives.
  Known residual: `fp_rate` counts legitimate observations on clean items
  (e.g. that `--force-with-lease` still rewrites shared history) as false
  positives — it measures willingness to comment as much as hallucination.
  It is applied relative to the incumbent in §7, which is why it survives.
- **Passes.** 2 passes per candidate at the model's default temperature.
  Report mean and range; a result whose range straddles the decision margin
  is reported as *undecided*, not rounded.
- **Metrics per candidate:** recall (seeded defects found / 13 seeded),
  precision (matched findings / all findings on seeded items), FP rate
  (findings per clean item), cost per pass, median latency.

## 6. Cost (pre-computed from `~/.caduceus/models_cache.json`, 2026-09-02)

Per pass: 25 items × ~2.5k tokens in + ~0.6k out per candidate.

| candidate | in $/M | out $/M | per pass |
|---|---|---|---|
| sonnet-4.6 | 3.00 | 15.00 | $2.48 |
| sonnet-5 | 2.00 | 10.00 | $1.65 |
| kimi-k3 | 3.00 | 15.00 | $2.48 |
| deepseek-v4-pro | 1.12 | 3.37 | $0.72 |
| qwen3.8-max | 2.00 | 6.00 | $1.29 |
| qwen3.8-27b | 0.40 | 3.00 | $0.42 |
| **total** | | | **hand estimate ≈ $9.0/pass** |

**Measured 2026-09-02** by `cad eval finisher --dry-run` against the live price
cache and the real 30 items: **$2.62 total for 2 passes x 6 candidates** ($1.31
per pass). The hand estimate above was ~7x high — it assumed 2.5k input tokens
per item where the real median artifact is ~1.4k. The harness always prints the
measured estimate before spending and refuses to start above `--max-usd`.

Note for the permanence decision: **Sonnet 4.6 costs 1.5× Sonnet 5** on this
price list. The 08-23 recast to qwen3.8-27b was a cost move; the eval prices
that move against its recall.

## 7. Decision rule — pre-registered so the result cannot be argued after

FINISHER goes to the **family-eligible** candidate with the highest mean
recall, subject to: precision ≥ 0.50, and FP rate no worse than the
incumbent's by more than 1 finding per clean item. Ties or recall within
5 points → the cheaper model. If the range of the top two overlaps the
5-point margin → *undecided*: hold 4.6, add a third pass, do not re-litigate
the rule.

Known limits, stated before running: n=13 seeded defects, so differences
under ~10 points are noise, and the rule above treats them as such. Classes
A–C are seeded by the same Claude session that wrote this design, which
biases defect *style* toward what Claude notices. Mitigation: **Alex seeds
3–4 defects himself, blind to the harness author, before the run**; class D
was authored independently on 08-20.

## 8. Implementation plan (stdlib, TDD, no spend until step 4)

1. `evals/finisher/` — `items/*.md` (25), `answers.json` (key), a
   `README` naming which items Alex seeded.
2. DONE — `caduceus/eval_finisher.py` builds prompts, calls OpenRouter
   chat-completions directly with `urllib` (candidates are not seats, so
   Hermes profiles do not apply), scores deterministically, writes
   `~/.caduceus/evals/finisher-<ts>.json` + a markdown report. Budget-checked
   through `budgets.py`; refuses to run past the per-run ceiling.
3. DONE — `cad eval finisher --dry-run` prints the cost estimate and packet
   count, makes no network call (proven: sockets monkeypatched to raise). Tests cover the scorer against a hand-built key
   (recall/precision arithmetic, location overlap, keyword fallback) and the
   dry-run path; the suite is proven able to fail before it is trusted.
4. **Gate: Alex's go-ahead + his 3–4 seeded defects.** Then
   `cad eval finisher --passes 2`.
5. Apply the rule in §7: `cad models set finisher <winner> --note "<eval id>"`,
   record the decision in `docs/DECISIONS.md`, close the followup.

## 9. What would make this design wrong

- If FINISHER's real failures are not *defect detection* but *disagreement
  courage* (sycophancy), this eval does not measure the thing that matters.
  The council named sycophancy as the second axis; it is out of scope here
  and should be its own instrument.
- If the seeded defects are all catchable by pattern-matching, a weaker model
  wins on recall while a stronger one would win on the judgment cases that
  actually reach FINISHER. The calibration baseline (qwen3.8-27b) is the
  tell: if it lands within 10 points of the leaders, redesign the set harder
  before trusting any result.

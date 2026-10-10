# `cad compile` — the complement compiler

Status: design, approved 2026-10-10 (grilled, 16 decisions; see DECISIONS.md 2026-10-10).
Owner: Alex. Author of record: Alex (drafted in session). Supersedes nothing; extends
seatsetup. Caliber (2026-08-19) is the reserved product name; this is the internal verb.

## 1. What it is

Caduceus today is one function: a person's measured gaps → five seats. The seats carry
identity (SOUL.md) and an employment contract (USER.md) and almost no reach: two skills
in `skills/`, while ~1,000 SKILL.md files sit on this machine across four roots.

`cad compile` is the second function, and it makes the first mechanical:

    profile (gap vector)  ──►  cast (which archetypes are staffed, as seats)
    cast × domain         ──►  loadout (≤5 skills per seat per domain, from a manifest)
    cast                  ──►  USER.md (generated from the vector + the fixed contract)

Code owns control flow. A model appears in exactly two bounded places, both Jev
(TypeSafe System One, typed questions, calibrated probabilities, no text generation):
domain classification of a council question, and offline scoring of skills against
seat×domain pairs. Neither picks a winner. Synthesis stays plain Python (Decision 2).

## 2. Decisions carried in (grill of 2026-10-10)

| # | Decision | Choice |
|---|---|---|
| 1 | First user | Alex first, stranger-ready: profile is a data file, not prose |
| 2 | Artifact shape | Compile once; live per-question routing only after the kill criterion passes |
| 3 | Profile schema | Canonical gap vector: trait → percentile, facets, source, confidence; adapters feed it |
| 4 | Scenario unit | The ten Caduceus domains + `general` (the `other` Jev needs) |
| 5 | Loadout scope | Manifest scanned from four roots, name+description only; 5 skills per seat per domain |
| 6 | Guard | Unchanged. Loadout is reach; guard is refusal |
| 7 | Kill criterion | Beat the no-loadout council on 3 real settled paired runs within 14 days of first install; settle the 8 open runs first |
| 8 | Lives | `cad compile` in this repo + a SKILL.md wrapper beside `caduceus-council` |
| 9 | Taxonomy | PrinciplesYou's own names (12 traits, 36 facets, 5 scales); other instruments map in |
| 10 | Source of truth | `seats/PROFILE.json`; USER.md is generated, contract block fixed |
| 11 | Casting | Fixed archetype library; the vector selects 4–6; Alex's profile must select exactly the current five (golden test) |
| 12 | Models | Compiler never touches model casting |
| 13 | Classifier policy | Jev Choice over domains; keyword fallback with no key or on error; below 0.6 confidence blend believability over the top two domains |
| 14 | Loadout selection | Jev scores offline → `seats/LOADOUT-PROPOSAL.json`; Alex edits → `seats/LOADOUT.json`; compile installs the edited table |
| 15 | Denylist | `seats/DENYLIST.json` of skills never compiled into any seat (send, publish, pay, settings, secrets) |
| 16 | Measurement | Paired: same question, arm A without loadouts, arm B with; both settled against the same reality |

Deferred in the grill, decided here (Alex deferred the remainder):

| D1 | Souls | The five hand-written SOUL.md files stay verbatim. Archetypes not currently staffed carry a soul template that renders only when a profile selects them |
| D2 | File format | JSON. The engine is stdlib-only (pyproject: `dependencies = []`), so no YAML |
| D3 | Pairing | `council_runs` gains `pair_id`, `arm`, `lead`; settlement stays per run; the pair report derives from settled outcomes |

## 3. Data

### 3.1 `seats/PROFILE.json` (source of truth)

```json
{
  "schema": "caduceus.profile.v1",
  "person": {"name": "Alex Bouchard", "handle": "alex"},
  "instrument": {"name": "PrinciplesYou", "taken": "2026-08", "source": "PDF, verified"},
  "archetypes": {"best": "Shaper", "secondary": ["Coach", "Growth Seeker"],
                 "least_like": ["Implementer", "Individualist"]},
  "traits": {
    "Organized":       {"pct": 26, "confidence": 1.0},
    "Detail-Oriented": {"pct": 34, "confidence": 1.0},
    "Composed":        {"pct": 99, "confidence": 1.0,
                        "facets": {"Calm": 98, "Confident": 99, "Poised": 96}}
  },
  "notes": {"Modest": "16 — a feature, not a gap. Do not inflate him."}
}
```

Rules: `pct` is 0–100. `confidence` is 0–1; measured instrument = 1.0, behavioural
inference (gsd-profile-user adapter, later) ≤ 0.6. Trait and facet names are validated
against `caduceus/data/principlesyou.json` (warn on unknown, never fail: the library
only needs the names it triggers on). Facet keys may appear at top level too
(`"Direct": {"pct": 94}`) because the report prints them that way and the souls cite
them that way.

### 3.2 Archetype library — `caduceus/archetypes.py`

Each entry: `key`, `seat` (the Hermes profile name it instantiates), `display`, `belbin`
(nearest Belbin role, for the record), `trigger` (predicate on the vector), `margin`
(how far past the threshold the profile is; used to rank), `domains` (believability
priors, from SEATS where the seat exists), `soul_template` (only used when no
hand-written `seats/<seat>/SOUL.md` exists), default `model/provider/family` for seats
that do not exist in SEATS (Decision 12: never applied to an existing seat).

| key | seat | trigger on the vector | Alex fires? |
|---|---|---|---|
| implementer | forge | `Implementer` in least_like OR Practical ≤ 50 | yes (least-like; 47) |
| completer_finisher | finisher | Organized ≤ 40 OR Detail-Oriented ≤ 40 | yes (26, 34) |
| source_grinder | recon | Curious ≥ 80 AND Detail-Oriented ≤ 50 | yes (95, 34) |
| stress_tester | sparring | Creative ≥ 80 OR Original ≥ 80 | yes (94, 95) |
| diplomat | envoy | Direct ≥ 80 AND Empathetic ≤ 50 | yes (94, 41) |
| plant | plant | Creative ≤ 40 OR Original ≤ 40 | no |
| coordinator | coordinator | Systematic ≤ 40 OR Leadership ≤ 40 | no (66, 88) |
| anchor | anchor | Composed ≤ 40 | no (99) |
| driver | driver | Determined ≤ 40 OR `Shaper` in least_like | no (98) |

`driver` enforces momentum and deadlines; it never sets direction (operating contract
rule 1 holds for every compiled cast, not only Alex's).

Confidence gate: a trait with `confidence < 0.7` must clear its threshold by 10 extra
points to fire. Inferred gaps cast weaker than measured ones.

### 3.3 Casting rule — `caduceus/compile.py: cast(profile)`

1. Evaluate every trigger; fired archetypes are selected.
2. If fewer than 4 fired, add unfired archetypes in order of smallest shortfall until 4.
3. If more than 6 fired, keep the 6 with the largest margin.
4. Run `heterogeneity_warnings` on the resulting seats; warnings print, never block.
5. Output `seats/CAST.json`: `{schema, profile_sha256, seats: [{key, seat, fired, margin,
   reason}], warnings, generated}`.

Golden test (pinned in `tests/test_compile.py`): Alex's `PROFILE.json` → exactly
`forge, finisher, recon, sparring, envoy`, all `fired: true`, no fill-ins.

### 3.4 USER.md generation

Template `seats/USER.md.tmpl`: header, "Who the operator is" (from `person`), archetype
line, strengths (traits ≥ 85, sorted desc, facets inline), gaps (every trait that fired an
archetype, with the archetype's one-line job), notes, then the six-rule operating
contract **verbatim** as a fixed block. `cad compile --write` writes `seats/USER.md` only
when the rendered text differs; `seatsetup.install_user` already copies it into every
profile on `cad init`.

### 3.5 Manifest — `~/.caduceus/skill-manifest.json`

Scanner roots (override/extend with `--root`):
`~/.claude/skills/*/SKILL.md` · `~/.claude/plugins/cache/**/SKILL.md` ·
`~/.hermes/skills/**/SKILL.md` · `<repo>/skills/*/SKILL.md`.
Entry: `name`, `description` (frontmatter; first 300 chars), `root`, `path`, `category`
(first dir under root), `user_invoked` (`disable-model-invocation: true`), `sha256` of
SKILL.md. Duplicate names across roots keep the first by root order and record the
shadowed paths. Counts today: 194 global, 561 plugin, 246 Hermes, 2 repo.

### 3.6 Denylist — `seats/DENYLIST.json`

`{"names": [...], "patterns": [...]}`. Shipped patterns: `send*`, `*email*`, `gmail*`,
`publish*`, `post*`, `pay*`, `payroll*`, `invoice*`, `buy*`, `purchase*`, `deploy*`,
`ship`, `land-and-deploy`, `update-config`, `*settings*`, `*secret*`, `*password*`.
Mirrors the WORKFLOW authorization list (external sends, publication, deployment,
charges, secrets). A denied skill never enters a proposal or an install. The guard sees
commands; this sees reach.

### 3.7 Loadout table — `seats/LOADOUT.json`

```json
{"schema": "caduceus.loadout.v1", "cast_sha256": "…", "per": 5,
 "seats": {"finisher": {"review": ["code-review", "…"], "testing": ["…"]}}}
```

`LOADOUT-PROPOSAL.json` has the same shape plus `score`, `confidence` per skill. Alex
edits the proposal into the table (or writes the table by hand; that path always works).

## 4. Jev — `caduceus/jev.py`

stdlib `urllib` client. `POST https://api.typesafe.ai/v1/systemone`, body
`{state, model: "jev-latest", questions}`, `Authorization: Bearer <TYPESAFE_API_KEY>`
read from `~/.caduceus/env` via `config.load_env()` (never logged). Timeout 10 s.
First-party endpoint only (OpenRouter routing measured at 33% availability; first-party
5,500/5,500 on 2026-09-24). Any non-200, timeout, or malformed body raises `JevError`.
Usage tokens are summed and reported; price assumed $0.042 per million input tokens.

### 4.1 Slot 1 — domain classification (`caduceus/classify.py`)

`domain_distribution(text) -> Classification(top, probabilities, confidence, source)`.
One Choice question over the ten `DOMAIN_KEYWORDS` keys plus `general` as the
catch-all. On no key, error, or timeout: `source="keyword"`, `probabilities={top: 1.0}`,
`confidence=1.0`, using the existing `classify_domain`. `config.classify_domain` keeps
its signature (returns `top`) so nothing else moves.

Blend (Decision 13): in `Council._finish`, when `confidence < 0.6`, a seat's weight uses
`Σ p_d · believability(seat, d)` over the top two domains, `p` renormalised. Otherwise
unchanged. The run registers under `top`; the memo prints source and confidence.

### 4.2 Slot 2 — loadout proposal (`caduceus/loadout.py: propose`)

State = one skill `{name, description, category}`. Questions = one Score per (seat in
cast × domain), 5 levels: irrelevant / rarely useful / sometimes useful / often useful /
essential. `score` is the expected level (0–4). Per (seat, domain): drop denied skills,
take the top `per` by score, tie-break on confidence. Answers cache to
`~/.caduceus/loadout-cache.json` keyed by sha256(skill sha256 + cast sha256) so a rerun
never re-spends (the FINISHER-eval lesson of 2026-10-01). `--max-usd` caps the run;
dry-run prints request count and estimated cost without a call. With no key: exit 2 with
the message that a hand-written table is the alternative.

## 5. Install / uninstall — `caduceus/loadout.py`

Static install (Decision 2): per seat, the union of its per-domain lists, capped at 15,
taking the seat's prior domains first (`SEATS[seat].domains` order, then the remaining
domains by best score). Destination: `~/.hermes/profiles/<seat>/skills/loadout/<skill>/`
(one category level, the same shape `install_skill` uses for the council skill).
`skills/loadout/.caduceus-loadout.json` records what compile put there and each source
sha256; `uninstall` removes only those directories and never touches
`productivity/caduceus-council` or anything hand-installed. Install is idempotent;
changed sources are re-copied; a seat whose profile does not exist is skipped with a
log line, not an error.

## 6. Paired evaluation — `cad eval loadout`

`cad eval loadout "QUESTION" [--context-file F] [--seats …] [--dry-run]`:
1. `pair_id = <ts>-<hex6>`; record current install state.
2. Arm A: uninstall; run a full council; register with `pair_id, arm="A"`, `lead`.
3. Arm B: install from `LOADOUT.json`; run the same question, same seats, same context;
   register with `arm="B"`.
4. Restore the prior install state. Print both run ids and both memo paths.
Dry-run runs tag `arm="A-dry"/"B-dry"` and are excluded from the report.

`cad eval loadout report`: for every pair whose two runs are both settled: arm B wins
the pair iff its `lead` seat has a `win` outcome for that run and arm A's lead does not;
arm A symmetric; otherwise tie. Prints pairs, B-wins, A-wins, ties, days since first
install (from `~/.caduceus/compile-state.json`).

Pre-registered rule (Decision 7), evaluated at day 14 after first install, real pairs
only: **PASS** if B-wins ≥ 3 and B-wins > A-wins. Otherwise **PARK**, and the loadout
trees come out. The report prints the verdict once day 14 has passed; it never settles
anything itself.

## 7. CLI

| Command | Does |
|---|---|
| `cad compile` | validate PROFILE.json, print cast + USER.md diff; writes nothing |
| `cad compile --write` | write `seats/CAST.json` and `seats/USER.md` (only on change) |
| `cad compile manifest [--root R …]` | scan, write manifest, print counts per root and denied count |
| `cad compile propose [--per 5] [--max-usd 1.00] [--dry-run]` | Jev scoring → `LOADOUT-PROPOSAL.json` |
| `cad compile install [--table seats/LOADOUT.json] [--cap 15]` | copy skill trees into seat profiles |
| `cad compile uninstall` | remove exactly what install recorded |
| `cad compile status` | cast sha, table sha, per-seat installed counts, criterion clock |
| `cad eval loadout …` / `cad eval loadout report` | §6 |

Doctor rows: `profile ↔ USER.md` (rendered text equals on-disk text), `loadout` (seats
installed / table sha matches / clock). Brief: one line with the criterion clock while it
runs.

## 8. Tests (stdlib pytest, isolated homes per conftest)

- profile: load/validate, unknown trait warns, bad pct fails, facet at top level accepted.
- archetypes/cast: golden test (Alex → the five); synthetic profiles fire plant,
  coordinator, anchor, driver; fill-to-4 and cap-at-6; confidence gate.
- user_md: render deterministic; contract block byte-identical to today's USER.md §
  "Operating contract"; `--write` no-op when unchanged.
- manifest: tmp roots with SKILL.md fixtures; shadowing; user_invoked flag; denylist
  patterns; the shipped denylist denies every name in a fixed list of risky fixtures.
- jev: fake transport; request body shape matches the documented Choice/Score bodies
  verbatim; non-200/timeout/malformed → JevError; usage summed.
- classify: keyword fallback with no key; Choice probabilities map; confidence; the
  council blend math on a two-domain distribution with a seeded ledger.
- loadout: proposal top-N with denylist and ties; cache hit means zero transport calls;
  install writes the record file; uninstall removes only recorded dirs; cap-15 precedence.
- eval: paired run on MockTransport registers two runs with pair_id/arm/lead; report
  derives wins from settled outcomes; rule PASS/PARK at day 14.
- ledger: migration adds the three columns to an existing v0.3 database without loss.

## 9. Out of scope (v1)

Live per-question routing (after the criterion). Life-situation scenarios. Model casting.
Regenerating the five existing souls. Behavioural-inference adapter (gsd-profile-user →
vector): schema admits it; code for it is a separate change. Hermes `skills` toolset
internals: install copies files exactly as `install_skill` does today and assumes the
same discovery.

## 10. Risks named

- Jev steerability on hostile content is untested (jev-usage-outline v2, E2). Alex's own
  questions are not hostile; a stranger's might be. Run E2 before any compiled council
  serves someone else.
- 15 auto-firing skill descriptions per seat is a cold-start cost. The cap is a knob;
  measure with the memo's elapsed time and token usage before and after.
- A loadout can only be as good as the manifest descriptions; Hermes-side skills with
  empty descriptions score as noise. The manifest flags empty descriptions.

# Execution ledger — cad compile (feat/compile, 2026-10-10)

Copied verbatim from the plan workspace at finish. Rulings are the calls the executor made on Alex's behalf; `minor (deferred)` lines are reviewer findings left for a later pass.

# SDD ledger — plan: docs/superpowers/plans/2026-10-10-compile.md
Spec: docs/compile-design.md (read). Executor: inline (executing-plans). No harness todo tool in this session; this ledger is the record.
Pre-flight (shared interfaces):
- T1→T2: Profile.pct/confidence/least_like consumed by triggers — match.
- T2→T3/T8/T9/T10: Cast.seats[].seat, Cast.sha256 — match.
- T4→T10: register_run(pair_id, arm, lead), pairs(), lead_outcome() — match.
- T5→T6/T8: Client.ask/.usage, estimate_usd — match (Task 8 stub client carries .usage like the real one).
- T6→T10: domain_distribution(text, client=None, allow_jev=True) — Interfaces block omits allow_jev; Step 3 text has it. Ruling: allow_jev is part of the signature (tests use it) — cost if wrong: none.
- T7→T8/T9: Entry field order (name, description, root, path, category, user_invoked, sha256, empty_description) must match the keyword construction in Task 8 tests — enforce in T7.
- T9→T10/T11: install/uninstall/status/first_install_ts/mark_first_install(ts, force) — match.
Guard note: the hq pre-tool guard blocks shell text containing the graph-clear token; DENYLIST.json and tests naming it are written with the Write tool, never a heredoc.
Task 1: complete (commits 1b60972..f2077e6, tests: python3 -m pytest tests/test_profile.py -q → 8 passed in 0.05s)
Task 2: Ruling: heterogeneity_warnings already lives in config.py (plan said cli.py) — imported from config, nothing moved — cost if wrong: none
Task 2: Ruling: golden test asserts a qwen family warning instead of no warnings — forge and envoy share qwen today; spec §3.3 says warnings print, never block — cost if wrong: a stale assertion if envoy is recast
Task 2: complete (commits f2077e6..87ede16, tests: python3 -m pytest tests/test_compile.py -q → 8 passed in 0.03s)
Task 3: Ruling: hand-written gap prose moved into archetype job lines and profile notes (plan rendered only the one-line job) — the seats keep reading the same instructions; nothing the 08-19 USER.md said is lost — cost if wrong: prose drift in USER.md, no behavior
Task 3: Ruling: optional per-trait 'note' renders after a strength (he does not rattle / he can take it) — keeps the 08-19 annotations — cost if wrong: none
Task 3: complete (commits 87ede16..ba8921f, tests: python3 -m pytest tests/test_compile.py -q → 12 passed in 0.03s)
Task 4: complete (commits ba8921f..6112722, tests: python3 -m pytest tests/test_ledger.py -q → 19 passed in 0.13s)
Task 5: complete (commits 6112722..6c9d22b, tests: python3 -m pytest tests/test_jev.py -q → 6 passed in 0.02s)
Task 6: Ruling: pair_id/arm plumbed through Council.run and register_run here instead of Task 10 — same edit region, one commit — cost if wrong: none
Task 6: Ruling: an explicit --domain yields a 'given' classification and never calls Jev — tests and cli pass domain deliberately — cost if wrong: none
Task 6: complete (commits 6c9d22b..47d7ec6, tests: python3 -m pytest tests/test_classify.py tests/test_council.py -q → 21 passed in 0.10s)
Task 7: Ruling: plugin-cache entries take the plugin directory as category (the marketplace name said nothing); category is state Jev sees — cost if wrong: weaker proposals for plugin skills
Task 7: process note: the first commit landed before the red shipped-denylist test was read; fixed (*send* pattern) and amended in place, suite green before task-done
Task 7: complete (commits 47d7ec6..ca3aa88, tests: python3 -m pytest tests/test_manifest.py -q → 10 passed in 0.03s)
Task 8: Ruling: loadout cache key = name | skill sha | cast sha (plan: skill sha | cast sha) — two byte-identical SKILL.md files must not share scores — cost if wrong: none
Task 8: process note: pipe hid pytest's exit status, commit landed red; fixed and amended; pipefail on from here
Task 8: complete (commits ca3aa88..0d0b84b, tests: python3 -m pytest tests/test_loadout.py -q -k 'questions_cover or score_and_propose or cache_hit or cache_misses or max_usd or dry_run or bad_answer' → 7 passed, 8 deselected in 0.04s)
Security review (automated, 2026-10-10): HIGH egress — ruled: Jev classification stays on by default when a key is present (Decision 20, Alex's); mock/dry runs now never construct a client; HANDOFF must say that adding TYPESAFE_API_KEY sends council QUESTION text (never the context file) to TypeSafe — cost if wrong: a question's text leaves the machine
Security review: MEDIUM probabilities/confidence finite and within [0,1] or keyword fallback; MEDIUM response body capped at 1 MB; MEDIUM Jev cost recorded in result.costs['jev'] — budgets.py session-ledger integration deferred (Jev is not a Hermes session; a classification is ~4e-6 USD; proposals carry --max-usd)
Task 9: Ruling: after the seat's prior domains, remaining domains follow table order (the table carries names only; the plan said 'by best score') — proposals are written in DOMAINS order so this is deterministic — cost if wrong: a slightly different tail of a capped list
Task 9: install also removes directories it recorded earlier that are no longer in the plan, never anything unrecorded; a seat with an empty plan gets no record
Task 9: complete (commits eca45b7..a0ca54b, tests: python3 -m pytest tests/test_loadout.py -q → 15 passed in 0.07s)
Task 10: Ruling: denied skills are filtered BEFORE Jev scoring (plan scored everything then dropped) — no spend on skills that can never install — cost if wrong: none
Task 10: Ruling: compile subcommands dispatch on args.ccmd from one default fn rather than per-subparser set_defaults (argparse default-override behaviour differs across 3.9–3.12) — cost if wrong: none
Task 10: Ruling: `cad eval loadout report` is the literal word report in the question slot — a question that is exactly 'report' is not supported — cost if wrong: trivial
Task 10: complete (commits a0ca54b..b31f290, tests: python3 -m pytest tests/test_evalpair.py tests/test_cli_compile.py -q → 16 passed in 0.19s)
Security review 2 (automated, 2026-10-10): HIGH/MEDIUM path traversal via frontmatter names — fixed: safe_name() at scan (fallback to the directory name) and again at install/uninstall, containment check before every copytree/rmtree; MEDIUM symlink dereference — copytree(symlinks=True) with .git/.env/*.pem/*.key ignored — tests in test_manifest/test_loadout
Task 11: complete (commits 0316686..dad9000, tests: python3 -m pytest tests/test_doctor.py tests/test_brief.py -q → 35 passed in 1.55s)
Final review (fresh Fable reviewer): 0 Critical, 8 Important, 9 Minor. Re-graded: all 8 Important stand; Minor 'non-numeric confidence tracebacks' promoted to Important (crash on bad input).
Final: fixed cad init never pushed a regenerated USER.md — test_install_user_md_overwrites_changed_content + test_profile_row_warns_when_a_seat_copy_is_stale RED→GREEN
Final: fixed dry-run pair started the clock / touched installs — test_dry_run_touches_no_installs_and_no_clock + test_dry_run_with_real_table_never_installs RED→GREEN (dry runs skip the install dance entirely)
Final: fixed pair with installed loadouts and no manifest stripped them — test_refuses_when_installed_and_cannot_restore RED→GREEN (PairError, cli exit 2)
Final: fixed symlinked skill dirs skipped / plugin category was the version dir / node_modules and dot-dirs descended — test_symlinked_skill_dir_is_scanned, test_symlink_cycle_terminates, test_plugin_layout_category_and_pruning RED→GREEN
Final: fixed no 14-day window on counted pairs — test_report_counts_only_pairs_inside_the_window RED→GREEN (late_pairs reported, never counted); two existing report tests re-seeded inside the window
Final: fixed cache saved only at the end — test_cache_saves_periodically_during_scoring RED→GREEN + try/finally in propose
Final: fixed non-numeric confidence traceback — test_non_numeric_confidence_is_profile_error RED→GREEN
Final: documented (Important 8) unstaffed archetypes carried as data, not rendered, in CHANGELOG + spec §3.2; propose egress sentence in HANDOFF + SKILL.md
Final: minor (deferred): cad compile prints no USER.md diff (spec §7 says diff)
Final: minor (deferred): manifest conflates unusable names with shadowed duplicates in the count
Final: minor (deferred): duplicate plugin versions resolve by lexical path order (1.1.9 beats 1.1.10)
Final: minor (deferred): float pct truncates (40.5 → 40)
Final: minor (deferred): Ledger() opened without close in cli status/report, brief clock, doctor loadout row
Final: minor (deferred): cad ledger runs does not show arm/pair_id
Final: minor (deferred): CAST.json heterogeneity warning uses static SEATS, not models.effective_seat
Final: Ruling: reviewer's declined-to-judge lines all stand as set aside (discovery, E2, denylist breadth, budgets integration, prose drift, literal 'report', operator settlement, out-of-scope items, pre-existing changelog debt, in-code template vs .tmpl) — cost if wrong: none beyond what each line already states
Final: suite 379 passed in 4.56s

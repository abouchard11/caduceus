"""cad - the Caduceus CLI. Every subcommand does something real or exits loudly."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from . import brief, config, dashboard, doctor, eval_finisher, guard, models, seatsetup, telegram, budgets
from . import compile as compile_mod, evalpair, jev, loadout, manifest as manifest_mod, profile as profile_mod
from .config import SEATS, seat_list, heterogeneity_warnings
from .council import Council, extract_json
from .hermes import MockTransport, OneshotTransport
from .ledger import Ledger


# ---------------------------------------------------------------- helpers

def _print(s=""):
    sys.stdout.write(str(s) + "\n")


def _read_context(args) -> str:
    ctx = ""
    if getattr(args, "context_file", None):
        p = Path(args.context_file)
        if not p.exists():
            raise SystemExit(f"context file not found: {p}")
        ctx = p.read_text()[:24000]
    if getattr(args, "context", None):
        ctx = (ctx + "\n\n" + args.context) if ctx else args.context
    return ctx


# ---------------------------------------------------------------- commands

def cmd_init(args):
    log = seatsetup.init(
        seat_names=[s.strip() for s in args.seats.split(",")] if args.seats else None,
        force_soul=args.force_soul,
        cron=args.cron,
        guard_write=args.guard_write,
        enable_api=not args.no_api,
    )
    _print("\n".join(log))
    if seatsetup.stopped(log):
        raise SystemExit(1)


def cmd_doctor(args):
    rows = doctor.checks()
    _print(doctor.render(rows))
    raise SystemExit(doctor.exit_code(rows))


def cmd_brief(args):
    facts = brief.gather()
    heading = brief.WEEKLY_HEADING if args.weekly else brief.MORNING_HEADING
    section = brief.render_weekly(facts) if args.weekly else brief.render_morning(facts)
    # stdout is what hermes actually delivers when the cron runs this with
    # --no-agent; always print, --write is an additional side effect, not
    # a substitute for the stdout delivery.
    _print(section)
    if args.write:
        path = brief.write(section, heading)
        _print(f"[+] written to {path}")


def cmd_council_ask(args):
    seats = seat_list(args.seats) if args.seats else (
        [SEATS[n] for n in config.QUICK_PAIR] if args.quick
        else [SEATS[n] for n in config.FULL_COUNCIL])
    seats = [models.effective_seat(s.name) for s in seats]  # casting overrides
    for w in heterogeneity_warnings(seats):
        _print(f"[warn] {w}")
    mock = MockTransport() if args.dry_run else None
    council = Council(transport="mock" if args.dry_run else args.transport, mock=mock)
    
    # Generate run_id upfront so we can create budget BEFORE dispatch (F2 fix)
    import time, uuid
    run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    
    # Create budget BEFORE council.run() with session IDs that ApiTransport will use
    # Note: OneshotTransport doesn't write to state.db, so spend tracking won't work for it
    if not args.dry_run:
        ceiling = budgets.CEILINGS["quick_council"]["hard"] if args.quick else budgets.CEILINGS["full_council"]["hard"]
        # ApiTransport generates session IDs as: caduceus-{seat.name}-{run_id}
        session_ids = [f"caduceus-{s.name}-{run_id}" for s in seats]
        budgets.create_budget(
            run_id=run_id,
            origin="council",
            seats=[s.name for s in seats],
            ceiling_usd=ceiling,
            session_ids=session_ids
        )
    
    result = council.run(
        question=args.question,
        seats=seats,
        context=_read_context(args),
        quick=args.quick,
        escalate=not args.no_escalate,
        run_id=run_id,  # Pass the pre-generated run_id
    )
    _print(f"run:      {result.run_id}   mode: {result.mode}   "
           f"domain: {result.domain}   {result.elapsed_s}s")
    _print(f"seats:    {', '.join(result.seats)}  "
           f"(transport: {', '.join(sorted(set(result.transport_used.values())))})")
    if result.winner:
        _print(f"lead:     {result.winner.seat.upper()} "
               f"(weight {result.weights.get(result.winner.seat, 0):.3f})")
        _print(f"rec:      {result.winner.recommendation or result.winner.position}")
    if result.dissent:
        _print(f"dissent:  {result.dissent.seat.upper()} - "
               f"{(result.dissent.recommendation or result.dissent.position)[:160]}")
    if result.conformity_flags:
        for f in result.conformity_flags:
            _print(f"conform:  {f}")
    if result.errors:
        for e in result.errors:
            _print(f"error:    {e}")
    _print(f"memo:     {result.memo_path}")
    _print(f"settle:   cad ledger settle {result.run_id} --winner <seat>")
    if getattr(args, "live", False):
        for line in telegram.broadcast_result(result):
            _print(f"telegram: {line}")


def cmd_council_review_command(args):
    """Two-person rule, second person = FINISHER (different model family)."""
    cmd = " ".join(args.command).strip()
    if not cmd:
        raise SystemExit("no command given")
    rule = guard.evaluate(cmd)
    if rule and rule.severity == "CRITICAL":
        _print(f"REJECTED locally: {rule.name} - {rule.why}. CRITICAL commands "
               "have no override path.")
        raise SystemExit(2)
    seat = models.effective_seat("finisher")
    prompt = (
        "[CADUCEUS TWO-PERSON RULE - COMMAND REVIEW]\n"
        "Another seat wants to run a shell command that the guard classified as "
        f"risky ({rule.name + ': ' + rule.why if rule else 'unclassified'}).\n"
        f"COMMAND:\n{cmd}\n\n"
        "Evaluate: (1) is it necessary, (2) is there a safer equivalent, "
        "(3) blast radius if wrong. Default to reject when uncertain.\n"
        'Reply ONLY JSON: {"verdict":"approve|reject","reason":"...",'
        '"safer_alternative":"... or empty"}'
    )
    if args.dry_run:
        _print("[dry-run] would ask FINISHER to review; no token granted")
        return
    reply = OneshotTransport().ask(seat, prompt)
    if not reply.ok:
        _print(f"FINISHER unreachable ({reply.error}) - defaulting to REJECT. "
               "A human can still grant: cad approve grant --grantor alex -- " + cmd)
        raise SystemExit(2)
    obj = extract_json(reply.text) or {}
    verdict = str(obj.get("verdict", "reject")).lower()
    reason = obj.get("reason", reply.text[:200])
    if verdict == "approve":
        tok = guard.grant(cmd, grantor="finisher")
        _print(f"APPROVED by FINISHER: {reason}")
        _print(f"token {tok['hash']} valid {guard.TOKEN_TTL_SECONDS // 60}m, single use")
    else:
        alt = obj.get("safer_alternative", "")
        _print(f"REJECTED by FINISHER: {reason}")
        if alt:
            _print(f"safer alternative: {alt}")
        raise SystemExit(2)


def cmd_ledger_show(args):
    led = Ledger()
    rows = led.table()
    if not rows:
        _print("ledger empty - councils run, reality settles, believability moves")
        return
    _print(f"{'seat':<10}{'domain':<16}{'w/m/l/u':<12}{'score':<8}basis")
    for r in rows:
        wmlu = f"{r['win']}/{r['mixed']}/{r['loss']}/{r['unexecuted']}"
        _print(f"{r['seat']:<10}{r['domain']:<16}{wmlu:<12}"
               f"{r['believability']:<8}{r['basis']}")
    led.close()


def cmd_ledger_runs(args):
    led = Ledger()
    runs = led.runs(unsettled_only=not args.all)
    for r in runs:
        flag = " " if r["settled"] else "*"
        tag = (f"  pair {r['pair_id']} arm {r['arm']}  lead {r['lead'] or '-'}"
               if r.get("pair_id") else "")
        _print(f"{flag} {r['run_id']}  [{r['domain']}]  {r['question'][:80]}{tag}")
    if not runs:
        _print("no runs" + ("" if args.all else " awaiting settlement"))
    led.close()



def _known_seats(led, run_id=None):
    """Seat names a settlement may name: the five SEATS, the archetype library's
    seats, and whatever seats the run itself registered."""
    known = set(SEATS)
    try:
        from . import archetypes
        known |= {a.seat for a in archetypes.LIBRARY}
    except Exception:
        pass
    if run_id:
        row = led.conn.execute("SELECT seats FROM council_runs WHERE run_id=?", (run_id,)).fetchone()
        if row and row[0]:
            known |= {s.strip().lower() for s in row[0].split(",") if s.strip()}
    return known


def _seat_names(values, led, run_id=None, flag="seat"):
    """`--winner finisher,forge --winner recon` -> ['finisher', 'forge', 'recon'],
    every name validated. 2026-10-10: comma lists were stored verbatim as a seat
    called "finisher,forge"; a 2026-09-29 row stored a --note typed into the
    seat slot. Both are refused here before anything is written."""
    names = []
    for v in values or []:
        for part in str(v).split(","):
            s = part.strip().lower()
            if s and s not in names:
                names.append(s)
    known = _known_seats(led, run_id)
    bad = [n for n in names if n not in known]
    if bad:
        raise SystemExit(f"unknown seat(s) for {flag}: {', '.join(repr(b) for b in bad)}. "
                         f"Known: {', '.join(sorted(known))}")
    return names


def cmd_ledger_record(args):
    led = Ledger()
    seat = _seat_names([args.seat], led, args.ref or None, "seat")[0]
    oid = led.record(seat, args.domain, args.result,
                     task_ref=args.ref or "", note=args.note or "")
    _print(f"recorded {oid}: {args.seat}/{args.domain} -> {args.result}")
    led.close()


def cmd_ledger_settle(args):
    led = Ledger()
    # attribute outcomes to the models that actually sat in the seats
    seat_models = {}
    run_file = config.runs_dir() / f"{args.run_id}.json"
    if run_file.exists():
        try:
            seat_models = json.loads(run_file.read_text()).get("models", {}) or {}
        except Exception:
            pass
    out = led.settle(args.run_id,
                     winners=_seat_names(args.winner, led, args.run_id, "--winner"),
                     losers=_seat_names(args.loser, led, args.run_id, "--loser"),
                     mixed=_seat_names(args.mixed, led, args.run_id, "--mixed"),
                     unexecuted=_seat_names(args.unexecuted, led, args.run_id, "--unexecuted"),
                     note=args.note or "",
                     models=seat_models)
    for seat, oid in out.items():
        _print(f"settled {seat}: {oid}")
    if not out:
        _print("run marked settled with no outcomes (use --winner/--loser/--mixed/--unexecuted)")
    led.close()


def cmd_ledger_resettle(args):
    led = Ledger()
    # attribute outcomes to the models that actually sat in the seats
    seat_models = {}
    run_file = config.runs_dir() / f"{args.run_id}.json"
    if run_file.exists():
        try:
            seat_models = json.loads(run_file.read_text()).get("models", {}) or {}
        except Exception:
            pass
    voided = led.conn.execute(
        "SELECT COUNT(*) FROM outcomes WHERE task_ref=? AND voided=0", (args.run_id,)
    ).fetchone()[0]
    out = led.resettle(args.run_id,
                       winners=_seat_names(args.winner, led, args.run_id, "--winner"),
                       losers=_seat_names(args.loser, led, args.run_id, "--loser"),
                       mixed=_seat_names(args.mixed, led, args.run_id, "--mixed"),
                       unexecuted=_seat_names(args.unexecuted, led, args.run_id, "--unexecuted"),
                       note=args.note or "",
                       models=seat_models)
    _print(f"resettled {args.run_id}: {voided} prior outcome(s) voided")
    for seat, oid in out.items():
        _print(f"settled {seat}: {oid}")
    if not out:
        _print("run marked settled with no outcomes (use --winner/--loser/--mixed/--unexecuted)")
    led.close()


def cmd_followup_list(args):
    from . import followup
    st = followup.status()
    acts, runs = st["unexecuted"], st["unsettled"]
    if not acts and not runs:
        _print("no open loops - every recommendation acted on, every decision graded")
        return
    if acts:
        _print(f"NOT DONE YET ({len(acts)}):")
        for c in acts:
            _print(f"  [{c.id}]  {int(c.age_days):>3}d  {c.seat or '-':<9} {c.action[:80]}")
        _print("  cad followup done <id> | cad followup drop <id>")
    if runs:
        if acts: _print("")
        _print(f"UNGRADED DECISIONS ({len(runs)}):")
        for r in runs:
            _print(f"  {r['run_id']}  {r['question'][:70]}")
        _print("  cad ledger settle <run_id> --winner <seat> --loser <seat>")


def cmd_followup_open(args):
    from . import followup
    f = followup.Followups()
    cid = f.open(args.run_id, args.action, seat=args.seat or "")
    f.close_conn()
    _print(f"tracking [{cid}]: {args.action[:70]}")


def _followup_close(args, state):
    from . import followup
    f = followup.Followups()
    ok = f.close(args.id, state, note=args.note or "")
    f.close_conn()
    _print(f"[{args.id}] -> {state}" if ok else
           f"[{args.id}] not found or already closed")
    if not ok:
        raise SystemExit(1)


def cmd_followup_done(args):
    _followup_close(args, "done")


def cmd_followup_drop(args):
    _followup_close(args, "dropped")


def cmd_exec_queue(args):
    from . import followup
    f = followup.Followups()
    q = [c for c in f.pending()
         if c.owner == "agent" and not followup._is_diagnostic(c.run_id)]
    f.close_conn()
    if not q:
        _print("staff queue empty")
        return
    for c in q:
        _print(f"  [{c.id}]  {int(c.age_days):>3}d  {c.action[:90]}")


def cmd_exec_run(args):
    """Exit 0 for an empty queue, a dry run, or any live run where an item was
    handled, ran, or failed for its own reasons. Exit 1 when the transport could
    not run (executor.transport_failure): per-item lines still print, then one
    FAILED line on stderr names the cause."""
    from . import executor
    results = executor.run_queue(live=args.live, max_actions=args.max)
    if not results:
        _print("staff queue empty")
        return
    for r in results:
        _print(f"  [{r.cid}] {r.status}: {r.detail[:120]}")
    if not args.live:
        _print("dry-run - pass --live to execute")
    failure = executor.transport_failure(results)
    if failure:
        sys.stdout.flush()  # keep the item lines ahead of the summary in a shared log
        sys.stderr.write(f"FAILED: {failure}\n")
        raise SystemExit(1)


def cmd_followup_agenda(args):
    from . import followup
    _print(followup.agenda(followup.status()))


def cmd_followup_triage(args):
    from . import followup
    f = followup.Followups()
    n = f.retriage()
    f.close_conn()
    _print(f"reclassified {n} item(s)")


def cmd_followup_split(args):
    from . import followup
    f = followup.Followups()
    new = f.split(args.id, args.part)
    f.close_conn()
    if not new:
        _print(f"[{args.id}] not found"); raise SystemExit(1)
    _print(f"split into {len(new)}: {', '.join(new)}")


def cmd_followup_nudge(args):
    from . import followup, telegram
    text = followup.agenda(followup.status())
    if not text:
        _print("nothing open - no nudge sent")
        return
    if args.dry_run:
        _print(text)
        return
    ok, err = telegram.post(text, seat=args.seat)
    _print("nudge sent" if ok else f"FAILED: {err}")
    if not ok:
        raise SystemExit(1)


def cmd_approve_grant(args):
    cmd = " ".join(args.command).strip()
    if not cmd:
        raise SystemExit("usage: cad approve grant --grantor alex -- <command...>")
    rule = guard.evaluate(cmd)
    if rule and rule.severity == "CRITICAL":
        _print(f"refused: {rule.name} is CRITICAL - no override exists")
        raise SystemExit(2)
    tok = guard.grant(cmd, grantor=args.grantor, ttl=args.ttl * 60)
    _print(f"granted {tok['hash']} by {args.grantor}, "
           f"valid {args.ttl}m, single use")


def cmd_approve_list(args):
    toks = guard.list_tokens()
    if not toks:
        _print("no approval tokens")
        return
    for t in toks:
        state = "valid" if t.get("valid") else "expired"
        _print(f"{t['hash']}  {state:<8} by {t.get('grantor','?'):<10} {t.get('command','')[:70]}")


def cmd_guard_test(args):
    cmd = " ".join(args.command).strip()
    rule = guard.evaluate(cmd, os.getcwd())
    if rule is None:
        _print("PASS - no rule matched")
        return
    _print(f"{rule.severity}: {rule.name} - {rule.why}")
    if rule.severity == "HIGH":
        _print(f"two-person token hash: {guard.command_hash(cmd)}")
    raise SystemExit(2 if rule.severity in ("CRITICAL", "HIGH") else 0)


def cmd_guard_install(args):
    log = []
    seatsetup.install_guard_hook(log, write=args.write,
                                 profiles=list(SEATS) if args.write else None)
    _print("\n".join(log))


def cmd_guard_hook(args):
    raise SystemExit(guard.hook_main(only=args.only))


def cmd_seats_status(args):
    from .hermes import ApiTransport
    api = ApiTransport()
    for name in SEATS:
        seat = models.effective_seat(name)
        pd = config.hermes_home() / "profiles" / name
        exists = pd.exists()
        gw = "-"
        if exists:
            gsp = pd / "gateway_state.json"
            if gsp.exists():
                try:
                    gw = json.loads(gsp.read_text()).get("gateway_state", "?")
                except Exception:
                    gw = "?"
        live = "api-up" if (exists and api.available(seat)) else ""
        _print(f"{seat.display:<10} profile={'yes' if exists else 'NO ':<4} "
               f"gateway={gw:<10} port={seat.port} {live}  {seat.model}")


def cmd_seats_up(args):
    cmds = seatsetup.gateway_commands(list(SEATS.values()))
    if not args.yes:
        _print("would run (pass --yes to execute):")
        for c in cmds:
            _print(f"  {c}")
        return
    for c in cmds:
        _print(f"$ {c}")
        code, out = seatsetup.run_hermes(c.split()[1:], timeout=120)
        _print(out[:300] if out else f"exit {code}")


def cmd_models_scan(args):
    try:
        market_raw, fetched_at = models.fetch_market(force=args.fresh)
    except Exception as e:
        raise SystemExit(f"OpenRouter fetch failed: {e} "
                         "(offline? try again, or without --fresh to use cache)")
    market = models.normalize(market_raw)
    rows = models.seat_report(market)
    promos = models.promo_candidates(market)
    _print(models.render_scan(rows, promos, fetched_at))


def cmd_models_set(args):
    _, log = models.set_seat_model(args.seat.lower(), args.model,
                                   provider=args.provider, note=args.note or "")
    _print("\n".join(log))


def cmd_models_value(args):
    led = Ledger()
    rows = models.value_report(led)
    led.close()
    if not rows:
        _print("no settled outcomes yet - value math needs reality first")
        return
    _print(f"{'seat':<10}{'model':<38}{'w/m/l':<10}{'spend $':<10}$/win")
    for r in rows:
        wml = f"{r['win']}/{r['mixed']}/{r['loss']}"
        spend = f"{r['council_spend_usd']:.3f}" if r['council_spend_usd'] is not None else "-"
        upw = f"{r['usd_per_win']:.3f}" if r['usd_per_win'] is not None else "-"
        _print(f"{r['seat']:<10}{r['model']:<38}{wml:<10}{spend:<10}{upw}")


def cmd_budget_set(args):
    """Set ceiling for a run. Raising requires --grantor (two-person rule)."""
    run_id = args.run
    ceiling = args.ceiling
    grantor = args.grantor
    
    budget = budgets.load_budget(run_id)
    if not budget:
        _print(f"error: budget not found for run {run_id}")
        return
    
    old_ceiling = budget.ceiling_usd
    if ceiling > old_ceiling and not grantor:
        _print(f"error: raising ceiling from ${old_ceiling:.2f} to ${ceiling:.2f} requires --grantor")
        _print("       (two-person rule: a different seat or operator must approve)")
        return
    
    success, msg = budgets.set_ceiling(run_id, ceiling, grantor)
    if success:
        _print(f"updated budget {run_id}: ${old_ceiling:.2f} -> ${ceiling:.2f}")
        if grantor:
            _print(f"approved by: {grantor}")
    else:
        _print(f"error: {msg}")


def cmd_budget_status(args):
    """Show current spend vs ceilings."""
    # Daily budget
    daily_status, daily_spend, daily_ceiling = budgets.check_daily_budget()
    _print("Daily Budget:")
    _print(f"  spend:   ${daily_spend:.4f} (effective, with drift multiplier)")
    _print(f"  ceiling: ${daily_ceiling:.2f}")
    _print(f"  status:  {daily_status}")
    _print()
    
    # Active run budgets
    active = budgets.list_active_budgets()
    if not active:
        _print("No active run budgets")
        return
    
    _print(f"Active Run Budgets ({len(active)}):")
    for b in active:
        status, spend, ceiling = budgets.check_budget(b.run_id)
        paused = " [PAUSED]" if b.paused else ""
        _print(f"  {b.run_id}: ${spend:.4f} / ${ceiling:.2f} ({status}){paused}")
        _print(f"    origin: {b.origin}  seats: {','.join(b.seats)}")


def cmd_budget_list(args):
    """List all active budgets."""
    active = budgets.list_active_budgets()
    if not active:
        _print("no active budgets")
        return
    
    for b in active:
        status, spend, ceiling = budgets.check_budget(b.run_id)
        paused = " [PAUSED]" if b.paused else ""
        _print(f"{b.run_id}: ${spend:.4f} / ${ceiling:.2f} ({status}){paused}")
        _print(f"  origin: {b.origin}  seats: {','.join(b.seats)}  sessions: {len(b.session_ids or [])}")


def cmd_budget_pause(args):
    """Pause a budget (stop all tool calls)."""
    run_id = args.run
    if budgets.pause_budget(run_id):
        _print(f"paused budget {run_id}")
    else:
        _print(f"error: budget not found for run {run_id}")


def cmd_budget_resume(args):
    """Resume a paused budget."""
    run_id = args.run
    if budgets.resume_budget(run_id):
        _print(f"resumed budget {run_id}")
    else:
        _print(f"error: budget not found for run {run_id}")


def cmd_telegram_init(args):
    p = telegram.ensure_settings_file()
    s = telegram.load_settings()
    ok, problems = telegram.settings_ready(s)
    if not ok:
        _print(f"settings: {p}")
        for prob in problems:
            _print(f"  fill in: {prob}")
        _print("runbook:  cad telegram runbook")
        return
    for line in telegram.bind_seats(write=args.write):
        _print(line)


def cmd_telegram_runbook(args):
    _print(telegram.RUNBOOK)


def cmd_telegram_test(args):
    ok, err = telegram.post(args.message or "caduceus: council online")
    _print("posted" if ok else f"FAILED: {err}")
    if not ok:
        raise SystemExit(1)


def cmd_dashboard(args):
    p = dashboard.write()
    _print(f"dashboard: {p}")
    if args.open:
        webbrowser.open(f"file://{p}")


def cmd_eval_finisher(args):
    """FINISHER planted-defect recall eval. See docs/finisher-eval-design.md.

    This eval exists because the 08-19 council made FINISHER's model choice
    provisional on third-party recall evidence: deterministic keyword/anchor
    scoring so Claude never grades Claude.
    """
    items_dir = Path(args.items) if args.items else config.repo_root() / "evals" / "finisher" / "items"
    key_path = Path(args.key) if args.key else config.repo_root() / "evals" / "finisher" / "answers.json"
    out_dir = Path(args.out) if args.out else config.caduceus_home() / "evals"
    soul_path = config.repo_root() / "seats" / "finisher" / "SOUL.md"

    candidates = eval_finisher.CANDIDATES
    if args.candidates:
        wanted = {c.strip() for c in args.candidates.split(",") if c.strip()}
        candidates = [c for c in candidates if c["model"] in wanted]
        if not candidates:
            raise SystemExit(f"--candidates matched none of the known models: {sorted(wanted)}")

    result = eval_finisher.run(
        items_dir=items_dir, key_path=key_path, candidates=candidates,
        passes=args.passes, dry_run=args.dry_run, max_usd=args.max_usd,
        out_dir=out_dir, soul_path=soul_path,
        resume=getattr(args, "resume", None),
    )

    est = result["estimate"]
    _print(f"Estimate: ${est['total_usd']:.2f} for {est['n_items']} items x "
           f"{est['n_candidates']} candidates x {est['passes']} passes")
    for model, d in est["per_candidate"].items():
        _print(f"  {model}: ${d['cost_usd']:.2f} ({d['price_source']})")

    if result.get("dry_run"):
        _print(f"dry-run: {result['packets']} packets queued, no network calls made")
        return

    _print(f"Actual spend: ${result['actual_spend_usd']:.2f}")
    _print(f"Report: {result.get('out_md', '')}")
    _print(f"Verdict: {result['verdict']}")


def cmd_plan(args):
    """Plan competition (Emanuel's 85%): full council on the goal, then FORGE
    decomposes the winning direction into concrete tasks."""
    mock = MockTransport() if args.dry_run else None
    council = Council(transport="mock" if args.dry_run else "auto", mock=mock)
    seats = [models.effective_seat(n) for n in config.FULL_COUNCIL]
    result = council.run(question=(
        "PLAN COMPETITION. Produce the best executable plan for this goal. "
        "Optimize for: fastest path to a shippable result, explicit sequencing, "
        "and what NOT to build.\nGOAL: " + args.goal
    ), seats=seats, context=_read_context(args), quick=False)
    _print(f"plan council: {result.run_id} -> memo {result.memo_path}")
    if getattr(args, "live", False):
        for line in telegram.broadcast_result(result):
            _print(f"telegram: {line}")
    if not result.winner:
        raise SystemExit("no winning plan - see memo/errors")

    decompose_prompt = (
        "[CADUCEUS DECOMPOSITION]\n"
        "Winning plan direction:\n" + (result.winner.recommendation or result.winner.position) +
        "\n\nKey points:\n- " + "\n- ".join(result.winner.key_points[:8]) +
        "\n\nDecompose into 5-20 self-contained tasks. Each task must be "
        "completable by one agent in one sitting without asking questions. "
        'Reply ONLY JSON: {"tasks":[{"title":"...","body":"what/why/done-when",'
        '"seat":"forge|finisher|recon|sparring|envoy","priority":1-5,'
        '"depends_on":[indices]}]}'
    )
    if args.dry_run:
        _print("[dry-run] skipping decomposition + kanban")
        return
    reply = OneshotTransport().ask(models.effective_seat("forge"), decompose_prompt)
    obj = extract_json(reply.text) if reply.ok else None
    if not obj or "tasks" not in obj:
        _print(f"decomposition failed ({reply.error or 'unparseable'}); "
               "winning plan is in the memo - decompose manually")
        return
    tasks = obj["tasks"]
    _print(f"\n{len(tasks)} tasks:")
    for i, t in enumerate(tasks):
        _print(f"  [{i}] ({t.get('seat', 'forge')}, p{t.get('priority', 3)}) "
               f"{t.get('title', '?')}"
               + (f"  <- deps {t['depends_on']}" if t.get("depends_on") else ""))
    if args.kanban:
        created = []
        for t in tasks:
            code, out = seatsetup.run_hermes([
                "kanban", "create", t.get("title", "untitled"),
                "--body", t.get("body", ""),
                "--assignee", t.get("seat", "forge"),
                "--priority", str(t.get("priority", 3)),
                "--json",
            ])
            tid = ""
            if code == 0:
                try:
                    tid = json.loads(out).get("id", "")
                except Exception:
                    tid = out.splitlines()[0][:30] if out else ""
            created.append(tid)
            _print(f"  kanban {'+' if code == 0 else '!'} {t.get('title','')[:60]} {tid}")
        _print("dependencies: link manually with `hermes kanban link` "
               "(indices above map to your new task ids)")
    else:
        _print("\nnothing queued (pass --kanban to create hermes kanban tasks)")


# ---------------------------------------------------------------- parser


# ---------------------------------------------------------------- compile

def _profile_path() -> Path:
    return config.repo_root() / "seats" / "PROFILE.json"


def _load_profile(args=None):
    path = Path(args.profile) if getattr(args, "profile", None) else _profile_path()
    if not path.exists():
        raise SystemExit(f"no profile at {path} (seats/PROFILE.json is the source of truth)")
    try:
        return profile_mod.load(path)
    except profile_mod.ProfileError as e:
        raise SystemExit(f"profile invalid: {e}")


def _manifest_or_exit():
    p = manifest_mod.default_manifest_path()
    if not p.exists():
        raise SystemExit(f"no skill manifest at {p}: run `cad compile manifest` first")
    return manifest_mod.load(p)


def cmd_compile(args):
    p = _load_profile(args)
    for w in p.warnings:
        _print(f"[warn] profile: {w}")
    c = compile_mod.cast(p)
    _print(f"profile: {p.person.get('name', '?')}  sha {p.sha256[:12]}  "
           f"archetype {p.best_archetype or '?'}")
    _print(f"cast:    {', '.join(s.seat for s in c.seats)}  (cast sha {c.sha256[:12]})")
    for s in c.seats:
        _print(f"  {s.display:<12} {'fired' if s.fired else 'filled':<6} {s.reason}")
    for w in c.warnings:
        _print(f"[warn] {w}")
    res = compile_mod.write_outputs(p, c, config.repo_root(), write=args.write)
    for k, v in res.items():
        _print(f"{k}: {v}")
    if not args.write and res.get("USER.md") == "would-write":
        import difflib
        current = config.repo_root() / "seats" / "USER.md"
        old_lines = current.read_text().splitlines() if current.exists() else []
        for line in difflib.unified_diff(old_lines, compile_mod.render_user_md(p, c).splitlines(),
                                         "seats/USER.md", "seats/USER.md (rendered)", lineterm="", n=1):
            _print(line)
    if not args.write and any(v == "would-write" for v in res.values()):
        _print("re-run with --write to apply, then `cad init` to push USER.md into the seats")


def _parse_root(spec: str):
    label, _, rest = spec.partition("=")
    if not rest:
        raise SystemExit(f"--root wants LABEL=PATH[:DEPTH], got {spec!r}")
    path, depth = rest, 3
    head, sep, tail = rest.rpartition(":")
    if sep and tail.isdigit():
        path, depth = head, int(tail)
    return (label, Path(path).expanduser(), depth)


def cmd_compile_manifest(args):
    roots = [] if args.roots_only else manifest_mod.default_roots()
    roots += [_parse_root(r) for r in args.root]
    m = manifest_mod.scan(roots=roots)
    out = manifest_mod.default_manifest_path()
    m.save(out)
    for label, n in m.counts.items():
        _print(f"{label}: {n}")
    if m.skipped_roots:
        _print(f"skipped (not on this machine): {', '.join(m.skipped_roots)}")
    _, denied = manifest_mod.Denylist.load(config.repo_root()).filter(m.entries)
    empty = sum(1 for e in m.entries if e.empty_description)
    _print(f"total: {len(m.entries)}  shadowed: {len(m.shadowed)}  denied: {len(denied)}  "
           f"empty-description: {empty}")
    _print(f"manifest: {out}")


def cmd_compile_propose(args):
    mani = _manifest_or_exit()
    p = _load_profile(args)
    c = compile_mod.cast(p)
    deny = manifest_mod.Denylist.load(config.repo_root())
    kept, denied = deny.filter(mani.entries)
    cache = loadout.Cache(loadout.default_cache_path())
    if args.dry_run:
        sc = loadout.score_skills(kept, c, None, cache, dry_run=True)
        est = sc.planned * 5000 * jev.USD_PER_INPUT_TOKEN
        _print(f"planned: {sc.planned} requests ({sc.cached} cached, {len(denied)} denied), "
               f"est ≈ ${est:.3f} — dry-run, no network")
        return
    if not jev.available():
        _print(f"no {jev.ENV_KEY} in {config.env_file()} — Jev cannot score the shelf. "
               "A hand-written seats/LOADOUT.json always works: cad compile install --table …")
        raise SystemExit(2)
    client = jev.Client()
    try:
        sc = loadout.score_skills(kept, c, client, cache, max_usd=args.max_usd)
    finally:
        cache.save()
    prop = loadout.propose(sc, c, deny, per=args.per)
    prop["denied"] = sorted(e.name for e in denied)
    out = Path(args.out) if args.out else config.repo_root() / "seats" / "LOADOUT-PROPOSAL.json"
    out.write_text(json.dumps(prop, indent=1, ensure_ascii=False) + "\n")
    _print(f"scored: {sc.calls} calls, {sc.cached} cached, {len(sc.errors)} errors, "
           f"≈ ${sc.est_usd:.4f}" + (f"  STOPPED: {sc.stopped_reason}" if sc.stopped_reason else ""))
    _print(f"proposal: {out}")
    _print("edit it into seats/LOADOUT.json (the table you install is the one you read), "
           "then `cad compile install`")


def cmd_compile_install(args):
    mani = _manifest_or_exit()
    p = _load_profile(args)
    c = compile_mod.cast(p)
    table_path = Path(args.table) if args.table else config.repo_root() / "seats" / "LOADOUT.json"
    if not table_path.exists():
        _print(f"no loadout table at {table_path}: copy seats/LOADOUT-PROPOSAL.json to "
               "seats/LOADOUT.json (edit it) or write one by hand")
        raise SystemExit(2)
    table = loadout.load_table(table_path)
    res = loadout.install(table, c, mani, cap=args.cap)
    for seat, r in res.items():
        if r["skipped"]:
            _print(f"{seat}: skipped ({r['skipped']})")
            continue
        line = f"{seat}: {len(r['installed'])} in reach"
        if r["missing"]:
            line += f"  missing: {', '.join(r['missing'])}"
        if r["removed"]:
            line += f"  removed: {', '.join(r['removed'])}"
        _print(line)
    t0 = loadout.first_install_ts()
    if t0:
        import time as _t
        _print(f"clock started {_t.strftime('%Y-%m-%d', _t.localtime(t0))} "
               f"(rule: {evalpair.RULE_WINS} paired wins by day {evalpair.RULE_DAYS})")


def cmd_compile_uninstall(args):
    removed = loadout.uninstall()
    if not removed:
        _print("nothing installed")
    for seat, n in removed.items():
        _print(f"{seat}: {n} removed")


def cmd_compile_status(args):
    st = loadout.status()
    cast_path = config.repo_root() / "seats" / "CAST.json"
    if cast_path.exists():
        try:
            _print(f"cast sha:  {json.loads(cast_path.read_text()).get('cast_sha256', '')[:12]}")
        except ValueError:
            pass
    table_path = config.repo_root() / "seats" / "LOADOUT.json"
    if table_path.exists():
        _print(f"table sha: {loadout.table_sha256(loadout.load_table(table_path))[:12]}")
    for seat, s in st["seats"].items():
        _print(f"{seat}: {s['installed']}")
    t0 = st["first_install_ts"]
    if t0:
        import time as _t
        days = int((_t.time() - t0) // 86400)
        _print(f"clock: day {days}/{evalpair.RULE_DAYS} (started "
               f"{_t.strftime('%Y-%m-%d', _t.localtime(t0))})")
    else:
        _print("clock: not started (no loadout installed yet)")
    led = Ledger()
    try:
        r = evalpair.report(led)
    finally:
        led.close()
    _print(f"pairs: {r['pairs']} · B {r['b_wins']} · A {r['a_wins']} · ties {r['ties']} · "
           f"unsettled {r['unsettled']} · verdict: {r['verdict']}")


def cmd_compile_dispatch(args):
    fn = {None: cmd_compile, "manifest": cmd_compile_manifest, "propose": cmd_compile_propose,
          "install": cmd_compile_install, "uninstall": cmd_compile_uninstall,
          "status": cmd_compile_status}[getattr(args, "ccmd", None)]
    fn(args)


def _eval_loadout_report():
    led = Ledger()
    try:
        r = evalpair.report(led)
    finally:
        led.close()
    _print(f"pairs: {r['pairs']} · B {r['b_wins']} · A {r['a_wins']} · ties {r['ties']} · "
           f"unsettled {r['unsettled']}")
    _print(f"days: {'-' if r['days'] is None else int(r['days'])}/{evalpair.RULE_DAYS}   "
           f"late pairs (outside the window): {r['late_pairs']}")
    _print(f"rule: {r['rule']}")
    for row in r["rows"]:
        _print(f"  {row['pair_id']}  {row['outcome']:<9} {row['question']}")
    _print(f"verdict: {r['verdict']}")
    if r["verdict"] == "PARK":
        _print("PARK means `cad compile uninstall` and leave it out until the shelf changes")


def cmd_eval_loadout(args):
    if args.question == "report":
        _eval_loadout_report()
        return
    seats = seat_list(args.seats) if args.seats else [SEATS[n] for n in config.FULL_COUNCIL]
    seats = [models.effective_seat(s.name) for s in seats]
    for w in heterogeneity_warnings(seats):
        _print(f"[warn] {w}")
    dry = args.dry_run
    table_path = Path(args.table) if args.table else config.repo_root() / "seats" / "LOADOUT.json"
    table = loadout.load_table(table_path) if table_path.exists() else {"seats": {}}
    cast = mani = None
    if table.get("seats") and manifest_mod.default_manifest_path().exists():
        mani = manifest_mod.load(manifest_mod.default_manifest_path())
        cast = compile_mod.cast(_load_profile(args))
    elif table.get("seats"):
        _print("[warn] loadout table present but no manifest: arm B runs without loadouts "
               "(run `cad compile manifest`)")

    def factory():
        return Council(transport="mock" if dry else "auto", mock=MockTransport() if dry else None)

    def before_run(run_id, run_seats):
        if dry:
            return
        budgets.create_budget(run_id=run_id, origin="council", seats=[s.name for s in run_seats],
                              ceiling_usd=budgets.CEILINGS["full_council"]["hard"],
                              session_ids=[f"caduceus-{s.name}-{run_id}" for s in run_seats])

    try:
        pr = evalpair.run_pair(args.question, seats, _read_context(args), dry, table, cast, mani,
                               factory, before_run=before_run)
    except evalpair.PairError as e:
        _print(f"refused: {e}")
        raise SystemExit(2)
    _print(f"pair:     {pr.pair_id}")
    for arm, r in (("A (no loadout)", pr.a), ("B (loadout)", pr.b)):
        lead = r.winner.seat.upper() if r.winner else "-"
        _print(f"  {arm:<15} {r.run_id}  lead {lead}  memo {r.memo_path}")
    _print("settle BOTH when reality reports back, e.g.:")
    _print(f"  cad ledger settle {pr.a.run_id} --winner <seat>")
    _print(f"  cad ledger settle {pr.b.run_id} --winner <seat>")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cad",
        description="Caduceus - multi-seat decision engine on Hermes Agent. "
                    "The operator is the Shaper; the seats are the staff.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="provision seat profiles, souls, skill, guard")
    s.add_argument("--seats", help="comma list (default: all five)")
    s.add_argument("--cron", action="store_true", help="register morning brief + weekly ledger cron")
    s.add_argument("--force-soul", action="store_true", help="overwrite existing SOUL.md files")
    s.add_argument("--guard-write", action="store_true", help="append guard hook to config.yaml files")
    s.add_argument("--no-api", action="store_true", help="skip api_server blocks in seat configs")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("doctor", help="verify the engine end to end")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("brief", help="operator brief: open loops, dead jobs - "
                                     "deterministic, no model")
    s.add_argument("--weekly", action="store_true", help="weekly ledger summary instead of morning brief")
    s.add_argument("--write", action="store_true", help="also write the section into CLAUDE-PENDING-ACTIONS.md")
    s.set_defaults(fn=cmd_brief)

    c = sub.add_parser("council", help="deliberation")
    csub = c.add_subparsers(dest="ccmd", required=True)
    s = csub.add_parser("ask", help="run a council on a question")
    s.add_argument("question")
    s.add_argument("--seats", help="comma list (default: full council)")
    s.add_argument("--quick", action="store_true", help="FORGE+FINISHER pair first, escalate on disagreement")
    s.add_argument("--no-escalate", action="store_true")
    s.add_argument("--context", help="inline context string")
    s.add_argument("--context-file", help="file whose contents are the brief context")
    s.add_argument("--transport", default="auto", choices=["auto", "oneshot", "api"])
    s.add_argument("--dry-run", action="store_true", help="mock transport, no model calls")
    s.add_argument("--live", action="store_true",
                   help="broadcast attributed results to the Telegram council group")
    s.set_defaults(fn=cmd_council_ask)
    s = csub.add_parser("review-command", help="FINISHER reviews a risky command (two-person rule)")
    s.add_argument("command", nargs=argparse.REMAINDER)
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_council_review_command)

    ex = sub.add_parser("exec", help="autonomous staff-work executor")
    esub = ex.add_subparsers(dest="ecmd", required=True)
    s = esub.add_parser("queue", help="agent-owned work waiting")
    s.set_defaults(fn=cmd_exec_queue)
    s = esub.add_parser("run", help="execute staff queue (dry-run by default)")
    s.add_argument("--live", action="store_true")
    s.add_argument("--max", type=int, default=2)
    s.set_defaults(fn=cmd_exec_run)

    fu = sub.add_parser("followup", help="open loops: unexecuted advice + ungraded decisions")
    fsub = fu.add_subparsers(dest="fcmd", required=True)
    s = fsub.add_parser("list", help="what is still open")
    s.set_defaults(fn=cmd_followup_list)
    s = fsub.add_parser("open", help="track an action a council recommended")
    s.add_argument("run_id"); s.add_argument("action")
    s.add_argument("--seat", help="seat that recommended it")
    s.set_defaults(fn=cmd_followup_open)
    s = fsub.add_parser("done", help="mark a tracked action as executed")
    s.add_argument("id"); s.add_argument("--note")
    s.set_defaults(fn=cmd_followup_done)
    s = fsub.add_parser("drop", help="abandon a tracked action (with reason)")
    s.add_argument("id"); s.add_argument("--note")
    s.set_defaults(fn=cmd_followup_drop)
    s = fsub.add_parser("agenda", help="what needs YOU (staff work collapsed)")
    s.set_defaults(fn=cmd_followup_agenda)
    s = fsub.add_parser("triage", help="re-classify pending items by ownership")
    s.set_defaults(fn=cmd_followup_triage)
    s = fsub.add_parser("split", help="break a compound item into atomic actions")
    s.add_argument("id"); s.add_argument("part", nargs="+")
    s.set_defaults(fn=cmd_followup_split)
    s = fsub.add_parser("nudge", help="push the agenda to telegram")
    s.add_argument("--seat", default="envoy", help="seat profile to post as")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_followup_nudge)

    lg = sub.add_parser("ledger", help="believability ledger")
    lsub = lg.add_subparsers(dest="lcmd", required=True)
    s = lsub.add_parser("show", help="seat x domain scores")
    s.set_defaults(fn=cmd_ledger_show)
    s = lsub.add_parser("runs", help="council runs awaiting settlement")
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_ledger_runs)
    s = lsub.add_parser("record", help="record one outcome directly")
    s.add_argument("seat"); s.add_argument("domain")
    s.add_argument("result", choices=["win", "mixed", "loss", "unexecuted"])
    s.add_argument("--ref"); s.add_argument("--note")
    s.set_defaults(fn=cmd_ledger_record)
    s = lsub.add_parser("settle", help="judge a council run against reality")
    s.add_argument("run_id")
    s.add_argument("--winner", action="append")
    s.add_argument("--loser", action="append")
    s.add_argument("--mixed", action="append")
    s.add_argument("--unexecuted", action="append")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_ledger_settle)
    s = lsub.add_parser("resettle",
                        help="void a run's prior outcomes and settle it again (history kept)")
    s.add_argument("run_id")
    s.add_argument("--winner", action="append")
    s.add_argument("--loser", action="append")
    s.add_argument("--mixed", action="append")
    s.add_argument("--unexecuted", action="append")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_ledger_resettle)

    ap = sub.add_parser("approve", help="two-person rule tokens")
    asub = ap.add_subparsers(dest="acmd", required=True)
    s = asub.add_parser("grant")
    s.add_argument("--grantor", required=True, help="alex or a seat name")
    s.add_argument("--ttl", type=int, default=15, help="minutes (default 15)")
    s.add_argument("command", nargs=argparse.REMAINDER)
    s.set_defaults(fn=cmd_approve_grant)
    s = asub.add_parser("list")
    s.set_defaults(fn=cmd_approve_list)

    g = sub.add_parser("guard", help="destructive-command guard")
    gsub = g.add_subparsers(dest="gcmd", required=True)
    s = gsub.add_parser("test", help="evaluate a command against the rules")
    s.add_argument("command", nargs=argparse.REMAINDER)
    s.set_defaults(fn=cmd_guard_test)
    s = gsub.add_parser("install", help="print or write the hooks: config block")
    s.add_argument("--write", action="store_true")
    s.set_defaults(fn=cmd_guard_install)
    s = gsub.add_parser("hook", help="(internal) hermes pre_tool_call entry - reads stdin")
    s.add_argument("--only", choices=["third-party"], default=None,
                   help="apply just this rule (the operator's own profile)")
    s.set_defaults(fn=cmd_guard_hook)

    se = sub.add_parser("seats", help="seat gateway management")
    ssub = se.add_subparsers(dest="scmd", required=True)
    s = ssub.add_parser("status")
    s.set_defaults(fn=cmd_seats_status)
    s = ssub.add_parser("up", help="install + start per-seat gateways (launchd)")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_seats_up)

    mo = sub.add_parser("models", help="model market: pricing, promos, recasting")
    msub = mo.add_subparsers(dest="mcmd", required=True)
    s = msub.add_parser("scan", help="live OpenRouter pricing vs current seat casting")
    s.add_argument("--fresh", action="store_true", help="bypass the 24h cache")
    s.set_defaults(fn=cmd_models_scan)
    s = msub.add_parser("set", help="recast a seat's model (casting + profile patch)")
    s.add_argument("seat")
    s.add_argument("model", help="e.g. google/gemini-3.7-flash")
    s.add_argument("--provider", default="openrouter")
    s.add_argument("--note", help="why (e.g. 'launch promo until it lapses')")
    s.set_defaults(fn=cmd_models_set)
    s = msub.add_parser("value", help="$ per win by seat/model from the ledger")
    s.set_defaults(fn=cmd_models_value)

    b = sub.add_parser("budget", help="spend guard: per-run budgets + daily aggregation")
    bsub = b.add_subparsers(dest="bcmd", required=True)
    s = bsub.add_parser("set", help="set ceiling for a run (requires two-person approval to raise)")
    s.add_argument("--run", required=True, help="run_id")
    s.add_argument("--ceiling", required=True, type=float, help="new ceiling in USD")
    s.add_argument("--grantor", help="who approved the raise (required if raising)")
    s.set_defaults(fn=cmd_budget_set)
    s = bsub.add_parser("status", help="show current spend vs ceilings")
    s.set_defaults(fn=cmd_budget_status)
    s = bsub.add_parser("list", help="list active budgets")
    s.set_defaults(fn=cmd_budget_list)
    s = bsub.add_parser("pause", help="pause a budget (stop all tool calls)")
    s.add_argument("--run", required=True, help="run_id")
    s.set_defaults(fn=cmd_budget_pause)
    s = bsub.add_parser("resume", help="resume a paused budget")
    s.add_argument("--run", required=True, help="run_id")
    s.set_defaults(fn=cmd_budget_resume)

    s = sub.add_parser("dashboard", help="regenerate the HTML status board")
    s.add_argument("--open", action="store_true")
    s.set_defaults(fn=cmd_dashboard)

    s = sub.add_parser("plan", help="plan competition -> decomposition -> optional kanban")
    s.add_argument("goal")
    s.add_argument("--kanban", action="store_true", help="create hermes kanban tasks")
    s.add_argument("--context"); s.add_argument("--context-file")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--live", action="store_true",
                   help="broadcast plan-council results to the Telegram group")
    s.set_defaults(fn=cmd_plan)

    tg = sub.add_parser("telegram", help="council group bridge (observation deck)")
    tsub = tg.add_subparsers(dest="tcmd", required=True)
    s = tsub.add_parser("init", help="create settings template / bind seats to bots")
    s.add_argument("--write", action="store_true", help="write platform blocks into seat configs")
    s.set_defaults(fn=cmd_telegram_init)
    s = tsub.add_parser("runbook", help="BotFather + group setup steps")
    s.set_defaults(fn=cmd_telegram_runbook)
    s = tsub.add_parser("test", help="post a test message to the council group")
    s.add_argument("message", nargs="?")
    s.set_defaults(fn=cmd_telegram_test)

    ev = sub.add_parser("eval", help="planted-defect evals")
    evsub = ev.add_subparsers(dest="evcmd", required=True)
    s = evsub.add_parser("finisher", help="FINISHER planted-defect recall eval")
    s.add_argument("--dry-run", action="store_true", help="print estimate + packet count, no network")
    s.add_argument("--passes", type=int, default=2)
    s.add_argument("--candidates", help="comma-separated model ids to restrict to")
    s.add_argument("--max-usd", type=float, default=25.0)
    s.add_argument("--items", help="override items dir (default evals/finisher/items)")
    s.add_argument("--key", help="override answer key (default evals/finisher/answers.json)")
    s.add_argument("--out", help="override output dir (default ~/.caduceus/evals)")
    s.add_argument("--resume", help="a prior finisher-*.calls.jsonl: reuse its calls, spend only on the rest")
    s.set_defaults(fn=cmd_eval_finisher)

    s = evsub.add_parser("loadout", help="paired A/B council: same question without and with loadouts; or `report`")
    s.add_argument("question", help="the council question, or the word `report`")
    s.add_argument("--seats", help="comma list (default: full council)")
    s.add_argument("--context"); s.add_argument("--context-file")
    s.add_argument("--table", help="override seats/LOADOUT.json")
    s.add_argument("--dry-run", action="store_true", help="mock transport, no model calls, excluded from the report")
    s.set_defaults(fn=cmd_eval_loadout)

    cp = sub.add_parser("compile", help="profile -> cast -> USER.md; skill manifest, loadout proposal, install")
    cp.add_argument("--write", action="store_true", help="write seats/USER.md + seats/CAST.json on change")
    cp.add_argument("--profile", help="override seats/PROFILE.json")
    cp.set_defaults(fn=cmd_compile_dispatch)
    csub = cp.add_subparsers(dest="ccmd")
    s = csub.add_parser("manifest", help="scan SKILL.md across the roots into ~/.caduceus/skill-manifest.json")
    s.add_argument("--root", action="append", default=[], help="LABEL=PATH[:DEPTH], repeatable")
    s.add_argument("--roots-only", action="store_true", help="skip the default roots")
    s = csub.add_parser("propose", help="Jev scores the shelf -> seats/LOADOUT-PROPOSAL.json")
    s.add_argument("--per", type=int, default=5, help="skills per seat per domain")
    s.add_argument("--max-usd", type=float, default=1.0)
    s.add_argument("--dry-run", action="store_true", help="count requests, no network")
    s.add_argument("--out", help="override the proposal path")
    s = csub.add_parser("install", help="copy the table's skills into each seat's skills/loadout/")
    s.add_argument("--table", help="override seats/LOADOUT.json")
    s.add_argument("--cap", type=int, default=15, help="max skills per seat")
    csub.add_parser("uninstall", help="remove exactly what install recorded")
    csub.add_parser("status", help="installed counts, clock, pair report")

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    # strip a leading '--' from REMAINDER captures
    if hasattr(args, "command") and args.command and args.command[0] == "--":
        args.command = args.command[1:]
    try:
        args.fn(args)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

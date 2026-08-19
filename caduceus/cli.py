"""cad - the Caduceus CLI. Every subcommand does something real or exits loudly."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import webbrowser
from pathlib import Path

from . import config, dashboard, doctor, guard, models, seatsetup, telegram
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


def cmd_doctor(args):
    rows = doctor.checks()
    _print(doctor.render(rows))
    raise SystemExit(doctor.exit_code(rows))


def cmd_council_ask(args):
    seats = seat_list(args.seats) if args.seats else (
        [SEATS[n] for n in config.QUICK_PAIR] if args.quick
        else [SEATS[n] for n in config.FULL_COUNCIL])
    seats = [models.effective_seat(s.name) for s in seats]  # casting overrides
    for w in heterogeneity_warnings(seats):
        _print(f"[warn] {w}")
    mock = MockTransport() if args.dry_run else None
    council = Council(transport="mock" if args.dry_run else args.transport, mock=mock)
    result = council.run(
        question=args.question,
        seats=seats,
        context=_read_context(args),
        quick=args.quick,
        escalate=not args.no_escalate,
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
    _print(f"{'seat':<10}{'domain':<16}{'w/m/l':<10}{'score':<8}basis")
    for r in rows:
        _print(f"{r['seat']:<10}{r['domain']:<16}"
               f"{str(r['win']) + '/' + str(r['mixed']) + '/' + str(r['loss']):<10}"
               f"{r['believability']:<8}{r['basis']}")
    led.close()


def cmd_ledger_runs(args):
    led = Ledger()
    runs = led.runs(unsettled_only=not args.all)
    for r in runs:
        flag = " " if r["settled"] else "*"
        _print(f"{flag} {r['run_id']}  [{r['domain']}]  {r['question'][:80]}")
    if not runs:
        _print("no runs" + ("" if args.all else " awaiting settlement"))
    led.close()


def cmd_ledger_record(args):
    led = Ledger()
    oid = led.record(args.seat, args.domain, args.result,
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
                     winners=args.winner or [],
                     losers=args.loser or [],
                     mixed=args.mixed or [],
                     note=args.note or "",
                     models=seat_models)
    for seat, oid in out.items():
        _print(f"settled {seat}: {oid}")
    if not out:
        _print("run marked settled with no outcomes (use --winner/--loser/--mixed)")
    led.close()


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
    rule = guard.evaluate(cmd)
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
    raise SystemExit(guard.hook_main())


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

    lg = sub.add_parser("ledger", help="believability ledger")
    lsub = lg.add_subparsers(dest="lcmd", required=True)
    s = lsub.add_parser("show", help="seat x domain scores")
    s.set_defaults(fn=cmd_ledger_show)
    s = lsub.add_parser("runs", help="council runs awaiting settlement")
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_ledger_runs)
    s = lsub.add_parser("record", help="record one outcome directly")
    s.add_argument("seat"); s.add_argument("domain")
    s.add_argument("result", choices=["win", "mixed", "loss"])
    s.add_argument("--ref"); s.add_argument("--note")
    s.set_defaults(fn=cmd_ledger_record)
    s = lsub.add_parser("settle", help="judge a council run against reality")
    s.add_argument("run_id")
    s.add_argument("--winner", action="append")
    s.add_argument("--loser", action="append")
    s.add_argument("--mixed", action="append")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_ledger_settle)

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

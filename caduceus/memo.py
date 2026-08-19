"""Decision memo rendering. The memo is the council's product: recommendation,
weighted rationale, and - non-negotiable - the Minority Report."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from . import config

if TYPE_CHECKING:  # avoid circular import at runtime
    from .council import CouncilResult
    from .ledger import Ledger


def write_memo(result: "CouncilResult", ledger: "Ledger") -> str:
    lines = []
    ts = time.strftime("%Y-%m-%d %H:%M")
    lines.append(f"# Council Memo - {result.run_id}")
    lines.append("")
    lines.append(f"**Question:** {result.question}")
    lines.append("")
    lines.append(f"**Domain:** {result.domain} | **Mode:** {result.mode} | "
                 f"**Seats:** {', '.join(result.seats)} | "
                 f"**Elapsed:** {result.elapsed_s}s | {ts}")
    lines.append("")

    if result.winner:
        w = result.winner
        lines.append("## Recommendation (weighted, not voted)")
        lines.append("")
        lines.append(f"**Lead seat:** {w.seat.upper()} "
                     f"(weight {result.weights.get(w.seat, 0):.3f} = "
                     f"believability x confidence {w.confidence:.2f})")
        lines.append("")
        lines.append(w.recommendation or w.position)
        lines.append("")
        if w.key_points:
            lines.append("**Why:**")
            lines.append("")
            for p in w.key_points:
                lines.append(f"- {p}")
            lines.append("")
        if w.risks:
            lines.append("**Known risks in this recommendation:**")
            lines.append("")
            for r in w.risks:
                lines.append(f"- {r}")
            lines.append("")
    else:
        lines.append("## No usable recommendation")
        lines.append("")
        lines.append("Not enough seats returned parseable drafts. See errors below.")
        lines.append("")

    if result.dissent:
        d = result.dissent
        lines.append("## Minority Report (preserved verbatim - read this)")
        lines.append("")
        lines.append(f"**Dissenting seat:** {d.seat.upper()} "
                     f"(weight {result.weights.get(d.seat, 0):.3f}, "
                     f"confidence {d.confidence:.2f})")
        lines.append("")
        lines.append(f"Position: {d.position}")
        lines.append("")
        lines.append(f"Recommendation: {d.recommendation}")
        lines.append("")
        if d.key_points:
            for p in d.key_points:
                lines.append(f"- {p}")
            lines.append("")
    elif result.winner:
        lines.append("## Minority Report")
        lines.append("")
        lines.append("_No substantive dissent survived cross-examination. "
                     "Treat unanimous councils with suspicion; consider adding "
                     "a seat from another model family next time._")
        lines.append("")

    lines.append("## Seat weights")
    lines.append("")
    lines.append("| Seat | Weight | Believability basis | Confidence |")
    lines.append("|---|---|---|---|")
    for name, score in result.ranked:
        b = ledger.believability(name, result.domain)
        draft = None
        for rnd in sorted(result.rounds.keys(), reverse=True):
            for dd in result.rounds[rnd]:
                if dd.seat == name:
                    draft = dd
                    break
            if draft:
                break
        conf = f"{draft.confidence:.2f}" if draft else "-"
        lines.append(f"| {name} | {score:.3f} | {b.score:.3f} ({b.basis}) | {conf} |")
    lines.append("")

    if result.conformity_flags:
        lines.append("## Conformity flags")
        lines.append("")
        for f in result.conformity_flags:
            lines.append(f"- {f}")
        lines.append("")

    if result.errors:
        lines.append("## Errors")
        lines.append("")
        for e in result.errors:
            lines.append(f"- {e}")
        lines.append("")

    if result.costs:
        total = sum(result.costs.values())
        per = ", ".join(f"{k} ${v:.3f}" for k, v in sorted(result.costs.items()))
        lines.append(f"**Estimated cost:** ${total:.3f} ({per})")
        lines.append("")

    lines.append("---")
    lines.append(f"_Settle this run once reality reports back: "
                 f"`cad ledger settle {result.run_id} --winner <seat>` "
                 f"(or `--mixed`/`--loser`). Unsettled advice never improves "
                 f"the ledger._")
    lines.append("")

    path = config.runs_dir() / f"{result.run_id}.md"
    path.write_text("\n".join(lines))
    return str(path)

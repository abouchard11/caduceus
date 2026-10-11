## Settlement sheet — the seven open runs only Alex can score (2026-10-10)

Closed on written evidence today: `20260927-035811-afe300` (aw-client#116) → `--unexecuted` all seats,
zero weight; the 09-30 backlog closeout chose "finish without nudging Erik" over the council's
"send the comment now".

Each line: run · lead · what the lead said · what the disk shows · suggested verdict. A suggestion
is not a settlement; `cad ledger settle <run> --winner <seat>` / `--loser` / `--mixed` / `--unexecuted`.

| Run | Lead | Lead said | Disk shows | Suggested |
|---|---|---|---|---|
| 20260924-151047-81f1ba | RECON | Pre-register X88 before touching breaker.js:712 | `experiments/x88-quarantine-expiry/README.md` registered, "instruction obeyed, nothing in src/ edited", status UNBUILT/SEALED | `--winner recon` once X88 runs; the process half already held |
| 20261002-211207-df32e6 | FINISHER | $0 two-blind-coder card sort this week over the 20 real rules | Portfolio memo 10-03 ranks it "Must, this week, $0"; no run artifact after 10-03 | open until the card sort runs; `--unexecuted` if it never does |
| 20261002-220944-b3e609 | SPARRING | $0 headless scanner across 5 external devs; kill if <3 act in 48h | same memo; no scanner-run artifact | same |
| 20261002-224350-bd995b | RECON | Ship the scanner to 6 operators + sha manifest, same session | same | same |
| 20261001-203344-383a56 | RECON | File no plugin; outbound to the 661-company Index + remediation offer | No plugin filed (half followed); no outbound artifact found | `--mixed recon` if outbound never ran; `--winner` if it ran and produced scans |
| 20260930-044738-0a05e3 | SPARRING | Stage Item A (X) and Item D (LinkedIn); release after operator execution | `outputs/linkedin-x-content-plan-2026-09-30/` exists; posting not visible from disk | `--winner sparring` if posted and it landed; `--unexecuted` if never posted |
| 20260907-003316-1758b8 | RECON | 30-day pain-only outreach sprint (gate: 3+ written pilot signals) + one-hour counsel call | 09-24 brief: "no customer has ever asked"; counsel call not evidenced | `--unexecuted recon` unless outreach or the call happened off-disk |

## Applied 2026-10-10 evening (Alex delegated the sheet)
Settled as suggested, conservative branch where conditional: 81f1ba `--winner recon`; df32e6, b3e609,
bd995b, 1758b8, 0a05e3 `--unexecuted` all seats; 383a56 `--mixed recon --unexecuted forge,finisher,sparring`.
All eight of the day's settlements were first written with comma lists that the CLI stored as literal
seat names; PR #22 fixed the CLI and every run was re-settled with real names (prior rows voided,
history kept). Resettle any of these if reality differs: `cad ledger resettle <run> --winner <seat>`.
20260929-233211-ea55cf (a note in the seat slot) re-settled 2026-10-11 from that note's own text: recon and sparring mixed.

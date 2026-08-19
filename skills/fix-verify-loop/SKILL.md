---
name: fix-verify-loop
description: >
  Two-agent execution engine for infrastructure and code fixes. CODE FIXER applies changes
  (CLI commands, file edits, browser actions), VERIFIER confirms each one landed before
  proceeding. Ingests audit .md files or inline issue lists. Use this skill whenever the user
  says "fix these issues", "execute the audit", "run the fixes", "apply the remediation",
  "work through the fix list", "fix and verify", "run the audit fixes", or has a list of
  bugs/issues to fix across one or more projects. Also trigger when the user describes a
  fix-then-check workflow, says "fix it and make sure it worked", or pastes an audit document
  with prioritized issues. Even if the user just says "go fix everything" after discussing
  infrastructure problems — use this skill. Do NOT use for discovery/auditing (use seo-audit,
  geo-crawl-audit, or similar). This skill is for EXECUTION of known fixes, not diagnosis.
---

# Fix-Verify Loop

A two-agent execution pattern for applying and confirming infrastructure, code, and
configuration fixes. Inspired by the Solver/Operator split: deterministic code does
the grunt work, AI verifies the results.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   ORCHESTRATION                      │
│                                                      │
│  1. Ingest task list (audit .md or inline)           │
│  2. Parse into ordered fix queue                     │
│  3. For each fix:                                    │
│     ┌──────────┐    ┌──────────┐                     │
│     │  FIXER   │───▶│ VERIFIER │──▶ PASS → next fix  │
│     │          │    │          │──▶ FAIL → retry (2x) │
│     └──────────┘    └──────────┘──▶ FAIL → escalate  │
│  4. Log every action to FIXES_APPLIED.md             │
│  5. Final summary report                             │
└─────────────────────────────────────────────────────┘
```

## Core Principles

### Solver/Operator Split
- **FIXER is the Solver**: deterministic, fast, no judgment calls. Runs sed, grep, curl,
  vercel CLI, file edits, npm commands. When a fix requires browser interaction (dashboard
  clicks), FIXER delegates to claude-in-chrome or desktop tools with a scripted CDP sequence.
- **VERIFIER is the Operator**: uses AI judgment only where needed — interpreting curl output,
  checking page titles, confirming content changes, reading HTTP status codes.

### Loop on a Ladder (Escalation)
Attempt fixes at the cheapest level first. Escalate only when the simpler approach fails:

1. **Rung 1 — CLI/file edit**: sed, grep, vercel CLI, supabase CLI, direct file writes.
   Fast, free, deterministic. Default for all code-level fixes.
2. **Rung 2 — Browser automation**: CDP trusted clicks via claude-in-chrome for dashboard
   actions (Vercel domain settings, Namecheap toggles, Supabase config, Clerk key swaps).
   Use when no CLI equivalent exists.
3. **Rung 3 — Human handoff**: When the fix requires credentials the agent cannot touch
   (API keys, passwords, payment info) or irreversible destructive actions. Pause, tell
   the user exactly what to do, wait for confirmation, then VERIFIER checks the result.

### Write It Down, Replay Forever
Every fix sequence that works gets logged in FIXES_APPLIED.md with the exact commands.
If the same class of issue appears again, the log becomes the playbook.

---

## Step 0 — Ingest the Task List

### From audit files
```
Scan the working directory for *.md files matching audit patterns:
- Files containing "CRITICAL", "HIGH", "MEDIUM", "Priority", "Fix:" headers
- Files with execution order tables or numbered fix lists
- Parse each issue into a structured queue:
  {priority, title, description, fix_commands[], verification_check, status}
```

### From inline descriptions
```
If the user describes issues in chat instead of providing files:
- Extract each distinct issue
- Assign priority based on user's ordering or severity language
- Ask for repo paths before touching any code
- Build the same structured queue
```

### Queue ordering rules
1. Respect explicit priority tables in audit files (execute in listed order)
2. If no explicit order: CRITICAL → HIGH → MEDIUM → LOW
3. Within same priority: lowest-effort first (quick wins build momentum)
4. Dependency awareness: if Fix B depends on Fix A completing, enforce ordering

---

## Step 1 — FIXER Agent Protocol

For each fix in the queue:

### 1a. Determine the rung

Ask: "Can this fix be done with a CLI command or file edit?"
- YES → Rung 1. Execute directly.
- NO → "Is there a dashboard/UI action needed?"
  - YES → Rung 2. Check if claude-in-chrome or desktop tools are available.
    - AVAILABLE → Script the CDP interaction.
    - NOT AVAILABLE → Rung 3. Human handoff.
  - NO → Rung 3. Requires credentials or irreversible action. Human handoff.

### 1b. Execute the fix

**Rung 1 — CLI/file fixes:**
```bash
# Pattern: execute command, capture output, pass to VERIFIER
RESULT=$(command_here 2>&1)
echo "$RESULT"
# VERIFIER evaluates $RESULT
```

Common fix patterns:
- `sed -i` for text replacements (tel links, URLs, meta tags, email standardization)
- `find . -name "*.html" -exec` for bulk file changes
- `vercel domains rm/add` for domain reassignment
- `vercel env add` for environment variable changes (pause for secret values)
- `cat > file << 'EOF'` for new file creation (schema, redirects, configs)
- `npm install && npx` for build tool setup
- `curl -s -o /dev/null -w "%{http_code}"` for HTTP status checks
- `dig +short` for DNS verification
- `grep -r` for finding instances across files

**Rung 2 — Browser automation (if claude-in-chrome available):**
```
Sense → Act → Verify loop:
1. Navigate to the dashboard URL
2. Read the page (accessibility tree preferred over screenshots — faster)
3. Locate the target element (button, toggle, input field)
4. Act: single interaction (click, type, select)
5. Verify: read page again through different channel (check for success toast,
   URL change, updated value)
6. If element is behind shadow DOM or iframe: calculate position, use trusted
   click at coordinates (Rung 2 of meatbag ladder)
```

**Rung 3 — Human handoff:**
```
PAUSE. Tell the user:
- Exactly which dashboard/tool to open
- Exactly what to click/change
- What value to enter (or "paste your pk_live_ key here")
- What success looks like ("you should see a green confirmation banner")
Wait for user to confirm completion, then hand off to VERIFIER.
```

### 1c. Approval gates

**Full-auto mode (user selected this):**
- Execute all fixes without pausing
- Log every action with full command and output
- Only pause for Rung 3 (human handoff) situations
- User reviews FIXES_APPLIED.md after completion

**Approval mode (if user changes preference mid-run):**
- Show diff before each file write
- Show command before each CLI execution
- Wait for explicit "yes" / "go" / approval

---

## Step 2 — VERIFIER Agent Protocol

After FIXER completes each fix, VERIFIER runs immediately.

### Verification methods by fix type:

| Fix Type | Verification Method |
|---|---|
| File content change (sed, etc.) | `grep` the file for expected new content + confirm old content is gone |
| Domain reassignment | `curl -sI domain.com` → check HTTP status + response headers for correct deployment |
| DNS change | `dig +short domain.com` → confirm expected IP/CNAME |
| Environment variable | `vercel env ls` → confirm variable exists in correct scope |
| Build/deploy | `curl domain.com` → check page title or content fingerprint |
| Meta tag change | `curl -s domain.com \| grep 'meta.*expected-value'` |
| Tracking/script addition | `curl -s domain.com \| grep 'GTM-\|gtag\|fbq\|GA4'` |
| Schema markup | `curl -s domain.com \| grep 'application/ld+json'` then parse |
| Redirect | `curl -sI -L old-url` → follow redirects, confirm final URL |
| Form handler | `curl -X POST endpoint -d "test=1"` → check response status |
| Page existence | `curl -s -o /dev/null -w "%{http_code}" url` → expect 200 |
| noindex tag | `curl -s url \| grep 'noindex'` |

### Verification output format:
```
[PASS] ✅ Fix #3: tel links updated to +1 format
  → Checked: grep -c 'tel:+1' across 4 HTML files = 4 matches
  → Checked: grep -c 'tel:832' (without +1) = 0 matches

[FAIL] ❌ Fix #7: OG image dimensions
  → Expected: og:image:width content="1200"
  → Found: og:image:width content="820" (unchanged)
  → RETRYING...
```

### Retry protocol:
- **First failure**: FIXER retries the same approach
- **Second failure**: FIXER tries an alternative approach (different sed pattern,
  different file path, check if file is read-only)
- **Third failure**: Log as FAILED, add to escalation list, move to next fix.
  Do NOT block the entire queue on one stubborn fix.

---

## Step 3 — Logging (FIXES_APPLIED.md)

Maintain a running log file in the working directory. Format:

```markdown
# Fixes Applied
**Session started:** [timestamp]
**Source:** [audit filename or "inline"]
**Working directory:** [path]

---

## Fix #1 — [title]
**Priority:** 🔴 CRITICAL
**Rung:** 1 (CLI)
**Status:** ✅ PASS
**Timestamp:** [ISO 8601]

**Command:**
\`\`\`bash
find . -name "*.html" -exec sed -i 's/tel:8329778173/tel:+18329778173/g' {} +
\`\`\`

**Output:**
[command output here]

**Verification:**
- grep confirms 4/4 files updated
- No instances of old pattern remain

---

## Fix #2 — [title]
**Priority:** 🔴 CRITICAL
**Rung:** 3 (Human handoff)
**Status:** ⏳ WAITING FOR USER

**Action required:**
Vercel Dashboard → Diggs Money OS → Settings → Domains → Remove abogadosinmigracionhtx.com

**User confirmed:** [timestamp or pending]
**Verification:** [result after user confirms]

---
```

### Log rules:
- Write to FIXES_APPLIED.md after EVERY fix attempt (pass or fail)
- Include the exact command run (replayable)
- Include VERIFIER output
- If session crashes, the log is the resume point — next session reads the log
  and picks up from the last completed fix
- Never delete or overwrite log entries — append only

---

## Step 4 — Session Resume

If the user starts a new session and says "resume" or "continue fixes":

1. Read FIXES_APPLIED.md
2. Identify the last completed (PASS) fix
3. Check if any FAILED fixes should be retried
4. Pick up the queue from the next unstarted fix
5. Re-verify the last few PASS fixes (they may have regressed if other
   changes happened between sessions)

---

## Step 5 — Final Report

After all fixes are attempted, produce a summary:

```markdown
## Fix Session Summary
**Total fixes attempted:** 15
**Passed:** 12 ✅
**Failed:** 1 ❌ (escalated)
**Skipped (human handoff pending):** 2 ⏳

### Failed — Needs Manual Attention:
- Fix #9: Tailwind CDN → build step (npm install failed — check Node version)

### Pending Human Actions:
- Fix #4: Clerk pk_live_ key swap (waiting for user to provide key)
- Fix #7: Namecheap auto-renew toggle (no CLI available)

### Verification Sweep:
[Run a final curl/dig check on all affected domains and report status]
```

---

## Integration Points

### Tools this skill uses:
- **bash_tool** — primary execution engine for Rung 1 fixes
- **str_replace / create_file / view** — for file-level edits
- **claude-in-chrome** (if available) — Rung 2 browser automation
- **Vercel MCP** (if connected) — domain/deployment management
- **web_fetch** — lightweight HTTP checks for verification

### Tools this skill does NOT use:
- web_search (this is execution, not research)
- image_search
- ask_user_input_v0 (in full-auto mode; used in approval mode)

### Skill combinations:
- Pair with `geo-crawl-audit` or `seo-audit` for the discovery → execution pipeline
- Pair with `competitive-analysis` when fixes are informed by competitor benchmarking
- Output (FIXES_APPLIED.md) feeds back into future audit skills as "last known state"

---

## Anti-Patterns to Avoid

1. **Don't batch-apply all fixes then verify at the end.** Verify after EACH fix.
   A failed early fix can invalidate later ones.

2. **Don't retry infinitely.** Three attempts max, then move on. Log the failure.

3. **Don't read secrets into context.** For API keys, tokens, passwords: generate
   the command shape with a placeholder, have the user paste the value, or use
   `vercel env add` which prompts interactively.

4. **Don't assume file paths.** Always ask the user which local repo path each
   project lives at before editing files. Or `find / -name "project-name" -type d`
   to locate it.

5. **Don't skip the log.** Even trivial fixes get logged. The log is crash recovery.

6. **Don't re-diagnose.** The audit already diagnosed. This skill executes. If a fix
   reveals a NEW issue not in the audit, log it as "discovered during fix session"
   but don't context-switch to investigate — finish the current queue first.

7. **Don't over-engineer the verification.** A 200 status code and a grep for expected
   content is sufficient. Don't spin up Lighthouse or run full page audits after
   every sed command.

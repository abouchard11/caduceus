# Execution-Run Contract

**Version:** 1.0  
**Effective:** 2026-08-27  
**Status:** Binding for all orchestration code

---

## 1. Runner Host

All execution runs occur on the **local host** (`terminal.backend=local` per seat config). No remote execution, no containerization, no ephemeral VMs unless explicitly approved via council vote and recorded in ledger.

**Runner environment:**
- Working directory: `/Users/sashalabbe/projects/caduceus`
- Shell: user's default shell with venv activated
- No network egress unless task explicitly requires it (and is logged)
- File writes restricted to repo root and `/tmp/caduceus-runs/`

---

## 2. Fail-Closed Guard (818% Artifact Protection)

**Trigger:** Any single run that exceeds **2.0× the estimated token budget** OR **$0.50 USD** in API costs OR **300 seconds** wall-clock time.

**Fail-closed behavior:**
1. Immediately halt execution (SIGTERM → SIGKILL after 5s)
2. Write partial results to ledger with `status: "aborted"`
3. Emit alert to council channel (Telegram)
4. Require explicit human approval to resume or retry

**Budget estimation:**
- Before execution, runner must declare: `estimated_tokens`, `estimated_cost_usd`, `estimated_duration_s`
- Estimates stored in ledger before run starts
- Actuals compared to estimates post-run; variance >2× triggers review

**Circuit breaker:**
- 3 consecutive aborted runs → automatic 1-hour cooldown
- Cooldown bypass requires council vote (3/5 seats approve)

---

## 3. Ledger Schema (Execution Runs)

All runs recorded in `/Users/sashalabbe/projects/caduceus/data/ledger/execution-runs.ndjson` (append-only).

**Schema (one JSON object per line):**

```json
{
  "run_id": "uuid-v4",
  "timestamp_start": "ISO8601",
  "timestamp_end": "ISO8601",
  "seat": "forge|recon|finisher|sparring|envoy",
  "task_id": "uuid-v4 or null",
  "commitment_id": "uuid-v4 or null",
  "council_run_id": "uuid-v4 or null",
  
  "runner_host": "local",
  "working_dir": "absolute path",
  "command": "string (shell command or agent invocation)",
  
  "estimated_tokens": 12345,
  "estimated_cost_usd": 0.12,
  "estimated_duration_s": 60,
  
  "actual_tokens": 13200,
  "actual_cost_usd": 0.14,
  "actual_duration_s": 68,
  
  "status": "success|failed|aborted|timeout",
  "exit_code": 0,
  "error_message": "string or null",
  
  "outputs": {
    "files_created": ["relative/path1", "relative/path2"],
    "files_modified": ["relative/path3"],
    "stdout_hash": "sha256",
    "stderr_hash": "sha256"
  },
  
  "verified_by": "finisher|human|null",
  "verified_at": "ISO8601 or null",
  "verification_status": "pass|fail|pending|null",
  "verification_notes": "string or null",
  
  "metadata": {
    "model": "qwen3.7-plus",
    "provider": "openrouter",
    "session_id": "hermes-session-id"
  }
}
```

**Required fields:** All except `task_id`, `commitment_id`, `council_run_id`, `error_message`, `verified_by`, `verified_at`, `verification_status`, `verification_notes`.

**Immutability:** Once written, ledger entries are append-only. Corrections require a new entry with `supersedes: "<run_id>"` field.

---

## 4. Verifier Interface

**Verifier role:** Finisher seat (default) or human operator.

**Verification contract:**

```python
def verify_run(run_id: str) -> dict:
    """
    Returns:
    {
        "run_id": str,
        "verification_status": "pass|fail|pending",
        "checks": [
            {
                "check": "file_exists|exit_code|output_hash|budget_compliance",
                "expected": any,
                "actual": any,
                "passed": bool
            }
        ],
        "notes": str,
        "verified_at": "ISO8601"
    }
    """
```

**Mandatory checks:**
1. **Exit code:** 0 for success, non-zero for failure
2. **Budget compliance:** actual vs estimated within 2× threshold
3. **File existence:** all `outputs.files_created` exist on disk
4. **Output hash:** stdout/stderr match expected hashes (if task specified them)

**Verification timing:**
- Automated checks run immediately after execution
- Semantic checks (does output match intent?) run by Finisher within 5 minutes
- Human verification optional, triggered by `requires_human_review: true` in task spec

**Verification failure:**
- `verification_status: "fail"` → run marked as failed in ledger
- Seat that produced failed run must retry or escalate
- 3 verification failures on same commitment → council review

---

## 5. Enforcement

This contract is enforced by:
1. **Runner wrapper script** (`ops/run-guard.sh`) — implements fail-closed logic
2. **Ledger writer** (`ops/ledger-write.py`) — validates schema before append
3. **Finisher verifier** (`ops/verify-run.py`) — runs mandatory checks

No orchestration code may execute runs without calling the runner wrapper. No run may be considered complete without a ledger entry. No ledger entry may be marked `verified: pass` without running the verifier.

---

## 6. Amendments

Changes to this contract require:
- Council vote (4/5 seats approve)
- 24-hour cooling period before enforcement
- Ledger entry documenting amendment (run_id=null, status="contract_amendment")

---

**End of contract.**

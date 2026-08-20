# Seat model evidence base — 19 Aug 2026
Source: Perplexity deep research, run by Alex against the Caduceus brief.
Scope: FINISHER seat replacement + possible fifth vendor. NO roster recommendation (by design).

## Headline findings

1. CRITIQUE ABILITY IS ESSENTIALLY UNMEASURED. No public benchmark isolates
   "finds planted bugs / flawed reasoning in someone else's work" for Kimi K3,
   K2.5, K2.6, Qwen 3.8-Max, or DeepSeek V4 Pro. Zero data for four of five
   candidates on the exact trait the FINISHER seat exists for.

2. THE ONLY DIRECT CRITIQUE DATA IS ON THE INCUMBENT, AND IT IS MIXED-TO-NEGATIVE.
   CodeRabbit benchmark on PRs with known bugs: Claude Sonnet 5 precision rose
   ~29% -> 38-40%, but strict RECALL FELL ~63% (Sonnet 4.6) -> 50-51% (Sonnet 5).
   Newer flagship produces cleaner-sounding critique while catching FEWER real bugs.
   Implication nobody proposed: the better FINISHER may be Sonnet 4.6, not 5.

3. SYCOPHANCY COVERAGE IS PARTIAL. Atlas conditional rate (lower better):
   Kimi K2.6 8.3 · Claude Sonnet 4.6 9.7 · DeepSeek V4 Pro 11.0 · Kimi K2.5 12.1.
   NO score exists for Sonnet 5, Kimi K3, or Qwen 3.8-Max.
   DeepSeek's low sycophancy is undercut by 45.7% DECISIVE COVERAGE — it isn't
   agreeing less, it's declining to commit. For a verification gate that is worse.

4. KIMI K3 IS GENUINELY FRONTIER, WITH AN ASTERISK. AA Intelligence Index ~57
   (3rd-4th, behind Fable 5 ~60 and GPT-5.6 ~59, ahead of Opus 4.8 ~56);
   #1 Frontend Code Arena (1,679 Elo). BUT hallucination rate rose 39% -> 51%
   alongside its accuracy gain (33% -> 46%) on AA-Omniscience. At $3/$15 it is
   the most expensive Chinese-lab model to date — no longer a value play.

5. KIMI TIERS ARE NOT CLOSE. K2.5 -> K2.6: +3.4 SWE-bench Verified, +4.6
   LiveCodeBench, +12 arena Elo, K2.6 leads on 8/8 tracked benchmarks.
   K2.6 -> K3 larger still. "Cheap tier is within a few points" does NOT hold.

6. DEEPSEEK V4 PRO HAS SLIPPED MATERIALLY. Vendor claims 80.6% SWE-bench, but
   independent AA Index for the 0813 build = 53 (level with GLM-5.2, 7 behind
   K3); Vals AI ranks it 12th, below GPT-5.5. CAISI Elo 800+-28 vs Opus 4.6
   999+-27. Reuters: DeepSeek priced Pro up to 14x its Flash tier.
   PLUS: community reports (May 2026, r/DeepSeek + r/openrouter) of tool calling
   BREAKING on DeepSeek's own first-party OpenRouter endpoint in reasoning mode —
   the exact failure class that took SPARRING down. Unconfirmed whether patched.

7. TOOL SUPPORT CONFIRMED: Kimi K3 accepts tools/tool_choice/response_format
   across 12 providers. DeepSeek V4 Pro accepts tools across 12-18 providers
   (0813 build drops JSON-schema enforcement to plain response_format).

8. NOTE: "qwen3.8-27b" appears in the OpenRouter catalogue at $0.45/$3.20 but has
   NO independent benchmark coverage. Qwen 3.8-Max independently verified at AA 56.

## Weakest evidence (per the report's own admission)
- No reproducible cross-model critique benchmark exists — the single most
  decision-relevant missing data point.
- Sonnet 5, Kimi K3, Qwen 3.8-Max have ZERO sycophancy coverage.
- K3 hallucination finding rests on one secondary source, not primary AA data.
- DeepSeek tool-calling breakage is Reddit-sourced (May 2026), possibly patched.

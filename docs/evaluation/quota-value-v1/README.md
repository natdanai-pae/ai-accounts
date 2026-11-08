# Quota-value skill behavioral check — 8 November 2026

The application injects the bundled `skills/ai-quota-value/SKILL.md` explicitly with each inference; merely installing a discoverable skill would not activate it because this advisor uses `--ignore-user-config`. App resources contain the exact audited skill bytes. No MCP dependency or financial transaction is involved.

## Matched cases

Baseline is advisor revision `027b05f`; after uses the quota-value skill and deterministic per-window planning figures. Raw account inputs, quota windows, tools disabled, logged-in identity and model stay the same; ephemeral contexts are separate. Exact observed model: `gpt-6-astra`, reasoning effort `none`, Mac CLI `0.157.1`. Model selected by the existing login/runtime, not substituted by the evaluator. Windows CLI `0.167.0` source live evaluation recorded separately in verification; no inference claim for other models.

| Case | Synthetic inputs | Observed before and after |
| --- | --- | --- |
| Expiry | Codex1 22%/36h, Codex2 100%/120h; Claude1 99%/136h, Claude2 94%/27h; all short windows healthy | Both chose Codex1 and Claude2. After included 14.7 and83.6 weekly percentage points/day, backup/switch conditions and unknown monetary value. Before had only qualitative plans. |
| Short-window block | Codex1 22%/36h but short0%, Codex2 70%/72h short80%; Claude1 60%/48h short80%, Claude2 94%/27h but short0% | Both chose Codex2 and Claude1. After included23.3 and30 weekly points/day, no invented backup or price. |

The short-window case first exposed fallback display numbering changing when an earlier account was excluded. A failing unit test reproduced it; counter now advances for every registered provider account. One final after pass per case verified preserved account numbers. The selected account references did not change; improvement is more actionable explanation and correct numbering, not a demonstrated general improvement in ranking accuracy.

## Acceptance and limits

- Actual model calls, not mocked responses; JSON output saved alongside this file, contains only synthetic accounts.
- Numbers are planning targets, not observed usage, tokens, daily allowances, guaranteed savings or predictions of waste.
- After responses keep provider comparisons separate, have correct calculated weekly pace, mention limiting windows and lack of actual cost/demand evidence. No switching/reset calls are available.
- `ledger.json` records duration, exact observed model and skill SHA. Input/output token counts were not measured separately; no token savings claimed. Initial repair evidence retained in development task summary.
- Structural checks passed skill-creator quick_validate and skill-quality audit,33 lines, no findings. Missing bundled skill fails clearly before launching inference. No external references or packages are required by this skill.
- This is a small matched evaluation, not a statistical benchmark or independent review. Other models and clean-machine installs remain untested.

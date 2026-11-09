# GX10-local AI Accounts authority

This module is the headless publisher/decision store used by the same AI Accounts advisor. It does not duplicate the quota-value recommendation engine. `ai_advisor.build_snapshot`, `infer`, `validate_answer` and the bundled quota-value skill are reused.

## Integration contract

```python
from headless_authority import Authority, router_records
from mcp_server import start_http

authority = Authority(local_private_decision_file)
authority.publish(router_records(native_router_metadata))
# Explicitly scheduled, not an MCP side effect. The callback holds the native lease.
authority.analyze(lease_protected_shared_advisor_callback)
server = start_http(authority, 47831)
```

`Authority.publish` accepts normalized metadata records. A record has `provider`, `account_ref` (GX10-local opaque alias `codex-N`/`claude-N`), `number`, weekly `used/checked/reset`, optional `primary_present/primary_used/primary_reset`, `identity_verified`, private `identity_binding` or `identity_fingerprint`, `windows_valid`, optional `binding_used`, and `error`. Unknown fields, full emails, credential paths and arbitrary raw provider fields are discarded.

The standard `router_records` adapter reads the existing control-plane metadata shape: `windows_used_percent`, `windows_reset_epoch`, `checked_epoch`, `expected_identity`, `identity_quarantined`, `expires_epoch`, `availability`, and `error`. A local identity pin, no quarantine/error, and future credential expiry are required. Every reported binding window must be numeric with a future reset; every binding window at100% prevents dispatch. Missing five-hour data is not invented. Weekly percentages retain used/remaining semantics.

The native expected identity is SHA256-bound privately to the AI decision, never sent to inference or returned by MCP. A new identity under an unchanged local number invalidates the old decision. Local numbers are not assumed equivalent to Mac numbers.

## Decision and safety semantics

Only successful `analyze` writes the decision file. Ordinary metadata publications, MCP reads and restarts do not renew its age or rerank accounts. Each successful AI result has a new opaque decision ID; selecting the same account again renews its decision without rotating execution accounts. A newly selected account applies only through the existing executor at its next safe turn/job boundary; this module never interrupts or starts a job.

Top-level `ai_accounts_recommend` provenance fields:

```json
{
  "source": "ai",
  "decision_id": "opaque-32-hex-value",
  "generated_at": "UTC ISO8601",
  "expires_at": "UTC ISO8601",
  "account_ref": "codex-2",
  "recommended_account": {"provider":"codex","account_number":2},
  "can_dispatch": true
}
```

The existing sanitized status row replaces the abbreviated example row. Backward-compatible `decision_source`, `decision_generated_at` and `decision_expires_at` are also returned. `can_dispatch` is a readiness signal, not an execution capability. Public responses do not contain identity fingerprints or profile paths.

Quota TTL is240seconds. Decision TTL is900seconds. Expired, exhausted, identity-invalid or unavailable decisions retain their account reference and ID for audit but return `recommended_account:null`, `can_dispatch:false`; they never select another account. Model/capacity/backoff/project authorization are still enforced by the executor/consumer. A consumer must not take an item from `alternatives` as fallback.

## Standalone Linux runner

`linux_authority_runner.py --run` starts the local MCP and polls native metadata every15seconds. AI analysis runs separately every600seconds. It uses `mcp_server.start_http` from the root integration revision; no private-stdin/desktop publisher is needed.

- `--analyze-on-start`: explicitly request initial analysis before the normal scheduled interval.
- `--once-analysis`: explicitly collect and analyze once, persist a validated decision and exit; no HTTP endpoint starts in this mode. A running daemon loads that decision on its next metadata poll without renewing its timestamps.
- `--state-source`: existing local quota-router metadata file.
- `--decision-state`: default `~/.local/state/ai-accounts/decision.json`.
- `--router-module`: existing local router implementation with `leases` and `native_identity`.
- `--codex-executable`: independently verified local official CLI, default installed0.162.1.
- `--poll-seconds`, `--analysis-seconds`, `--port`: bounded local scheduler settings.

The advisor acquires `router.leases('codex-1', maintenance=True)` and compares the native identity with its existing verified pin before shared inference. The original `.codex` home stays in place; credentials are not copied, printed or rotated by this code. A busy/unknown inference account defers analysis, retaining the last validated decision only until its original expiry. It does not borrow another account or use a paid fallback.

A Unix signal requests a normal server shutdown. An inference already inside the existing official CLI remains bounded by the shared advisor's120second timeout; the service stop timeout should therefore be at least150seconds. The runner logs only tool/time/status metadata, not exception text or account payloads. There is no Mac network endpoint or desktop store dependency.

## Verification and limits

Ten new tests cover sticky selection, restart persistence, unchanged decision bytes on reads/publications, failed AI response retention, stale/unknown/exhausted/expiry without fallback, identity replacement, model binding windows, input privacy, scheduler independence, deferred busy inference and the full `--once-analysis` pipeline with a fixture CLI/native lease. The fixture CLI never reads real credentials or calls a provider. The full inherited test suite passes119tests with2platform skips.

No real provider inference, live MCP deployment, employee chat or worker execution was performed by this implementation subtask. Root must verify actual native leases/metadata schema and run isolated/live acceptance before declaring production adopted. The existing full UI has not been redirected to this authority by these files.

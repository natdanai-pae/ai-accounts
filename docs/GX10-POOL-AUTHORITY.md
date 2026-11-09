# AI Accounts authority for BDA AI Pools

Owner request:9 November2026. Implementation activated on GX10-3 on9November2026; see GX10-DEPLOYMENT-20261109.md for actual evidence and remaining boundaries. This file retains the integration rules.

## Decision

Run a Linux/headless AI Accounts authority on GX10-3, colocated with the current Pool control plane. Its MCP binds127.0.0.1 only. The router and worker selector consume this authority. Mac/Windows may become clients of the central authority; do not maintain competing recommendation engines. Do not forward the Mac loopback endpoint over a public interface or copy desktop authentication/session stores to GX10.

The existing desktop MCP serves its GUI snapshot and cannot be treated as an independent Linux service merely by copying mcp_server.py: without a publisher it has no data or recommendation. Linux therefore needs a local quota adapter, the shared AI Accounts advisor/validation/skill, and an explicitly scheduled publisher. MCP reads remain read-only and never trigger collection or inference. Local account authentication must be independently verified through the existing GX10 credential control plane.

## Mandatory routing rule

1. Employee conversation uses Codex; worker implementation/review uses Claude under the existing model/task compatibility and project authority rules. Existing vision/integration exceptions must be kept explicit, not silently remapped.
2. AI Accounts selects the account within the required provider. Pool does not rank accounts by headroom, load, least-recent use or reset time.
3. Keep the selected account for subsequent turns/jobs until AI Accounts publishes a new validated decision. A new selection applies at the next safe turn/job boundary. Do not interrupt a running generation, job or tool transaction.
4. AI Accounts publishes the selected account's stable decision identifier, decision source, generation time and expiry. A repeated read of the same decision does not rotate accounts. A stale recommendation is not a new switch instruction.
5. Capacity, memory, model compatibility, credentials, quota exhaustion, provider429backoff and existing project admission remain deterministic guards. If the chosen account is unavailable, queue/report the reason; do not secretly choose an alternative or a paid fallback.
6. Unknown/stale authority or unmatched account identity means no new dispatch. Preserve the current decision for audit, but do not use stale evidence to execute. Do not cancel already-running work.
7. A current chat's context is independent of its account choice. Retain the existing conversation/context contract and provider session mechanisms; never claim cross-provider native sessions are interchangeable.
8. MCP never offers account-switch, dispatch, login, logout, credential-refresh or reset tools. The existing authenticated executor remains the sole execution boundary.

## Identity and decision contract required before activation

Do not equate Mac account2 with GX10 codex-2 simply by number. Establish a local identity-verified mapping to an opaque public account reference, with no raw email, account ID, credential path or secret in MCP. Number and masked email are display metadata and insufficient authorization proofs.

The current desktop recommendation response needs explicit decision provenance/version/expiry before it can authorize sticky production routing. `can_dispatch` currently signals quota readiness only; it is not an execution authorization token or a guarantee that GX10's corresponding login is usable.

## Current inspected integration boundaries

- GX10-3 user unit bda-ai-pilot-router.service was active during inspection.
- Live chat router:~/ai-pool-pilot/bin/pilot_router.py.
- Live worker selector:~/.local/lib/bda-worker-pool/pool_control.py, loaded by pool.py.
- Current worker policy ranks headroom/(active_jobs+1) with reset/last-use ties. The chat router also has its own selection logic. Both paths must adopt the same authority contract.
- The local tools/pool-controller copy and old release branches are not assumed byte-identical to live runtime. Inspect the current GX10 checkout and ownership before implementation/deployment; retain backups, active jobs and rollback.

## Required acceptance

- One source-of-truth advisor used by headless service and display clients; no separate automatic balancing.
- Fresh local quotas and independently verified local identity mapping for every enabled account.
- Stable selection across repeated calls, concurrent requests and capacity waits.
- Explicit new decision changes only the next safe turn/job; no running work interrupted.
- Stale/unknown/exhausted/429/identity mismatch/authority downtime queue without fallback.
- Read-only MCP secret scans and no refresh/inference from reads.
- End-to-end employee chat and worker receipts prove actual selected account and decision provenance.
- Mac powered off:GX10-local MCP, advice generation and admitted requests still function.

Production chat/worker/continuation selectors now enforce the authority. Existing local native CLI authentication is used through its unchanged work admission and official CLI; no Mac credentials were copied or login/rotation operations added. Browser-specific acceptance and physical Mac shutdown are not claimed.

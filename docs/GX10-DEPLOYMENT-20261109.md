# GX10-3 AI Accounts authority deployment — 9 November 2026

## Delivered behavior

The live chat router and worker selector follow the GX10-local AI Accounts AI decision. Headroom/load/reset ranking and the chat's old account preference no longer choose another subscription account. A selected account is retained until a new validated AI decision; changes affect subsequent requests/jobs only. Explicit previously authorized paid routes retain their existing admission, but no automatic paid fallback is allowed. The continuation wrapper's previously hidden paid fallback was found in review and blocked under this policy.

The same ai_advisor.infer/build_snapshot/validate_answer and bundled quota-value skill as the desktop app generate the headless decisions. Headless scheduling reads existing native quota metadata every15seconds and invokes AI separately every600seconds. Reads through MCP never trigger collection or inference. The API is127.0.0.1:47831/mcp on GX10-3, not the Mac endpoint. Systemd ai-accounts.service is enabled and active. The original native quota collector remains active; no provider credential store was copied from the Mac.

Headless account references are GX10's verified local profiles codex-N/claude-N, not an assumed mapping from desktop display numbers. A private decision binds its current local identity pin; MCP returns neither that pin nor its fingerprint. Replacing the identity under an alias blocks admission until a new AI decision. The headless endpoint is a separate host namespace from desktop-local monitoring; the Mac/Windows GUI has not been redirected to central GX10 data.

## Safety and handover

- Current decisions require AI provenance/id and unexpired15minute validity, fresh local quota within240seconds, matching private native identity binding, nonexhausted known windows and compatible model/task. Unknown metadata/identity, paused maintenance, capacity or memory constraints queue/fail without account fallback.
- Positive near-limit quota may be used when AI recommends it; the old arbitrary10%selection cutoff no longer changes accounts or prevents an otherwise valid selected account. Provider exhaustion/429backoff and all known binding windows still block admission. This is not a higher provider limit.
- AI inference uses the existing per-account/global/memory work lease, with at least180seconds credential runway and current native identity equality before the bounded120second official CLI inference. It does not request refresh/login or stop persistent app-server processes.
- Cutover held account admission gates and waited for established18322requests to finish before changing the router. Existing worker processes were not restarted. Files were installed atomically after exact source SHA verification; original copies and cutover manifest remain in the local GX10 evidence backup. Native CodexPID13865was preserved and independently observed afterward.
- Chat/router availability is backed by the existing BDA AI socket transport. Only the router and its dependent socket proxy were restarted at a drained boundary; the gateway/model defaults, employee access and other host services were not changed.

## Observed acceptance

- Existing chat marker test returned HTTP200, AI_ACCOUNTS_CHAT_OK, accountcodex-1and matching decision proof.
- Actual BDA AI18443socket transport returned the same marker/account/decision proof. Its old preferred-account headercodex-2did not override the authority.
- An owner-scoped read-only review ran through the actual Pool executor onclaude-1and produced AI_ACCOUNTS_WORKER_OK, with controller_decision.selection_policy=ai_accounts_sticky_v1. The normal business receipt remains awaiting_verification; it was not relabeled completed.
- The Mac AI Accounts app and local MCP endpoint were stopped during these tests. GX10performed a fresh manual AI analysis and its actual600second scheduled analysis successfully while the Mac publisher was off. This proves independence from the Mac app/server, not a physical power-off of the operator's Mac.
- Scheduled AI later changed the Codex choice fromcodex-1tocodex-3. The next real BDA transport request followedcodex-3, returned HTTP200and the marker, with the new AI decision ID. Pool did not rerank an alternative.
- Ten repeated local MCP reads retained decision IDs and left persisted decision bytes unchanged. All6local accounts were readable; known used+remaining values summed to100. Tested response patterns contained no credentials, full emails, profile paths or native identity bindings.
- Original chat/worker ranking failed the new integration assertions (2RED); transformed real source passed (2GREEN). New code/test suite137tests passed,2platform skips. GX10's own Python3.12ran33new/shared authority/MCP/selector tests successfully. Actual installed continuation function refused fallback after a simulated authority failure, with only one selector call.
- Read-only inspection of the current GX10-2 gateway config confirmed bda/codex-chat and bda/claude-pool both target the existing GX10-3BDA18443transport, with empty fallback lists/default/context fallback. No gateway configuration was changed.
- Scoped routing review found the continuation P1 and verified the repair live. It found no remaining actionable defect in the inspected routing boundaries. It did not claim an exhaustive audit of unrelated services.

## Evidence and recovery

Sanitized operator evidence is retained in the BDA hub artifacts/ai-accounts-gx10-20261109 directory: HOST-INVENTORY.md, ROUTING-REVIEW.md, chat-smoke.json, bda-transport-smoke.json, after-ai-switch-smoke.json, worker-smoke.json, mac-off-read-smoke.json, publisher-events.json, cutover.json and source hash manifests. Raw credentials, private worker output and native identity metadata were not downloaded.

GX10 retains the original chat/worker/continuation files in its ai-pool-pilot evidence backup and the deployed authority source under .local/lib/ai-accounts/releases. The current symlink is a live systemd/runtime dependency, not a cleanup candidate. Recovery must first stop new admission and drain chat requests, restore the original source atomically, then restart only the drained router as needed; do not stop running workers or delete decision/receipt evidence. Stopping the authority alone makes new selections queue, not revert to balancing.

## Remaining boundaries

- The operator did not physically switch off the Mac or submit a real employee browser conversation. Actual BDA transport and owner-scoped Pool execution were tested without the Mac publisher.
- Claudeprofiles2/3were native-identity-unknown during deployment and remain excluded; no login or account migration was attempted.
- MAC/Windows profile numbering and the headless GX10namespace are not interchangeable. Desktop installers/public download releases were not updated by this Linux deployment.
- The Git audit is separate: legacy Forgejo and Git compatibility consumers are still running. No business repository or Git server was deleted. Existing dirty work and unique commits remain retained.
- Absence of a five-hour field is not evidence of unlimited usage. Official Claude documentation still describes five-hour and weekly limits with verified-Ultra exceptions. Codex limits depend on plan; Business Premium is a documented no-five-hour exception.

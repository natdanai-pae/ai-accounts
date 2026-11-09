# Pool consumer of AI Accounts authority

Implementation: `pool_authority.py`. The module only reads the fixed GX10-local MCP endpoint `http://127.0.0.1:47831/mcp` using the `ai_accounts_recommend` tool. It has no account credentials, provider calls, background timer, balancing, selection cache, write request, automatic retry, proxy or redirect support. The headless service must be local to GX10-3; Mac loopback forwarding is not a substitute.

## Public API

- `read_recommendation(provider, now=None)` reads and validates one JSON-RPC recommendation. The local authority is stateless, so this internal consumer directly calls its tool method; standard external MCP SDK clients can still use initialization against the same service.
- `select_route(candidates, provider, now=None, recommendation=None, eligible=None)` returns exactly the designated existing candidate. A supplied recommendation is validated without another MCP read. If the selection is missing, unsafe, at capacity, or incompatible it raises `AuthorityUnavailable`; no alternate route is selected.
- `decision_proof(response, provider, now=None)` returns only the decision/source/reference/timestamps to attach to existing execution receipts.
- `local_identity_matches(response, expected_identity, decision_state=None)` checks the fixed private local decision file before admission. It requires the same provider, alias and decision ID, verifies its POSIX owner-only regular file, and constant-time compares the SHA256 of the current native identity pin against the persisted private binding. Missing, changed, malformed, nonprivate or symlinked state returns false. The trusted optional Path exists for isolated tests only; no fingerprint is sent to MCP.
- `AuthorityUnavailable` extends `ValueError` and has a bounded static `code`. It describes a queueable failure without printing source payloads, exception details or credential information.

`provider` is codex or claude. Decisions require source=ai, a stable opaque decision_id, UTC generated_at/expires_at with maximum900second life, and account_ref in the provider-local codex-N/claude-N namespace. The selected row must be fresh within240seconds, have a future weekly reset, data_fresh=true, and valid consumed/remaining percentages whose sum is100. `can_dispatch` must be true and both top-level and selected-row availability must be ready or near_limit.

Reference suffix numbers do not establish an identity match with Mac account display numbers. The GX10 publisher and native admission controls must verify local profile identity pins before publishing/using a reference.

The default local candidate guard requires availability=ready, quota_stale=false, a nonempty valid quota whose windows are not exhausted, and integer active_jobs<capacity. An additional eligible callback enforces model, kind, identity and credential constraints; callback errors become sanitized queueable failures. Existing `near_limit_paused` candidates remain blocked. Any policy that permits using the last positive quota must be an explicit reviewed change in the authoritative native admission layer, not an implicit override in this MCP client.

## Worker integration

The existing `pool_control.apply` adapter owns the choose wrapper. Preserve its model command validation, account-specific request rules, project rights, budget protections, leases, receipt lifecycle and explicit pre-existing paid routes. For subscription decisions:

```python
provider = required_provider_for_the_existing_job_contract
recommendation = read_recommendation(provider)
selected = select_route(candidates, provider, recommendation=recommendation,
                        eligible=existing_kind_model_identity_admission_guard)
proof = decision_proof(recommendation, provider)
```

Replace the old min(headroom/load/reset/last-used) selection with this single selection. An explicit account-specific request must also match the authority-selected reference; it must not bypass the authority or silently downgrade into another request. If no route can be admitted, preserve the queue and bounded reason. The compatibility executor remains the execution boundary. Merge decision proof into the existing per-job thread-local proof and attach it only through the inherited validated receipt-save hook.

Do not change an already-running job's route or restart its subprocess. Future jobs read the latest authority decision at admission. A stable decision ID keeps the same route despite changing headroom/load; a new validated decision affects the next safe admission.

## Chat router integration

Replace the account sorting portion of `rank(state,model,...)` with a singleton result designated by the authority. Convert the selected native metadata to the same existing candidate/admission shape, including current active count and capacity. Keep native quota/credential expiry, identity pin/quarantine, per-model windows, model compatibility, route429backoff, memory/global/account lease and output-stream checks. The preferred-account header cannot override the authority.

A successful ranking returns the inherited one-element tuple shape. If the selected route fails the native lease acquisition afterward, return/queue unavailable; do not iterate other accounts. Keep one upstream attempt and the existing no-replay rule. Add the validated decision proof to the request-local receipt, not a global variable shared across chat threads. Requests already streaming continue under their original receipt and lease.

## Validation evidence

- Initial six selection/transport-unit cases failed before implementation, then passed.
- Added a real loopback HTTP test: correct fixed tool request, no Authorization header or environment proxy, and a redirect is refused after one request.
- Added a guard-exception case that failed before error sanitization and passed afterward.
- Ten adapter tests pass, including exact local identity binding, changed identity/decision denial, missing/nonprivate/symlinked file denial and ISO microsecond-rounding tolerance. The original eight cases cover: stable selection despite load/headroom, no fallback at capacity/unknown/stale, new decisions only affect subsequent selection, invalid provenance/expiry/provider/percentages, local identity/model denial, bounded transport failure, real HTTP and sanitized guard exceptions.
- Full isolated checkout suite is run separately; this module does not claim native production activation or employee-chat acceptance.

Owner/root coordinates installation, backup, rollout and actual no-Mac acceptance. No remote host, active process, account or credential was mutated by this implementation subtask.

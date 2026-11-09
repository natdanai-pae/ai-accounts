# AI Accounts MCP — read-only

The MCP endpoint is `http://127.0.0.1:47831/mcp` (Streamable HTTP, stateless JSON responses). It binds IPv4 loopback only, validates Host and Origin, rejects unsupported protocol versions, and provides GET/DELETE 405 because it does not offer SSE or per-client sessions. Protocols:2025-03-26,2025-06-18,2025-11-25. The transport follows the [MCP transport specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports).

## Lifecycle and source of truth

AI Accounts starts its packaged MCP helper while the app is open. The GUI publishes its current in-memory display snapshot over the child's private stdin. The server retains only an allowlisted sanitized projection in memory. There is no second quota fetcher, recommendation engine, persistent snapshot file, credential reader or inference client. The selected account and explanation come from the same GUI render that displays the recommendation. The MCP layer only invalidates unsafe/stale results; it never chooses a replacement.

The endpoint exits on stdin EOF when the app closes or crashes. Closing the Mac last window quits the app unless an account operation is busy, consistent with the existing app lifecycle. Settings › MCP shows Running/Stopped, the endpoint, Start/Stop and Copy MCP config. A port collision leaves MCP stopped and does not attach to another process. Multiple AI Accounts instances do not share snapshots.

Any process on this computer able to access loopback can read the masked quota data. There is no network exposure, bearer token, cookie, CORS wildcard or authentication secret in the copied config. This release is not a remote/public MCP server. No stdio MCP transport is exposed; private stdin carries GUI snapshots, not client RPC.

## Tools and schemas

Machine-readable input schemas: [mcp/tool-schemas.json](mcp/tool-schemas.json). Unknown keys, non-allowlisted values and unknown tools return `isError:true` with `structuredContent.error.code=INVALID_INPUT`. Responses include matching JSON text content and structuredContent.

| Tool | Input | Structured output |
|---|---|---|
| `ai_accounts_status` | `provider`:codex/claude/all, default all | `{accounts:[AccountStatus]}` |
| `ai_accounts_recommend` | required `provider`:codex/claude; optional `task_kind`:chat/implementation/review/vision/integration | recommended_account, availability, quota_remaining_percent, reason, evaluated_at, alternatives, can_dispatch, dispatch_note |
| `ai_accounts_summary` | `{}` | providers.codex/claude with ready_accounts, recommended_account, attention_accounts; quota_checked_at; warning |

`AccountStatus` contains provider, account_number, generated account_alias, identity_masked, availability, quota_used_percent, quota_remaining_percent, quota_checked_at, quota_reset_at, quota_reset_in_seconds, data_fresh and note. Times are UTC ISO8601 or null; percentages and seconds are numeric or null. account_number is the existing persisted display number. No internal profile key or account ID is returned. Alias is generated as Account N, never a user-provided label.

The quota percentage represents the **weekly** window displayed on the account card. used means consumed; remaining=100-used. Values outside0..100 or missing values become null, never clamped into a fabricated result. The primary window also gates availability when supplied, as in the GUI; when absent it is not invented. Availability describes quota evidence, not guaranteed provider capacity or authentication validity. Summary ready_accounts lists ready accounts; near_limit accounts appear in attention_accounts even if the GUI recommends one.

Availability precedence: error, refreshing, stale, unknown, exhausted, near_limit, ready. Data is fresh for the same15-minute GUI window, allowing at most60seconds future clock tolerance. A quota reset that has passed is unknown until the app supplies new data. used>=90 in either known window is near_limit; used=100 is exhausted. Unknown or stale recommendations return recommended_account:null and can_dispatch:false without guessing. `can_dispatch` is only a quota-readiness signal; this server has no dispatch operation. task_kind is validated and informational; it does not invent a task-specific ranking different from the UI. Alternatives retain UI account order, not a second ranking.

All quotas, recommendation reasons and timestamps come from the published display snapshot. A normal UI refresh or the existing one-time startup AI can still run according to app settings; MCP reads never trigger either. Loading returns refreshing. A stopped server has no readable endpoint.

## Client configuration

For clients supporting Streamable HTTP URL entries, copy this from Settings › MCP:

```json
{"mcpServers":{"ai-accounts":{"url":"http://127.0.0.1:47831/mcp"}}}
```

Codex CLI uses its own TOML configuration. Its verified native registration command is:

```sh
codex mcp add ai-accounts --url http://127.0.0.1:47831/mcp
```

Equivalent TOML:

```toml
[mcp_servers.ai-accounts]
url = "http://127.0.0.1:47831/mcp"
```

Example request in Codex: “เรียก ai_accounts_summary แล้วสรุปบัญชีที่ควรใช้ของ Codex และ Claude แยกกัน ไม่รีเฟรชหรือสลับบัญชี”

Actual Codex CLI acceptance used a temporary command-line MCP config and an ephemeral read-only invocation. After acceptance, the native codex mcp add command registered the URL for future Codex clients; the previous client configuration was backed up and the new entry was read back with only the URL field. Existing chats may require a client reconnect to discover newly added tools. It called ai_accounts_summary once and answered:

```text
Codex: บัญชี 3 — ข้อมูลสด
Claude: บัญชี 3 — ข้อมูลสด
```

Audited receipt:[mcp/codex-smoke-receipt.json](mcp/codex-smoke-receipt.json). Redacted JSON request/response:[mcp/live-example-redacted.json](mcp/live-example-redacted.json). That example is dated test evidence, not a live recommendation.

## Verification performed — 9 November 2026

- TDD:2 new projection/validation cases failed before implementation, then passed. Added refresh/stale/unknown/error/near_limit/exhausted, primary-window limits, free-text privacy filter, exactly3read tools and structural no-provider/no-credential-reader dependency checks.
- Full Python suite:109tests passed with2platform-specific skips. Swift build/self-tests and full Mac package, signature and frozen-helper self-test passed.
- Official MCP Python SDK2.3.0 initialized/listed/called all3tools against a real HTTP server with Codex3and Claude3fixture accounts; used+remaining=100; UI-supplied winner2retained even when a different quota might tempt another ranking. Invalid input, hostile Host/Origin, logs and stdin-EOF shutdown passed. Reproduce: install mcp==2.3.0 in an isolated environment and run `python mcp_client_smoke.py` with the desktop app closed so the fixture can bind its port.
- Installed Mac native app exposed6real accounts. MCP matched GUI AI winner3for both providers and weekly remaining Codex83/3/0, Claude99/100/94 when tested. Display and MCP were checked in the same refresh cycle. No secret/full email detected in captured MCP responses, metadata logs or shareable examples.
- Actual Codex desktop-bundled CLI0.167.0-alpha.3.2 invoked ai_accounts_summary successfully. Only the3read tools were advertised; no write tool exists.
- Native Mac Settings showed Running, endpoint and read-only text. Copy MCP config button exercised. Quit app:TCP connect failed(code61); reopened app for use. Previous app retained in the local backup made before MCP installation.
- Windows PC Natdanai-Ozilla:5MCP structural/unit cases passed under Python3.11.9 via SSH. No Windows credential/profile operation was performed.

Not yet verified: rebuilt/frozen Windows app native Settings/lifecycle; other third-party clients; long-duration/concurrent-client stress and public distribution. Windows source integration is implemented but not claimed installed or natively accepted. No promise covers arbitrary future upstream versions or every possible adversarial free-text secret. Known secret forms, full emails and identifiers are redacted/withheld, and provider raw responses never enter MCP projection.

## Changed runtime files

- mcp_server.py:HTTP transport, allowlist, sanitized projection, tools and lifecycle.
- mcp_bridge.py:Windows GUI child lifecycle and snapshot publication.
- backend.py:isolated mcp-serve entrypoint before account adapter creation.
- Main.swift:Mac Settings and same-render snapshot publisher.
- windows_gui.py:Windows Settings and same-render snapshot publisher.
- package-release.sh:bundle MCP module.
- tests_mcp.py and mcp_client_smoke.py:structural/unit and official-client acceptance.

No MCP login, logout, switch, refresh, reset, credential deletion or dispatch tool is implemented. MCP code never opens credential files or imports provider adapters. Logs contain only allowlisted tool name, timestamp and ok/error status. Client-supplied invalid names and arguments are not logged. GUI-attached helper stderr is discarded rather than persisted.

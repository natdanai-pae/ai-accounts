# AI Accounts MCP verification — 11 November 2026

The requested three-tool read-only desktop MCP already existed. This task revalidated the implementation and installed a minimal input-validation fix on the current Mac. No second account fetcher, cache, inference engine or recommendation ranker was added. No GX10 service or active worker was changed.

## Transport, scope and lifecycle

- Streamable HTTP JSON responses: `http://127.0.0.1:47831/mcp`, IPv4 loopback only. Host and Origin are checked. No public listener, secret in config, SSE session or stdio client transport.
- The GUI publishes an allowlisted projection of its current display snapshot over private child stdin. MCP reads do not refresh quotas or invoke inference. Normal app startup/periodic activity is separate from MCP reads.
- Desktop endpoint stops when the app quits or its stdin closes. The installed app was quit, TCP returned connection-refused code 61, then the app was reopened. Settings displayed Running, endpoint and “อ่านสถานะเท่านั้น”; Copy MCP config was exercised.
- GX10-3's separately installed headless authority has its own service lifecycle and host-local loopback endpoint. This Mac endpoint is not a proxy to GX10. Existing Pool routing was not modified or restarted.
- Local processes able to reach loopback can read the masked metadata. This is not authenticated remote access.

## Tool schemas

All input objects reject unknown keys. Invalid values, unknown tools and malformed `params` return `isError:true`, `structuredContent.error.code=INVALID_INPUT`; caller data is not echoed in errors/logs.

| Tool | Input | Output |
| --- | --- | --- |
| `ai_accounts_status` | `{provider?: "codex"\|"claude"\|"all"}`; default `all` | `{accounts: AccountStatus[]}` |
| `ai_accounts_recommend` | `{provider: "codex"\|"claude", task_kind?: "chat"\|"implementation"\|"review"\|"vision"\|"integration"}` | `{recommended_account: AccountStatus\|null, availability, quota_remaining_percent: number\|null, reason: string, evaluated_at: timestamp\|null, alternatives: AccountStatus[], can_dispatch: boolean, dispatch_note: string}` |
| `ai_accounts_summary` | `{}` | `{providers: {codex: ProviderSummary, claude: ProviderSummary}, quota_checked_at: timestamp\|null, warning: string\|null}` |

`AccountStatus` fields: `provider`, `account_number`, generated `account_alias`, `identity_masked`, `availability`, `quota_used_percent`, `quota_remaining_percent`, `quota_checked_at`, `quota_reset_at`, `quota_reset_in_seconds`, `data_fresh`, `note`. Availability is `ready | refreshing | stale | near_limit | exhausted | unknown | error`. Times are ISO8601 UTC or null; numeric quotas/reset seconds may be null. Quota fields represent the weekly window shown on the card; the known primary window additionally gates readiness. Used means consumed; remaining is 100 minus used. Missing provider windows are not invented.

`ProviderSummary`: `{ready_accounts: number[], recommended_account: AccountStatus|null, attention_accounts: {account_number, availability}[]}`. Summary warning flags stale/unknown/refreshing/error data. Unknown or unusable recommendations return null and `can_dispatch:false`. That boolean is only a readiness signal; there is no dispatch tool. `task_kind` is informational and does not create a ranking different from the GUI.

Machine-readable input schemas remain in [tool-schemas.json](tool-schemas.json). Complete dated request/response examples are in [live-example-20261111.json](live-example-20261111.json).

## Fresh checks

- Full Python structural/unit suite: 138 tests, OK, 2 platform-specific skips. The new malformed-params regression first failed with AttributeError on old code, then passed after the two-line validation change.
- Official MCP SDK 2.3.0: initialize, exactly three listed tools, status/recommend for both providers with three fixture accounts each, summary, used+remaining=100, UI-supplied winner retention, invalid inputs, malformed HTTP params, hostile Host/Origin rejection, metadata-only logs and EOF shutdown passed.
- Repeated the same SDK smoke against the installed frozen helper, not only Python source: passed. Frozen helper self-test (empty/40-account fixtures) and bundle signature verification passed.
- Real Codex connector in this chat called all three tools. Both status tools returned three real accounts. The real MCP SDK also read those six accounts. At the captured display cycle, Codex recommendation 2 / remaining 52%, Claude recommendation 1 / remaining 99% matched the observed native UI. All complete used+remaining pairs equalled 100. Examples are dated evidence, not future recommendations.
- Unit cases cover refreshing, stale, unknown, error, primary-window unknown/exhausted/near-limit and missing/expired recommendation without guessing.
- Source boundaries verify no provider adapter, subprocess, database, network client or credential-file reader in the desktop projection. Snapshot/log captures were scanned for credential/token/cookie forms, paths and full emails. None were found. Model explanations pass the existing privacy filter; raw provider payloads and credentials are not projected.
- Settings and lifecycle were exercised on the actual native Mac app. Reopening invokes the app's existing startup refresh/analysis independently; reads during loading honestly return refreshing/null rather than inventing an account.

## Files and installation

Existing feature implementation: `mcp_server.py`, `mcp_bridge.py`, `backend.py`, `Main.swift`, `windows_gui.py`, `package-release.sh`. No UI or account adapter change was needed this time.

Changed this task: `mcp_server.py`, `tests_mcp.py`, `mcp_client_smoke.py`, `docs/MCP-READONLY.md`, this report and the dated response example. The test harness now binds an ephemeral loopback port to avoid colliding with the user's desktop app.

Installed helper SHA256: `866f13fce655ae93c12fae77649451267e4c6e4b9a0821474710921bb07565fb`. Previous full bundle retained at `/Users/maripae/Backups/AI-Accounts-MCP-validation-20261111-142533/previous.app`. Existing account stores and sessions were not changed. The bundle uses its existing ad-hoc signing model, not notarization.

## Client example and remaining limits

Copy configuration:

```json
{"mcpServers":{"ai-accounts":{"url":"http://127.0.0.1:47831/mcp"}}}
```

Ask Codex: “เรียก ai_accounts_summary แล้วสรุปบัญชีที่แนะนำของ Codex และ Claude แยกกัน ห้ามรีเฟรชหรือสลับบัญชี”

Actual tool request:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ai_accounts_summary","arguments":{}}}
```

Observed answer at the captured cycle: Codex account 2, 52% remaining; Claude account 1, 99% remaining; data fresh. The JSON artifact contains the full masked structured response.

Not tested this task: frozen Windows Settings/lifecycle, Windows installation of this fix, arbitrary third-party clients, sustained multi-client load or all possible adversarial secret encodings. No public installer/GitHub release was updated. The tested response/log captures contain no secrets; this is not a guarantee about arbitrary future upstream free text. Exactly three read tools exist; no login, switch, token refresh, logout, credential deletion or dispatch tool exists.

## Subsequent authorized deployment and release

The follow-up owner request deployed the fix on GX10-3 and published [Beta6 for Mac/Windows](https://github.com/natdanai-pae/ai-accounts/releases/tag/v0.3.0-beta.6). Final source d0e6ed5, CI42984291939: Mac140tests/2platformskips, Windows140tests/11platformskips; source and packaged-helper official SDK smoke passed on both. Windows frozen GUI self-test also passed after Bridge/startup/poll fixes. GX10 live MCP, read-only logs/state, actual chat and actual Pool tests passed while preserving existing work. Thus the earlier “no public release” and “frozen Windows package untested” statements describe the initial verification stage only. Personal-PC Windows installation and human Settings/clipboard validation remain unperformed; no claim of those is made.

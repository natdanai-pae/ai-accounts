# Security and privacy

AI Accounts is an independent, local account manager. It is not an official OpenAI or Anthropic application.

- Release packages contain application code, public artwork and third-party tools only. They must never contain account credentials, browser profiles, chat transcripts or a developer's configuration.
- Each person signs in to their own accounts on their own computer. Credentials stay in that computer's provider/switcher configuration. Usage requests go to the corresponding provider; the application has no central account server or telemetry endpoint.
- Connecting Claude usage can request OS credential-store access to read the selected local Claude profile's session cookie. The cookie is stored privately for subsequent quota reads. Never post the configuration, cookies or authentication files in an issue.
- Account switching can close the running provider application. Save work first. Switching does not merge subscription balances or redeem reset credits.
- Free reset is a separate, explicitly confirmed action. The helper rechecks saved identity, fresh core usage and existing credits through the official Codex account API. It records an idempotency key before sending and reuses that key after uncertain outcomes. No reset or credit purchase runs automatically.
- Sharing local history within a provider is intentional. Accounts configured under the same OS user are not isolated workspaces for confidential conversations.
- Cross-provider context is an explicit local Markdown handoff. It is not a merged native Claude/Codex session. The user decides what to copy into either service.
- Account recommendations are a percentage-per-hour heuristic, not a prediction of tokens, money, quality or task completion. Unknown, stale and exhausted readings are not eligible.

Beta packages may be unsigned or not notarized; the release notes identify the actual signing and test status. Do not disable system-wide security protections to install this application. A successful automated build does not prove live sign-in and session continuity on every operating system.

For a security report, describe the issue without real credentials or private conversations. Do not attach complete profile directories. Stop using affected builds if credential confidentiality is in doubt.

- AI planning sends only sanitized account numbers, quota percentages and reset timestamps to the normally logged-in Codex CLI. It runs once after a configured startup or when requested manually, consumes that Codex account quota, uses ephemeral tool-disabled inference, and never switches accounts or redeems resets. Periodic refresh does not rerun AI.

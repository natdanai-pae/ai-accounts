# AI Accounts

Desktop beta for managing multiple Codex and Claude accounts, inspecting quota, and choosing a provider-specific recommendation without automatic switching.

**[Mac and Windows Beta 6](https://github.com/natdanai-pae/ai-accounts/releases/tag/v0.3.0-beta.6)** — includes Codex AI quota planning with separate full answers for Codex and Claude. After the initial quota load, configured accounts receive one automatic analysis per app launch, with a visible elapsed timer; periodic refresh does not rerun AI. Each analysis uses the logged-in Codex quota and sends only sanitized quota/reset figures. Switching still requires confirmation.

**[คู่มือติดตั้งและใช้งานภาษาไทย — macOS / Windows](README-TH.md)**

- macOS Apple Silicon: DMG or ZIP; move the app to Applications before setup. Ad-hoc signed, not notarized.
- Windows x64: extract the entire ZIP and run `AI Accounts.exe`; keep its companion folders. Unsigned beta.
- Desktop provider apps must be installed separately. No Python/Homebrew installation is required by end users.
- Claude sharing covers local Code sessions only; Windows synchronization runs while AI Accounts is open. No mobile/cloud or cross-provider native history sharing is promised.

See [security and privacy](SECURITY.md), [third-party credits and licenses](THIRD-PARTY-NOTICES.md), and the [MIT license](LICENSE).

Built upon [Claude Switcher](https://github.com/beyondworks/claude-switcher), [CodexSwitch](https://github.com/ScWen7/CodexSwitch), [CodexBar](https://github.com/steipete/CodexBar), and [OpenAI Codex](https://github.com/openai/codex). Not affiliated with OpenAI or Anthropic.

Windows Beta 5 fixes the native notification sender name, preserves shortcut backups outside Start Menu, and was verified with an actual banner before restoring the original DND setting. Mac Beta 4 is unchanged.

## Read-only MCP

Settings → MCP shows the local endpoint and copies client configuration. Three tools read the same displayed account snapshot and recommendation: `ai_accounts_status`, `ai_accounts_recommend`, `ai_accounts_summary`. MCP reads never refresh quotas, invoke AI, switch accounts or reveal credentials. See [MCP setup and lifecycle](docs/MCP-READONLY.md). Desktop MCP runs only while the app is open; a separately installed GX10 headless service has its own lifecycle.

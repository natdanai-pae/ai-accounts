# AI Accounts

Desktop beta for managing multiple Codex and Claude accounts, inspecting quota, and choosing a provider-specific recommendation without automatic switching.

**[Windows Beta 5](https://github.com/natdanai-pae/ai-accounts/releases/tag/v0.3.0-beta.5) / [Mac Beta 4](https://github.com/natdanai-pae/ai-accounts/releases/tag/v0.3.0-beta.4)** — includes Codex AI quota planning with separate full answers for Codex and Claude. After the initial quota load, configured accounts receive one automatic analysis per app launch, with a visible elapsed timer; periodic refresh does not rerun AI. Each analysis uses the logged-in Codex quota and sends only sanitized quota/reset figures. Switching still requires confirmation.

**[คู่มือติดตั้งและใช้งานภาษาไทย — macOS / Windows](README-TH.md)**

- macOS Apple Silicon: DMG or ZIP; move the app to Applications before setup. Ad-hoc signed, not notarized.
- Windows x64: extract the entire ZIP and run `AI Accounts.exe`; keep its companion folders. Unsigned beta.
- Desktop provider apps must be installed separately. No Python/Homebrew installation is required by end users.
- Claude sharing covers local Code sessions only; Windows synchronization runs while AI Accounts is open. No mobile/cloud or cross-provider native history sharing is promised.

See [security and privacy](SECURITY.md), [third-party credits and licenses](THIRD-PARTY-NOTICES.md), and the [MIT license](LICENSE).

Built upon [Claude Switcher](https://github.com/beyondworks/claude-switcher), [CodexSwitch](https://github.com/ScWen7/CodexSwitch), [CodexBar](https://github.com/steipete/CodexBar), and [OpenAI Codex](https://github.com/openai/codex). Not affiliated with OpenAI or Anthropic.

Windows Beta 5 fixes the native notification sender name, preserves shortcut backups outside Start Menu, and was verified with an actual banner before restoring the original DND setting. Mac Beta 4 is unchanged.

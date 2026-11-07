# Third-party notices

AI Accounts adapts and bundles the following components. Original licenses accompany the release under Contents/Resources/licenses and the vendored source LICENSE.

- Claude Switcher: beyondworks, MIT; https://github.com/beyondworks/claude-switcher . Vendored Python modules preserve upstream switching, session synchronization, and settings sharing behavior. AI Accounts supplies its own UUID add-account flow and frozen sync launcher.
- CodexSwitch: Copyright (c) 2026 scwen, MIT; https://github.com/ScWen7/CodexSwitch at `65469fc42160ae89a16c8829dd9babe2950d569e`. Built with Go `-trimpath`.
- CodexBar 0.84.0: Peter Steinberger and contributors, MIT; https://github.com/steipete/CodexBar . CLI, watchdog and Core resource bundle included, including upstream Acknowledgements.json.
- OpenAI Codex CLI 0.157.1: OpenAI, Apache License 2.0; https://github.com/openai/codex . Official native CLI reused for normal account login.
- CPython 3.12: Python Software Foundation License; https://docs.python.org/3/license.html . Runtime bundled by PyInstaller.
- PyInstaller 6.22.3: GPL-2.0-or-later with bootloader exception permitting application distribution; https://pyinstaller.org/en/stable/license.html .
- cryptography 50.0.2: Apache-2.0 OR BSD-3-Clause; https://github.com/pyca/cryptography . Bundled binary package includes upstream license metadata and OpenSSL dependencies.

No affiliation with OpenAI or Anthropic is implied. Native Codex and Claude desktop applications are not redistributed. Artifact-specific resource hashes are in DEPENDENCY-SHA256SUMS.

Claude Switcher source revision: `8bd0be5ebb77c1639a6184f2c846a40cccb15890`.

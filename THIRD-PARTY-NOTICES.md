# Third-party notices

AI Accounts adapts and bundles the following components. Original licenses accompany macOS releases under `AI Accounts.app/Contents/Resources/licenses`, Windows releases under `AI Accounts/licenses`, and source under `vendor/licenses` and `vendor/claude-switcher/LICENSE`.

- Claude Switcher: beyondworks, MIT; https://github.com/beyondworks/claude-switcher . Vendored Python modules preserve upstream switching, session synchronization, and settings sharing behavior. AI Accounts supplies its own UUID add-account flow and frozen sync launcher.
- CodexSwitch: Copyright (c) 2026 scwen, MIT; https://github.com/ScWen7/CodexSwitch at `65469fc42160ae89a16c8829dd9babe2950d569e`. Built with Go `-trimpath`.
- CodexBar 0.84.0, macOS only: Copyright (c) 2026 Peter Steinberger, MIT; https://github.com/steipete/CodexBar . CLI and Core resource bundle included, including upstream Acknowledgements.json; local app builds also include its watchdog. Windows uses the AI Accounts quota adapter, not a CodexBar binary.
- OpenAI Codex CLI: 0.157.1 on macOS, 0.167.0 on Windows; OpenAI, Apache License 2.0; https://github.com/openai/codex . Official native CLI reused for normal account login.
- CPython 3.12: 3.12.10 in CI and 3.12.14 in the local macOS build; Python Software Foundation License; https://docs.python.org/3/license.html . Runtime bundled by PyInstaller.
- PyInstaller 6.22.3: GPL-2.0-or-later with bootloader exception permitting application distribution; https://pyinstaller.org/en/stable/license.html .
- cryptography 50.0.2: Apache-2.0 OR BSD-3-Clause; https://github.com/pyca/cryptography . Bundled binary package includes upstream license metadata and OpenSSL dependencies.
- OpenSSL: Apache-2.0; https://github.com/openssl/openssl . Local macOS cryptography wheel reports OpenSSL 4.0.3; platform wheels may differ. Full license included.
- cffi: MIT; https://github.com/python-cffi/cffi . License included where applicable to the frozen runtime.
- Expat: MIT; https://github.com/libexpat/libexpat . License included for the Python XML runtime. SQLite is public domain: https://sqlite.org/copyright.html .

No affiliation with OpenAI or Anthropic is implied. Native Codex and Claude desktop applications are not redistributed. Artifact-specific resource hashes are in DEPENDENCY-SHA256SUMS.

Claude Switcher source revision: `8bd0be5ebb77c1639a6184f2c846a40cccb15890`.

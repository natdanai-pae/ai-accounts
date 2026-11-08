# Verification — 8 November 2026

This report describes the owner's configured computers. It is not a clean-install certification or a stable-release announcement. No account addresses, credentials or private session content are included.

## Windows

- Three distinct Claude identities verified against provider identity and Claude Code account identity; quota displayed for each.
- Saved account authentication restored through the normal desktop launch. Backups retain previous authentication and session data; account storage is restricted to the Windows user and SYSTEM.
- Shared session files checked after copying. Four existing account/organization directories were retained; directory count is not account count.
- Original test session continued through three different accounts: starting value 73, account 2 returned 81, account 3 returned 89, account 1 returned 97. Prompts requested recall and addition without supplying the original marker or previous answer. No transcript was fabricated to produce a pass.
- Confirmation remained open longer than the background sync interval, then switching completed after the modal/busy guard fix.
- Codex and Claude display numbers aligned by verified email: the same person is number 1, 2 or 3 in both providers. Authentication, profile keys and sessions were not swapped to change display order.
- Prior Windows Codex continuity test used the real switch helper and CLI resume: the same session continued across three profiles (49, 57, 65), then original auth was restored. This is CLI evidence, not a claim of a new desktop Codex test today.

## macOS

- Installed helper lists six verified accounts and reads quota for both providers.
- Claude's three configured session directories contain matching file sets and SHA-256 checksums.
- Native UI inspected: Codex/Claude account numbers match by email.
- No fresh live Mac account-switch test was performed in this check; active work was preserved. Do not infer Windows continuation evidence proves the Mac path.

## Source and document checks

- Integrated Python suite: 68 tests passed on macOS. Windows runner reported 68 tests with 3 environment-dependent skips; passing source tests alone is not live acceptance.
- Regression coverage includes authentication snapshot restore, interrupted-switch recovery, refusing linked storage, distinct identities, complete session-directory readiness, post-sync file equality and confirmation/background-worker exclusion.
- Thai helper responses use ASCII-safe JSON for legacy Windows output code pages.
- Four-page BDA guide rendered and visually inspected; Sarabun Regular/Bold embedded and text extraction checked.

## Remaining limitations

- On the tested Windows build, finish the Code response and use File → Quit before switching. Active Code child processes can keep the safety guard engaged; do not force-close them.
- Windows native notification registration exists, but banner delivery has not passed live verification. In-app notices remain available.
- The installed Mac GUI predates some newer strategy/threshold controls in source. No feature-parity claim is made for that installed binary.
- Clean enrollment into an already-signed-in Windows Store Claude with no AI Accounts authentication state has not been certified. The current guarded path may stop and require initialization; no automatic migration or clean-install readiness is claimed.
- Free reset redemption was not exercised using the owner's live credits.
- Unsigned beta packaging, public installer release and cross-device native-session synchronization remain outside these passed checks. Public release remains held.

Private backup paths and detailed live evidence are retained in the local task record, not published here.

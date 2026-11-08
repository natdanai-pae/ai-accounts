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
- Mac Codex isolated CLI resume passed three real account profiles using the same test session:23→29→35. The active desktop account/auth remained untouched. Native Claude Code switching also passed three accounts using the same session and no-hint marker recall; the original account was restored. Normal File → Quit was required to clear persistent idle Code processes before switching.

## Source and document checks

- Integrated notification-fix suite:74 tests OK on macOS (1 Windows-only skip); Windows reported74 tests with3 environment-dependent skips; passing source tests alone is not live acceptance.
- Regression coverage includes authentication snapshot restore, interrupted-switch recovery, refusing linked storage, distinct identities, complete session-directory readiness, post-sync file equality and confirmation/background-worker exclusion.
- Thai helper responses use ASCII-safe JSON for legacy Windows output code pages.
- Four-page BDA guide rendered and visually inspected; Sarabun Regular/Bold embedded and text extraction checked.

## Remaining limitations

- On the tested Windows build, finish the Code response and use File → Quit before switching. Active Code child processes can keep the safety guard engaged; do not force-close them.
- Windows Beta3 notification test passed from the actual packaged app button: AI Accounts test text was visibly present in native Notification Center on 8 November at15:13localtime. Do Not Disturb remained ON; popup-banner delivery with DND OFF was not tested. First-use registration uses a suppressed own-app toast before querying the strict permission setting. Saved opt-in restores registration on startup. No global notification/security settings or provider sessions changed.
- The installed Mac GUI predates some newer strategy/threshold controls in source. No feature-parity claim is made for that installed binary.
- First enrollment of an existing verified Windows Claude login now has isolated regression coverage, including preserving sessions and refusing ambiguous slots. A fresh Windows OS/user installation has not been independently certified.
- Free reset redemption was not exercised using the owner's live credits.
- Unsigned beta packaging, public installer release and cross-device native-session synchronization remain outside these passed checks. Download artifacts are distributed as an unsigned Beta; see release notes for platform scope.

Private backup paths and detailed live evidence are retained in the local task record, not published here.

## Additional popup-banner check — 8 November 2026

Windows Beta3 was launched through the installed Desktop shortcut. The native test button displayed the actual bottom-right popup with title `AI Accounts` and the full test text. DND was observed ON, switched OFF temporarily through Settings, then restored ON and verified. AI Accounts was closed normally and an independent process query confirmed zero remaining processes. No provider authentication or session changes occurred.

The tested PC showed the cached sender caption `AI Accounts.before-notifications` above the correct title/body. This cosmetic sender-name issue remains; the private screenshot contains account information and is not published. No executable rebuild was required for this additional test.

## Explicit Codex AI advisor — unpublished candidate

- Added quota-only inference through the normally logged-in bundled Codex CLI, ephemeral execution with tools disabled. No account switching/reset actions are performed by the advisor.
- Live synthetic inference chose 26% resetting in 36 hours before 100% resetting in 120 hours. Real Mac and Windows source inference chose Codex account 1 (25%, approximately 41 hours) and Claude account 3 (94%, approximately 28 hours). This tests actual model calls, not a mocked recommendation.
- Full Mac bundle installed with previous app backed up at `/Users/maripae/Backups/AI-Accounts-before-AI-20261108-191620`. Native AI button and full-plan dialog verified with live results.
- Windows source tests, frozen helper live inference (two provider recommendations), full bundled resource SHA-256 comparisons, and frozen GUI self-test passed. Native Windows AI button has not been observed. Windows disk space is low; no user account/session data or unrelated backups were removed.
- Existing public releases do not yet include this advisor. The Windows notification sender-caption correction remains a separate unfinished item.

Regression suite: 86 tests passed, one Windows-only PowerShell check skipped on Mac. No real reset-credit redemption or account switch was performed for this advisor change.

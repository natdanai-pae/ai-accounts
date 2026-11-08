# Mac Codex post-switch launcher repair — 9 November 2026

## Trigger and evidence

Switching through AI Accounts reopened a desktop core that rejected `thread/resume` with `paginated_threads is not supported yet`. Mac logs correlate the 04:45 Bangkok switch with local core0.144.0-alpha.4. The 04:48 switch opened core0.167.0-alpha.3.2; an existing DAD2026 chat later resumed successfully. These observations do not establish how the earlier desktop binary was replaced.

## Repair

Before a Codex account change, inspect ChatGPT.app and Codex.app in system and user Applications. Require the OpenAI bundle identity and original Apple signing requirement before executing a candidate CLI. Select the newest installed signed desktop/core pair by core version and bundle build, with core0.167 as the minimum verified working generation. No network update, app removal, signature bypass, history rewrite or auth copy is added.

A private temporary codex executable scopes CodexSwitch to that pair. Its app command invokes `/usr/bin/open -a <selected app> --env CODEX_CLI_PATH=<selected core>`; all other subcommands run the same selected core. This prevents PATH/default app discovery or an inherited stale CODEX_CLI_PATH from choosing the post-switch runtime. It does not create a new chat. Other helper operations retain their packaged CLI.

Old, invalid or unsigned candidates cause a safe error before invoking the account switch. Each switch repeats selection. “Newest” means the newest compatible signed version already installed, not an automatic download or a guarantee against future upstream defects.

## Automated evidence

- Regression cases failed before implementation: selection, compatibility rejection and explicit launch scope.
- Original backend switch path also failed both integration cases: it used the legacy CLI and invoked the account switch despite an old core.
- Repaired suite:104 tests passed,2 platform skips. Five launcher cases exercise real fixture executables, actual temporary wrapper execution, backend subprocess PATH propagation and cleanup. Signature validation alone is replaced by a fixture double in these tests.
- Real installed desktop preflight selected `/Applications/ChatGPT.app` and its nested core0.167.0-alpha.3.2; original OpenAI signature verified.
- Full Mac package built, signature and frozen fixture self-test passed.
- Previous installed AI Accounts retained at `/Users/maripae/Backups/AI-Accounts-before-codex-launch-20261109-051519/previous.app`.

## Live acceptance

Pending fresh GUI account switch after other work completes, native resume and an actual continued response. Automated regression passes and an earlier native resume are not a substitute for this acceptance.

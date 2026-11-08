import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import SafeError


class ClaudeProfileTests(unittest.TestCase):
    def test_background_sync_never_closes_or_syncs_running_claude(self):
        from windows_backend import WindowsBackend
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            b = WindowsBackend(root=Path(tmp).resolve())
            switcher = Mock()
            switcher.win_processes.return_value = [(123, 1, 'Claude.exe', 'desktop')]
            switcher.win_is_app.return_value = True
            with patch.object(b, 'primary_mode', return_value=True), patch.object(b, 'primary_sync_directories', return_value=['a', 'b']), patch.object(b, 'claude_modules', return_value=switcher), patch.object(b, 'setup') as setup:
                b.sync()
            setup.assert_not_called()
            switcher.quit_app.assert_not_called()
            switcher.cs_sync.sync.assert_not_called()

    def test_background_sync_dispatches_to_windows_readiness_guard(self):
        import backend as entry
        from windows_backend import WindowsBackend
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            b = WindowsBackend(root=Path(tmp).resolve())
            switcher = Mock()
            switcher.cs_sync.sync.return_value = 0
            with patch('backend.Backend', return_value=b), patch('windows_backend.WindowsBackend', return_value=b), patch.object(b, 'claude_modules', return_value=switcher), patch.object(b, 'sync', return_value='waiting-for-configured-accounts', create=True) as sync:
                result = entry.main(['sync'])
            sync.assert_called_once_with()
            self.assertEqual(result['message'], 'waiting-for-configured-accounts')
            switcher.cs_sync.sync.assert_not_called()

    def test_pending_slot_login_of_existing_account_checkpoints_existing_slot_only(self):
        from windows_backend import WindowsBackend
        from backend import atomic_json
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            b = WindowsBackend(root=Path(tmp).resolve())
            atomic_json(b.state / 'identities.json', {'a': {'email': 'one@example.test', 'uuid': 'u'}})
            identity = {'email': 'one@example.test', 'uuid': 'u', 'token': 'fixture'}
            store = Mock()
            store.state.return_value = {'active': 'b', 'snapshots': {'a': 'saved-a'}}
            with patch.object(b, 'auth_store', return_value=store), patch.object(b, 'primary_identity', return_value=identity), patch.object(b, 'config', return_value={'profiles': {'a': {}, 'b': {}}}), patch.object(b, 'setup') as setup, patch.object(b, 'remember_primary_identity') as remember:
                b.checkpoint_primary()
            remember.assert_called_once_with('a', identity)
            store.capture.assert_called_once_with('a')
            setup.assert_not_called()

    def test_primary_setup_requires_every_distinct_identity_and_real_code_directory(self):
        from windows_backend import WindowsBackend
        from backend import atomic_json
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            b = WindowsBackend(root=Path(tmp).resolve())
            live = b.local / 'Claude-Data/claude_pzs8sxrjxfjjc'
            (live / 'claude-code-sessions/a/org').mkdir(parents=True)
            (live / 'claude-code-sessions/a/org/local_test.json').write_text('{}')
            profiles = {key: {'data_dir': str(b.roaming / key)} for key in ('a', 'b', 'c')}
            atomic_json(b.claude_config, {'profiles': profiles, 'sync_dirs': []})
            atomic_json(b.state / 'identities.json', {'a': {'email': 'a@example.test', 'uuid': 'a'}})
            switcher = Mock()
            switcher.cs_sync.sync.return_value = 0
            store = Mock()
            store.state.return_value = {'active': 'a', 'snapshots': {'a': 'saved-a'}}
            with patch.object(b, 'primary_mode', return_value=True), patch.object(b, 'auth_store', return_value=store), patch.object(b, 'claude_modules', return_value=switcher):
                with self.assertRaises(SafeError):
                    b.setup()
                switcher.cs_sync.sync.assert_not_called()

    def test_setup_does_not_claim_success_when_sync_returns_zero_but_files_differ(self):
        from windows_backend import WindowsBackend
        from backend import atomic_json, read_json
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            b = WindowsBackend(root=Path(tmp).resolve())
            live = b.local / 'Claude-Data/claude_pzs8sxrjxfjjc'
            profiles = {key: {'data_dir': str(b.roaming / key)} for key in ('a', 'b')}
            for key in profiles:
                (live / 'claude-code-sessions' / key / 'org').mkdir(parents=True)
            (live / 'claude-code-sessions/a/org/local_test.json').write_text('{"marker":"original"}')
            atomic_json(b.claude_config, {'profiles': profiles, 'sync_dirs': []})
            atomic_json(b.state / 'identities.json', {key: {'email': key + '@example.test', 'uuid': key} for key in profiles})
            switcher = Mock()
            switcher.cs_sync.sync.return_value = 0
            store = b.auth_store()
            atomic_json(store.root / 'state.json', {'active': 'a', 'snapshots': {key: 'saved-' + key for key in profiles}})
            with patch.object(b, 'primary_mode', return_value=True), patch.object(b, 'claude_modules', return_value=switcher), patch.object(b, 'close_primary_claude'):
                with self.assertRaises(SafeError):
                    b.setup()
            self.assertEqual(read_json(b.claude_config, {})['sync_dirs'], [])

    def test_sync_readiness_uses_configured_account_count_and_real_directories(self):
        from windows_backend import WindowsBackend
        from backend import atomic_json
        with tempfile.TemporaryDirectory() as tmp:
            b = WindowsBackend(root=Path(tmp).resolve())
            live = b.local / 'Claude-Data/claude_pzs8sxrjxfjjc'
            profiles = {key: {'data_dir': str(b.roaming / key)} for key in ('a', 'b')}
            for key in profiles:
                (live / 'claude-code-sessions' / key / 'org').mkdir(parents=True)
            atomic_json(b.claude_config, {'profiles': profiles, 'sync_dirs': []})
            atomic_json(b.state / 'identities.json', {key: {'email': key + '@example.test', 'uuid': key} for key in profiles})
            atomic_json(b.auth_store().root / 'state.json', {'active': 'a', 'snapshots': {key: 'saved-' + key for key in profiles}})
            self.assertEqual(len(b.primary_sync_directories()), 2)

    def test_identity_database_closes_before_network_or_profile_moves(self):
        from windows_backend import WindowsBackend
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as tmp:
            b = WindowsBackend(root=Path(tmp).resolve())
            live = b.local / 'Claude-Data/claude_pzs8sxrjxfjjc'
            (live / 'Network').mkdir(parents=True)
            (live / 'Network/Cookies').touch()
            (live / 'config.json').write_text(json.dumps({'lastKnownAccountUuid': 'u'}))
            connection = MagicMock()
            connection.__enter__.return_value = connection
            connection.execute.return_value.fetchall.return_value = [('.claude.ai', b'fixture')]
            def verify_closed(*args, **kwargs):
                connection.close.assert_called_once()
                return {'email': 'one@example.test', 'uuid': 'u'}
            with patch('windows_backend.sqlite3.connect', return_value=connection), patch('windows_backend.decrypt_cookie', return_value='fixture'), patch('windows_backend.request_json', side_effect=verify_closed):
                self.assertEqual(b.primary_identity()['uuid'], 'u')

    def test_duplicate_identity_is_refused_without_overwriting_existing_slot(self):
        from windows_backend import WindowsBackend
        from backend import atomic_json
        with tempfile.TemporaryDirectory() as tmp:
            b = WindowsBackend(root=Path(tmp).resolve())
            atomic_json(b.state / 'identities.json', {'a': {'email': 'one@example.test', 'usageAccount': 'original'}})
            with self.assertRaises(SafeError):
                b.remember_primary_identity('b', {'email': 'ONE@example.test', 'uuid': 'u', 'token': 'fixture'})
            self.assertEqual(json.loads((b.state / 'identities.json').read_text())['a']['usageAccount'], 'original')

    def test_existing_account_cannot_be_silently_replaced_with_different_identity(self):
        from windows_backend import WindowsBackend
        from backend import atomic_json
        with tempfile.TemporaryDirectory() as tmp:
            b = WindowsBackend(root=Path(tmp).resolve())
            atomic_json(b.state / 'identities.json', {'a': {'email': 'one@example.test', 'uuid': 'one'}})
            with self.assertRaises(SafeError):
                b.remember_primary_identity('a', {'email': 'two@example.test', 'uuid': 'two', 'token': 'fixture'})

    def test_crash_recovery_preserves_auth_and_sessions(self):
        from windows_claude_profiles import AuthStore
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            live = base / 'live'
            live.mkdir()
            (live / 'config.json').write_text('a')
            (live / 'Local State').write_text('key-a')
            store = AuthStore(live, base / 'store')
            store.capture('a')
            store.activate('b')
            (live / 'config.json').write_text('b')
            store.capture('b')
            with patch.object(store, 'copy_item', side_effect=lambda source, destination: (_ for _ in ()).throw(KeyboardInterrupt()) if destination == live / 'config.json' else AuthStore.copy_item(store, source, destination)):
                with self.assertRaises(KeyboardInterrupt):
                    store.activate('a')
            self.assertTrue(store.journal.exists())
            AuthStore(live, base / 'store').recover()
            self.assertEqual((live / 'config.json').read_text(), 'b')
            self.assertEqual(store.state()['active'], 'b')

    def test_fixture_backend_never_discovers_or_closes_host_app(self):
        from windows_backend import WindowsBackend
        with tempfile.TemporaryDirectory() as tmp:
            b = WindowsBackend(root=Path(tmp).resolve())
            with patch('windows_backend.subprocess.run') as run:
                self.assertIsNone(b.claude_app())
                self.assertFalse(b.primary_mode())
                run.assert_not_called()

    def test_primary_close_refuses_all_mutations_while_code_is_busy(self):
        from windows_backend import WindowsBackend
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            b = WindowsBackend(root=Path(tmp).resolve())
            switcher = Mock()
            switcher.win_processes.return_value = [(123, 1, 'Claude.exe', 'desktop')]
            switcher.win_is_app.return_value = True
            switcher.win_data_dir.return_value = 'live'
            switcher.busy_sessions.return_value = 1
            with patch.object(b, 'claude_modules', return_value=switcher):
                with self.assertRaises(SafeError):
                    b.close_primary_claude()
            switcher.quit_app.assert_not_called()

    def test_auth_switch_keeps_sessions_and_restores_both_accounts(self):
        from windows_claude_profiles import AuthStore
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            live = base / 'live'
            live.mkdir()
            sessions = live / 'claude-code-sessions' / 'a' / 'org'
            sessions.mkdir(parents=True)
            (sessions / 'original.json').write_text('session-73')
            store = AuthStore(live, base / 'store')
            (live / 'config.json').write_text('account-a')
            (live / 'Local State').write_text('key-a')
            store.capture('a')
            store.activate('b')
            self.assertFalse((live / 'config.json').exists())
            (live / 'config.json').write_text('account-b')
            (live / 'Local State').write_text('key-b')
            store.capture('b')
            store.activate('a')
            self.assertEqual((live / 'config.json').read_text(), 'account-a')
            self.assertEqual((live / 'Local State').read_text(), 'key-a')
            store.activate('b')
            self.assertEqual((live / 'config.json').read_text(), 'account-b')
            self.assertEqual((sessions / 'original.json').read_text(), 'session-73')

    def test_failure_and_interrupted_switch_restore_original_auth(self):
        from windows_claude_profiles import AuthStore
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            live = base / 'live'
            live.mkdir()
            (live / 'config.json').write_text('a')
            (live / 'Local State').write_text('key-a')
            store = AuthStore(live, base / 'store')
            store.capture('a')
            store.activate('b')
            (live / 'config.json').write_text('b')
            store.capture('b')
            original_copy = store.copy_item
            def failing_copy(source, destination):
                if destination == live / 'config.json' and source.parent.name != 'rollback':
                    raise OSError('simulated write failure')
                original_copy(source, destination)
            with patch.object(store, 'copy_item', side_effect=failing_copy):
                with self.assertRaises(SafeError):
                    store.activate('a')
            self.assertEqual((live / 'config.json').read_text(), 'b')
            self.assertEqual(store.state()['active'], 'b')
            self.assertFalse(store.journal.exists())

    def test_rejects_traversal_and_linked_auth_items(self):
        from windows_claude_profiles import AuthStore
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            live = base / 'live'
            live.mkdir()
            store = AuthStore(live, base / 'store')
            with self.assertRaises(SafeError):
                store.capture('../escape')
            with patch.object(store, 'is_link', return_value=True):
                with self.assertRaises(SafeError):
                    store.capture('a')

    def test_migrated_primary_path_is_recognized(self):
        from windows_backend import WindowsBackend
        with tempfile.TemporaryDirectory() as tmp:
            backend = WindowsBackend(root=Path(tmp).resolve())
            migrated = backend.local / 'Claude-Data/claude_pzs8sxrjxfjjc'
            migrated.mkdir(parents=True)
            (migrated / 'Local State').write_text('{}')
            self.assertEqual(backend.claude_primary_data(), migrated)


if __name__ == '__main__':
    unittest.main()

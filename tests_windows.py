import copy
import unittest
from datetime import datetime, timezone, timedelta

class WindowsTests(unittest.TestCase):
    def test_recommendation_boundaries(self):
        from windows_gui import recommendation
        now = datetime(2026, 11, 7, tzinfo=timezone.utc)
        usage = {'updatedAt': now.isoformat(), 'secondary': {'usedPercent': 0, 'resetsAt': (now + timedelta(hours=2)).isoformat()}}
        self.assertEqual(recommendation(usage, now)[0], 50)
        for value in (None, float('nan'), 100, -1, 101):
            broken = copy.deepcopy(usage)
            broken['secondary']['usedPercent'] = value
            self.assertIsNone(recommendation(broken, now)[0])
        for delta in (-1, 0):
            broken = copy.deepcopy(usage)
            broken['secondary']['resetsAt'] = (now + timedelta(seconds=delta)).isoformat()
            self.assertIsNone(recommendation(broken, now)[0])
        broken = copy.deepcopy(usage)
        broken['updatedAt'] = (now - timedelta(minutes=16)).isoformat()
        self.assertIsNone(recommendation(broken, now)[0])
        usage['primary'] = {'usedPercent': None}
        self.assertIsNone(recommendation(usage, now)[0])
        usage['primary'] = {'usedPercent': 90, 'resetsAt': (now + timedelta(hours=1)).isoformat()}
        self.assertEqual(recommendation(usage, now)[0], 10)

    def test_many_accounts_identity_and_partial_failures(self):
        from windows_gui import match_usage, parse_accounts
        accounts = [{'id': f'codex:a{i}', 'key': f'a{i}', 'provider': 'codex', 'label': str(i), 'usageAccount': f'a{i}', 'email': None} for i in range(50)]
        self.assertEqual(len(parse_accounts({'accounts': accounts})), 50)
        rows = [{'provider': 'codex', 'account': 'a2', 'usage': {'updatedAt': '2026-11-07T01:00:00Z'}}, {'provider': 'codex', 'account': 'a1', 'error': 'failed'}]
        self.assertEqual(match_usage(accounts[2], rows)['updatedAt'], '2026-11-07T01:00:00Z')
        self.assertIsNone(match_usage(accounts[1], rows))
        self.assertIsNone(match_usage(dict(accounts[2], email='other@example.invalid'), rows))
        with self.assertRaises(ValueError):
            parse_accounts({'accounts': accounts + [accounts[0]]})

    def test_normalize_unknown_and_zero(self):
        from windows_usage import normalize_codex, normalize_claude
        row = normalize_codex({'rate_limit': {'primary_window': {'used_percent': 0, 'reset_at': 1900000000}, 'secondary_window': {'used_percent': 40, 'reset_at': 1900000200}}, 'credits': {'balance': 0}}, 'a', None)
        self.assertEqual(row['usage']['primary']['usedPercent'], 0)
        self.assertEqual(row['credits']['remaining'], 0)
        for invalid in (float('nan'), float('inf'), -1, None, 'invalid'):
            self.assertIsNone(normalize_codex({'credits': {'balance': invalid}}, 'a', None)['credits']['remaining'])
        self.assertIsNone(normalize_codex({}, 'a', None)['usage']['secondary']['usedPercent'])
        self.assertEqual(normalize_claude({'seven_day': {'utilization': 0, 'resets_at': '2030-01-01T00:00:00Z'}}, 'a', None)['usage']['secondary']['usedPercent'], 0)

    def test_weekly_primary_window(self):
        from windows_usage import normalize_codex
        row = normalize_codex({'rate_limit': {'primary_window': {'used_percent': 12, 'limit_window_seconds': 604800, 'reset_at': 1900000000}}}, 'a', None)
        self.assertEqual(row['usage']['secondary']['usedPercent'], 12)
        self.assertNotIn('primary', row['usage'])

    def test_fixed_provider_origins_and_redirect_denial(self):
        from windows_usage import request_json, NoRedirect, UsageError
        with self.assertRaises(UsageError):
            request_json('https://example.invalid/api/usage', {'Authorization': 'not-a-real-secret'})
        with self.assertRaises(UsageError):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid/')

    def test_windows_profile_boundary(self):
        import tempfile
        from pathlib import Path
        from backend import atomic_json, SafeError
        from windows_backend import WindowsBackend
        with tempfile.TemporaryDirectory() as home:
            backend = WindowsBackend(root=home)
            self.assertEqual(backend.list_accounts()['accounts'], [])
            atomic_json(backend.claude_config, {'profiles': {'a': {'label': 'A', 'data_dir': str(Path(home) / 'outside')}}, 'sync_dirs': []})
            with self.assertRaises(SafeError):
                backend.config()

    def test_connect_rolls_back_config_when_identity_write_fails(self):
        import tempfile
        from unittest.mock import patch
        import windows_backend as mod
        with tempfile.TemporaryDirectory() as home:
            backend = mod.WindowsBackend(root=home)
            path = backend.root / '.config/codexbar/config.json'
            original = {'version': 1, 'providers': []}
            mod.atomic_json(path, original)
            write = mod.atomic_json
            def fail_identity(path, value):
                if path.name == 'identities.json':
                    raise OSError('fixture failure')
                write(path, value)
            with patch.object(mod, 'atomic_json', side_effect=fail_identity):
                with self.assertRaises(OSError):
                    backend.connect()
            self.assertEqual(mod.read_json(path, {}), original)

if __name__ == '__main__':
    unittest.main()

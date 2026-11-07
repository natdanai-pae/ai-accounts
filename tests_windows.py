import copy
import unittest
from datetime import datetime, timezone, timedelta

class WindowsTests(unittest.TestCase):
    def test_fresh_custom_account_starts_at_one(self):
        from windows_gui import stable_numbers
        first = {'id': 'codex:custom-id', 'provider': 'codex', 'key': 'custom-id'}
        mapping = stable_numbers([first], {})
        self.assertEqual(mapping, {'codex:custom-id': 1})
        second = {'id': 'codex:second-id', 'provider': 'codex', 'key': 'second-id'}
        self.assertEqual(stable_numbers([second], mapping)['codex:second-id'], 2)
        claude = {'id': 'claude:custom-id', 'provider': 'claude', 'key': 'custom-id'}
        self.assertEqual(stable_numbers([claude], {})[claude['id']], 1)

    def test_stable_account_numbers_and_natural_order(self):
        from windows_gui import stable_numbers, ordered_accounts
        accounts = [{'id': 'codex:' + key, 'provider': 'codex', 'key': key} for key in ['account3', 'main', 'account2', 'new']]
        mapping = stable_numbers(accounts, {})
        self.assertEqual([mapping[a['id']] for a in accounts], [3, 1, 2, 4])
        mapping = stable_numbers(accounts[::-1], mapping)
        self.assertEqual([a['key'] for a in ordered_accounts(accounts, mapping)], ['main', 'account2', 'account3', 'new'])
        more = [{'id': 'claude:' + k, 'provider': 'claude', 'key': k} for k in ['c', 'a', 'b']]
        self.assertEqual([stable_numbers(more, {})[a['id']] for a in more], [3, 1, 2])
        damaged = stable_numbers(accounts, {'codex:main': 1, 'codex:account2': 1, 'codex:account3': -1})
        self.assertEqual(len({damaged[a['id']] for a in accounts}), 4)
        many = accounts + [{'id': f'codex:n{i}', 'provider': 'codex', 'key': f'n{i}'} for i in range(50)]
        expanded = stable_numbers(many, mapping)
        self.assertEqual(expanded['codex:new'], 4)
        self.assertEqual(len({expanded[a['id']] for a in many}), 54)

    def test_alert_baseline_change_cooldown_restart_and_errors(self):
        from windows_gui import alert_policy
        now = datetime(2026, 11, 7, tzinfo=timezone.utc)
        accounts = [{'id': f'codex:{key}', 'provider': 'codex', 'key': key} for key in ['main', 'account2']]
        def usage(used, time=now):
            return {'updatedAt': time.isoformat(), 'secondary': {'usedPercent': used, 'resetsAt': (time + timedelta(hours=4)).isoformat()}}
        values = {'codex:main': usage(0), 'codex:account2': usage(50)}
        state, alerts = alert_policy({}, accounts, values, now, True)
        self.assertEqual(alerts, [])
        values = {'codex:main': usage(80), 'codex:account2': usage(0)}
        state, alerts = alert_policy(state, accounts, values, now, True)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['account'], 'codex:account2')
        import json
        state = json.loads(json.dumps(state))
        state, alerts = alert_policy(state, accounts, values, now, True)
        self.assertEqual(alerts, [])
        saved = copy.deepcopy(state)
        state, alerts = alert_policy(state, accounts, {}, now + timedelta(minutes=40), True)
        self.assertEqual(state['winners'], saved['winners'])
        self.assertEqual(alerts, [])
        values = {'codex:main': usage(0, now + timedelta(minutes=30)), 'codex:account2': usage(80, now + timedelta(minutes=30))}
        earlier = {key: dict(value, updatedAt=(now + timedelta(minutes=29)).isoformat()) for key, value in values.items()}
        self.assertEqual(alert_policy(state, accounts, earlier, now + timedelta(minutes=29), True)[1], [])
        _, alerts = alert_policy(state, accounts, values, now + timedelta(minutes=30), True)
        self.assertEqual(len(alerts), 1)
        _, alerts = alert_policy({}, accounts, values, now + timedelta(minutes=30), False)
        self.assertEqual(alerts, [])

    def test_near_reset_dedup_stale_exhausted_and_sleep(self):
        from windows_gui import alert_policy, refresh_due
        now = datetime(2026, 11, 7, tzinfo=timezone.utc)
        account = {'id': 'claude:a', 'provider': 'claude', 'key': 'a'}
        usage = {'updatedAt': now.isoformat(), 'secondary': {'usedPercent': 20, 'resetsAt': (now + timedelta(minutes=45)).isoformat()}}
        state, alerts = alert_policy({}, [account], {'claude:a': usage}, now, True)
        self.assertEqual(alerts[0]['kind'], 'reset')
        state, alerts = alert_policy(state, [account], {'claude:a': usage}, now, True)
        self.assertEqual(alerts, [])
        for used in (None, 100):
            broken = copy.deepcopy(usage)
            broken['secondary']['usedPercent'] = used
            self.assertEqual(alert_policy({}, [account], {'claude:a': broken}, now, True)[1], [])
        self.assertEqual(alert_policy({}, [account], {'claude:a': usage}, now + timedelta(minutes=20), True)[1], [])
        self.assertFalse(refresh_due(now.timestamp(), now.timestamp() + 299, False))
        self.assertTrue(refresh_due(now.timestamp(), now.timestamp() + 300, False))
        self.assertFalse(refresh_due(now.timestamp(), now.timestamp() + 3600, True))
        self.assertTrue(refresh_due(now.timestamp(), now.timestamp() + 3600, False))

    def test_reset_display_uses_countdown_and_handles_unknown(self):
        from windows_gui import reset_text
        now = datetime(2026, 11, 7, tzinfo=timezone.utc)
        self.assertIn('45 นาที', reset_text((now + timedelta(minutes=45)).isoformat(), now))
        self.assertIn('ถึงเวลา', reset_text(now.isoformat(), now))
        self.assertIn('ไม่ทราบ', reset_text(None, now))

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
        broken = dict(usage, error='refresh failed')
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

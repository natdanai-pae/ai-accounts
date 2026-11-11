import copy
import unittest
from datetime import datetime, timezone, timedelta

class WindowsTests(unittest.TestCase):
    def test_mcp_bridge_is_bound_before_gui_startup(self):
        import windows_gui
        from mcp_bridge import Bridge
        self.assertIs(getattr(windows_gui,'Bridge',None),Bridge)

    def test_event_poll_reschedules_even_after_handler_error(self):
        import ast
        from pathlib import Path
        from unittest.mock import Mock
        tree=ast.parse(Path(__file__).with_name('windows_gui.py').read_text())
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        poll=next(n for n in main.body if isinstance(n,ast.FunctionDef) and n.name=='poll')
        root=Mock();handler=Mock(side_effect=RuntimeError('fixture handler error'))
        scope={'root':root,'poll_once':handler}
        exec(compile(ast.Module(body=[poll],type_ignores=[]),'poll-fixture','exec'),scope)
        with self.assertRaises(RuntimeError):scope['poll']()
        root.after.assert_called_once_with(100,scope['poll'])

    def test_resume_claude_login_preserves_profiles_and_refuses_active_work(self):
        import tempfile
        from unittest.mock import Mock, patch
        from windows_backend import WindowsBackend
        from backend import atomic_json, SafeError
        with tempfile.TemporaryDirectory() as home:
            backend = WindowsBackend(root=home)
            for key in ('a', 'b'):
                (backend.roaming / key).mkdir(parents=True)
            conf = {'profiles': {k: {'label': k, 'data_dir': str(backend.roaming / k)} for k in ('a', 'b')}, 'sync_dirs': []}
            atomic_json(backend.claude_config, conf)
            switcher = Mock()
            switcher.running.return_value = {'a': 123}
            switcher.busy_sessions.return_value = 1
            with patch.object(backend, 'claude_modules', return_value=switcher), patch.object(backend, 'primary_mode', return_value=False):
                with self.assertRaises(SafeError):
                    backend.login('claude', 'b')
                switcher.quit_app.assert_not_called()
                switcher.busy_sessions.return_value = 0
                switcher.quit_app.return_value = True
                backend.login('claude', 'b')
                self.assertEqual(backend.config(), conf)
                switcher.launch.assert_called_once_with(conf, 'b')

    def test_three_selection_modes_and_limiting_reset_protection(self):
        from windows_gui import provider_winner, reset_wait_reason
        now = datetime(2026, 11, 7, tzinfo=timezone.utc)
        accounts = [{'id': 'codex:' + k, 'provider': 'codex', 'key': k} for k in ('a', 'b', 'c')]
        numbers = {'codex:a': 1, 'codex:b': 2, 'codex:c': 3}
        def usage(left, hours):
            return {'updatedAt': now.isoformat(), 'secondary': {'usedPercent': 100-left, 'resetsAt': (now+timedelta(hours=hours)).isoformat()}}
        values = {'codex:a': usage(40, 100), 'codex:b': usage(90, 100), 'codex:c': usage(60, 2)}
        for mode, expected in [('sequential', 'a'), ('balance', 'b'), ('rate', 'c')]:
            self.assertEqual(provider_winner(accounts, values, 'codex', now, mode, numbers)['key'], expected)
        exhausted = usage(0, 2)
        self.assertTrue(reset_wait_reason(exhausted, now, 24))
        self.assertIsNone(reset_wait_reason(exhausted, now, 1))
        exhausted['primary'] = {'usedPercent': 20, 'resetsAt': (now+timedelta(minutes=30)).isoformat()}
        exhausted['secondary']['resetsAt'] = (now+timedelta(days=5)).isoformat()
        self.assertIsNone(reset_wait_reason(exhausted, now, 24), 'short primary reset must not hide exhausted long weekly window')

    def test_usage_threshold_fires_once_per_window_even_when_exhausted(self):
        from windows_gui import alert_policy
        now = datetime(2026, 11, 7, tzinfo=timezone.utc)
        account = {'id': 'codex:a', 'provider': 'codex', 'key': 'a'}
        usage = {'updatedAt': now.isoformat(), 'secondary': {'usedPercent': 49, 'resetsAt': (now+timedelta(days=1)).isoformat()}}
        state, alerts = alert_policy({}, [account], {account['id']: usage}, now, True)
        self.assertEqual(alerts, [])
        usage['secondary']['usedPercent'] = 50
        state, alerts = alert_policy(state, [account], {account['id']: usage}, now, True)
        self.assertEqual(alerts[0]['kind'], 'usage')
        usage['secondary']['usedPercent'] = 100
        self.assertEqual(alert_policy(state, [account], {account['id']: usage}, now, True)[1], [])
        self.assertEqual(alert_policy({}, [account], {account['id']: usage}, now, True)[1][0]['kind'], 'usage')
        self.assertEqual(alert_policy({}, [account], {account['id']: usage}, now+timedelta(minutes=16), True)[1], [])

    def test_switcher_recognizes_store_desktop_but_not_code_cli_or_renderer(self):
        import sys
        from pathlib import Path
        from unittest.mock import patch
        sys.path.insert(0, str(Path(__file__).parent / 'vendor/claude-switcher'))
        import claude_switch as switcher
        app = r'C:\Program Files\WindowsApps\Claude_1.0_x64__pzs8sxrjxfjjc\app\Claude.exe'
        with patch.object(switcher.C, 'APP', app):
            self.assertTrue(switcher.win_is_app('Claude.exe', '"' + app + '"'))
            self.assertFalse(switcher.win_is_app('Claude.exe', '"' + app + '" --type=renderer'))
            self.assertFalse(switcher.win_is_app('claude.exe', r'C:\Users\BDA\.local\bin\claude.exe'))

    def test_claude_store_profile_maps_only_official_package_cache(self):
        import tempfile
        from pathlib import Path
        from backend import atomic_json, SafeError
        from windows_backend import WindowsBackend
        with tempfile.TemporaryDirectory() as home:
            backend = WindowsBackend(root=home)
            logical = backend.roaming / 'Claude AI Accounts a'
            physical = backend.local / 'Packages/Claude_pzs8sxrjxfjjc/LocalCache/Roaming/Claude AI Accounts a'
            physical.mkdir(parents=True)
            atomic_json(backend.claude_config, {'profiles': {'a': {'label': 'A', 'data_dir': str(logical)}}, 'sync_dirs': []})
            self.assertEqual(backend.config()['profiles']['a']['data_dir'], str(physical))
            for bad in (backend.local / 'Packages/Other/LocalCache/Roaming/a', Path(home) / 'outside'):
                atomic_json(backend.claude_config, {'profiles': {'a': {'label': 'A', 'data_dir': str(bad)}}, 'sync_dirs': []})
                with self.assertRaises(SafeError):
                    backend.config()

    def test_add_claude_finds_registered_windows_package(self):
        import tempfile, json
        from pathlib import Path
        from unittest.mock import patch, Mock
        from windows_backend import WindowsBackend
        with tempfile.TemporaryDirectory() as home:
            backend = WindowsBackend(root=home)
            package = Path(home) / 'WindowsApps/Claude'
            app = package / 'app/Claude.exe'
            app.parent.mkdir(parents=True)
            app.touch()
            result = Mock(returncode=0, stdout=json.dumps(str(package)).encode())
            backend.fixture_root = False
            with patch('windows_backend.subprocess.run', return_value=result), patch('windows_backend.subprocess.Popen') as launch, patch.object(backend, 'close_primary_claude'), patch.object(backend, 'checkpoint_primary'):
                self.assertTrue(backend.list_accounts()['dependencies']['claudeApp'])
                backend.add('claude', 'Account 1')
                args = launch.call_args.args[0]
                self.assertEqual(args[0], str(app))
                self.assertEqual(len(args), 1, 'Store sign-in must use the real primary app')
                self.assertEqual(len(backend.config()['profiles']), 1)

    def test_system_dpi_awareness_and_scaled_dimensions(self):
        from unittest.mock import Mock
        from windows_gui import system_dpi, scaled_pixels
        api = Mock()
        api.IsProcessDPIAware.return_value = True
        api.GetDpiForSystem.return_value = 144
        self.assertEqual(system_dpi(api), 144)
        self.assertEqual([call[0] for call in api.mock_calls], ['SetProcessDPIAware', 'IsProcessDPIAware', 'GetDpiForSystem'])
        self.assertEqual(scaled_pixels((1120, 850), 144), (1680, 1275))
        self.assertEqual(scaled_pixels(180, 144), 270)
        self.assertEqual(scaled_pixels((12, 0, 8, 7), 144), (18, 0, 12, 11))
        self.assertEqual(scaled_pixels((1120, 850), 96), (1120, 850))
        api.SetProcessDPIAware.return_value = False  # The executable manifest already set it.
        self.assertEqual(system_dpi(api), 144)
        api.IsProcessDPIAware.return_value = False
        with self.assertRaises(RuntimeError):
            system_dpi(api)

    def test_preview_fixtures_are_synthetic_and_support_empty_and_many(self):
        from windows_gui import preview_data
        now = datetime(2026, 11, 7, tzinfo=timezone.utc)
        for count in (0, 3, 25):
            data = preview_data(count, now)
            self.assertEqual(len(data['accounts']), count * 2)
            self.assertTrue(all(a['key'].startswith('fixture') and a['email'] is None for a in data['accounts']))
            self.assertEqual(len(data['usage']['codex']), count)
        self.assertEqual(len(preview_data(3, now)['resetStatuses']), 3)

    def test_missing_primary_uses_full_width_weekly_and_explicit_reason(self):
        from windows_gui import quota_lanes, recommendation_reason, provider_winner
        now = datetime(2026, 11, 7, tzinfo=timezone.utc)
        account = {'id': 'codex:main', 'provider': 'codex', 'key': 'main'}
        usage = {'updatedAt': now.isoformat(), 'secondary': {'usedPercent': 20, 'resetsAt': (now+timedelta(hours=2)).isoformat()}}
        for value in (usage, dict(usage, primary=None)):
            self.assertEqual(quota_lanes(value), [('secondary', 'รายสัปดาห์')])
            winner = provider_winner([account], {account['id']: value}, 'codex', now)
            self.assertEqual(winner, account)
            self.assertIn('รายสัปดาห์เท่านั้น', recommendation_reason([account], {account['id']: value}, winner, {account['id']: 1}, now))
        self.assertEqual(len(quota_lanes(dict(usage, primary={'usedPercent': None}))), 2)

    def test_reset_requires_confirmation_and_fresh_eligible_status(self):
        from windows_gui import reset_command
        account = {'provider': 'codex', 'key': 'main', 'email': 'fixture@example.invalid'}
        status = {'ok': True, 'supported': True, 'eligible': True, 'availableCount': 1, 'accountEmail': account['email'], 'uncertain': False}
        self.assertEqual(reset_command(account, status, True, False), ['reset', 'codex', 'main', '--confirmed'])
        self.assertIsNone(reset_command(account, status, False, False))
        self.assertIsNone(reset_command(account, status, True, True))
        for field, value in [('eligible', False), ('supported', False), ('availableCount', 0), ('accountEmail', 'other@example.invalid'), ('uncertain', True)]:
            self.assertIsNone(reset_command(account, dict(status, **{field: value}), True, False))
        self.assertIsNone(reset_command(dict(account, provider='claude'), status, True, False))

    def test_uncertain_reset_reuses_verified_eligible_attempt(self):
        from windows_gui import reset_command
        account = {'provider': 'codex', 'key': 'main', 'email': 'fixture@example.invalid'}
        status = {'ok': True, 'supported': True, 'eligible': True, 'availableCount': 1, 'accountEmail': account['email'], 'uncertain': True, 'attemptId': '2b8e9aa7-cf1c-4d34-8208-3f5162c72631'}
        self.assertEqual(reset_command(account, status, True, False), ['reset', 'codex', 'main', '--confirmed'])
        for attempt in (None, '', 'invalid', '../attempt'):
            self.assertIsNone(reset_command(account, dict(status, attemptId=attempt), True, False))
        self.assertIsNone(reset_command(account, dict(status, eligible=False), True, False))
        self.assertIsNone(reset_command(account, dict(status, accountEmail='other@example.invalid'), True, False))
        self.assertIsNone(reset_command(account, status, False, False))

    def test_reset_reasons_are_short_thai(self):
        from windows_gui import reset_reason
        self.assertIn('10%', reset_reason({'reason': 'Core 5h or weekly remaining must be <=10%'}))
        self.assertIn('ไม่มีสิทธิ์', reset_reason({'reason': 'No available free reset credit'}))
        self.assertIn('คำขอเดิม', reset_reason({'uncertain': True, 'reason': 'Previous result remains uncertain'}))
        self.assertEqual(reset_reason({'reason': 'Unknown lengthy upstream English message'}), 'ตรวจสิทธิ์ไม่ได้ · ดูรายละเอียด')

    def test_v5_prefers_ready_account_before_weekly_reset_priority(self):
        from windows_gui import provider_winner, recommendation_reason
        now = datetime(2026, 11, 7, tzinfo=timezone.utc)
        accounts = [{'id': f'codex:{key}', 'provider': 'codex', 'key': key} for key in ('main', 'account2')]
        def usage(primary, week, hours):
            return {'updatedAt': now.isoformat(), 'primary': {'usedPercent': 100-primary, 'resetsAt': (now+timedelta(hours=1)).isoformat()}, 'secondary': {'usedPercent': 100-week, 'resetsAt': (now+timedelta(hours=hours)).isoformat()}}
        values = {'codex:main': usage(5, 80, 1), 'codex:account2': usage(20, 10, 10)}
        winner = provider_winner(accounts, values, 'codex', now)
        self.assertEqual(winner['id'], 'codex:account2')
        reason = recommendation_reason(accounts, values, winner, {'codex:main': 1, 'codex:account2': 2}, now)
        self.assertIn('บัญชี 1', reason)
        self.assertIn('ใกล้หมด', reason)
        values['codex:main'] = usage(20, 80, 1)
        self.assertEqual(provider_winner(accounts, values, 'codex', now)['id'], 'codex:main')
        values['codex:main'] = usage(19, 80, 1)
        values['codex:account2'] = usage(19, 80, 2)
        self.assertEqual(provider_winner(accounts, values, 'codex', now)['id'], 'codex:main')
        values['codex:main']['updatedAt'] = (now-timedelta(minutes=16)).isoformat()
        self.assertEqual(provider_winner(accounts, values, 'codex', now)['id'], 'codex:account2')

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
        from windows_gui import alert_policy as full_alert_policy
        def alert_policy(*args):
            return full_alert_policy(*args, usage_threshold=None)
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
        from windows_gui import alert_policy as full_alert_policy, refresh_due
        def alert_policy(*args):
            return full_alert_policy(*args, usage_threshold=None)
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
        self.assertEqual(recommendation(usage, now)[0], 50)

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

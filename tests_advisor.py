import json
import unittest
from datetime import datetime, timezone, timedelta


class AdvisorTests(unittest.TestCase):
    def snapshot(self):
        from ai_advisor import build_snapshot
        now = datetime(2026, 11, 8, tzinfo=timezone.utc)
        accounts = [{'id': 'codex:a', 'provider': 'codex', 'email': 'private@example.test'},
                    {'id': 'codex:b', 'provider': 'codex', 'email': 'other@example.test'}]
        rows = [{'provider': 'codex', 'usage': {'accountEmail': a['email'], 'updatedAt': now.isoformat(),
                 'secondary': {'usedPercent': used, 'resetsAt': (now + timedelta(hours=hours)).isoformat()}}}
                for a, used, hours in zip(accounts, [74, 0], [36, 120])]
        return build_snapshot(accounts, rows, now), now

    def test_snapshot_contains_only_quota_and_opaque_references(self):
        (snapshot, mapping), _ = self.snapshot()
        encoded = json.dumps(snapshot)
        for private in ['private@', 'other@', 'codex:a', 'codex:b']:
            self.assertNotIn(private, encoded)
        self.assertEqual(snapshot['accounts'][0]['windows'][0]['remainingPercent'], 26)
        self.assertEqual(snapshot['accounts'][0]['windows'][0]['hoursUntilReset'], 36)
        self.assertEqual(len(mapping), 2)

    def test_rejects_unknown_cross_provider_or_duplicate_ai_choices(self):
        from ai_advisor import validate_answer
        from backend import SafeError
        (snapshot, mapping), now = self.snapshot()
        good = {'recommendations': [{'provider': 'codex', 'account': 'candidate1', 'reason': 'ใช้ยอดก่อนหมดรอบ', 'plan': 'ใช้บัญชีนี้ก่อน'}]}
        result = validate_answer(good, snapshot, mapping, now)
        self.assertEqual(result['recommendations'][0]['account'], 'codex:a')
        for choices in [[dict(good['recommendations'][0], account='secret')],
                        [dict(good['recommendations'][0], provider='claude')], good['recommendations'] * 2]:
            with self.assertRaises(SafeError):
                validate_answer({'recommendations': choices}, snapshot, mapping, now)

    def test_invalid_stale_exhausted_windows_do_not_reach_ai(self):
        from ai_advisor import build_snapshot
        from backend import SafeError
        now = datetime(2026, 11, 8, tzinfo=timezone.utc)
        a = [{'id': 'codex:a', 'provider': 'codex', 'email': 'private@example.test'}]
        for used, updated, reset in [(100, now, now + timedelta(hours=1)),
                                     (50, now - timedelta(minutes=16), now + timedelta(hours=1)),
                                     (float('nan'), now, now + timedelta(hours=1)),
                                     (50, now, now - timedelta(seconds=1))]:
            rows = [{'provider':'codex', 'usage':{'accountEmail':a[0]['email'], 'updatedAt':updated.isoformat(),
                    'secondary':{'usedPercent':used,'resetsAt':reset.isoformat()}}}]
            with self.assertRaises(SafeError): build_snapshot(a, rows, now)

    def test_response_requires_all_available_providers_and_safe_text(self):
        from ai_advisor import validate_answer
        from backend import SafeError
        (snapshot, mapping), now = self.snapshot()
        for reason in ['private@example.test', 'x' * 501, 'bad\x00text', '']:
            with self.assertRaises(SafeError):
                validate_answer({'recommendations':[{'provider':'codex','account':'candidate1','reason':reason,'plan':'ใช้ก่อน'}]}, snapshot, mapping, now)
        with self.assertRaises(SafeError): validate_answer({'recommendations':[]}, snapshot, mapping, now)

    def test_inference_is_ephemeral_tool_restricted_and_uses_only_sanitized_input(self):
        import tempfile
        import subprocess
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from ai_advisor import infer
        (snapshot, _), _ = self.snapshot()
        def run(args, **kwargs):
            self.assertIn('--ephemeral', args)
            self.assertIn('--ignore-user-config', args)
            self.assertEqual(args[args.index('--sandbox') + 1], 'read-only')
            self.assertNotIn('OPENAI_API_KEY', kwargs['env'])
            prompt = kwargs['input'].decode('utf-8')
            self.assertNotIn('private@example.test', prompt)
            self.assertNotIn('codex:a', prompt)
            self.assertIn('shell_tool', args)
            self.assertIn('multi_agent', args)
            self.assertNotIn('shell', kwargs)
            skill = Path(__file__).parent / 'skills/ai-quota-value/SKILL.md'
            self.assertTrue(skill.is_file(), 'quota-value skill must ship with the advisor')
            self.assertIn(skill.read_text(encoding='utf-8'), prompt)
            Path(args[args.index('--output-last-message') + 1]).write_text('{"recommendations":[]}', encoding='utf-8')
            return subprocess.CompletedProcess(args, 0)
        with tempfile.TemporaryDirectory() as tmp, patch('ai_advisor.subprocess.run', side_effect=run):
            b = SimpleNamespace(root=Path(tmp), executable=lambda _: 'fixture-codex')
            self.assertEqual(infer(b, snapshot), {'recommendations': []})

    def test_expired_advice_and_candidate_identifiers_are_not_shown(self):
        from ai_advisor import validate_answer
        from backend import SafeError
        (snapshot, mapping), now = self.snapshot()
        reply = {'recommendations':[{'provider':'codex','account':'candidate1','reason':'ใช้ candidate1 ก่อน candidate2','plan':'เลือก candidate2 หากไม่พอ'}]}
        result = validate_answer(reply, snapshot, mapping, now)
        self.assertNotIn('candidate', result['recommendations'][0]['reason'])
        with self.assertRaises(SafeError): validate_answer(reply, snapshot, mapping, now + timedelta(minutes=16))

    def test_daily_pace_is_a_percentage_point_target_not_a_prediction(self):
        (snapshot, _), _ = self.snapshot()
        weekly = snapshot['accounts'][0]['windows'][0]
        self.assertEqual(weekly.get('daysUntilReset'), 1.5)
        self.assertAlmostEqual(weekly.get('dailyUseToFinishPercent', -1), 17.333, places=3)
        self.assertAlmostEqual(snapshot['accounts'][1]['windows'][0].get('dailyUseToFinishPercent', -1), 20, places=3)

    def test_missing_bundled_skill_stops_inference_instead_of_silently_downgrading(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from ai_advisor import infer
        from backend import SafeError
        (snapshot, _), _ = self.snapshot()
        with tempfile.TemporaryDirectory() as tmp:
            backend = SimpleNamespace(root=Path(tmp), resources=Path(tmp), executable=lambda _: 'missing-codex')
            with self.assertRaisesRegex(SafeError, 'skill'):
                infer(backend, snapshot)

    def test_excluded_account_does_not_renumber_remaining_accounts(self):
        from ai_advisor import build_snapshot
        now = datetime(2026, 11, 8, tzinfo=timezone.utc)
        accounts = [{'id': 'codex:1', 'provider':'codex', 'email':'blocked@synthetic.invalid'},
                    {'id': 'codex:2', 'provider':'codex', 'email':'ready@synthetic.invalid'}]
        rows = [{'provider':'codex','usage':{'accountEmail':a['email'],'updatedAt':now.isoformat(),
                'secondary':{'usedPercent':used,'resetsAt':(now+timedelta(hours=48)).isoformat()}}}
                for a,used in zip(accounts,[100,30])]
        snapshot,mapping = build_snapshot(accounts,rows,now)
        self.assertEqual(snapshot['accounts'][0]['number'], 2)
        self.assertEqual(mapping['candidate1'], 'codex:2')

    def test_advice_returns_its_fresh_account_and_quota_snapshot_for_immediate_display(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from ai_advisor import advise
        now = datetime.now(timezone.utc)
        accounts = [{'id':'codex:1','provider':'codex','email':'private@synthetic.invalid'}]
        rows = [{'provider':'codex','usage':{'accountEmail':accounts[0]['email'],'updatedAt':now.isoformat(),
                 'secondary':{'usedPercent':78,'resetsAt':(now+timedelta(hours=36)).isoformat()}}}]
        calls = []
        def usage(provider):
            calls.append(provider)
            return rows + [None] if provider == 'codex' else []
        answer = {'recommendations':[{'provider':'codex','account':'candidate1','reason':'ใช้ก่อนรีเซ็ต','plan':'ใช้วันนี้'}]}
        with tempfile.TemporaryDirectory() as tmp, patch('ai_advisor.infer', return_value=answer):
            backend=SimpleNamespace(state=Path(tmp),root=Path(tmp),list_accounts=lambda:{'accounts':accounts},usage=usage)
            result=advise(backend)
        self.assertEqual(result.get('accounts'), accounts)
        self.assertEqual(result.get('usage'), {'codex':rows,'claude':[]})
        self.assertCountEqual(calls,['codex','claude'])
        self.assertEqual(result['recommendations'][0]['account'],'codex:1')

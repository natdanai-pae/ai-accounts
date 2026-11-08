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

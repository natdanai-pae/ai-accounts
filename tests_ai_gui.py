import unittest
from datetime import datetime, timezone, timedelta


class AIAdviceTests(unittest.TestCase):
    def test_result_sections_separate_full_provider_answers(self):
        import copy
        from windows_gui import ai_result_sections
        self.accounts.append({'id': 'claude:a', 'provider': 'claude', 'key': 'a'})
        self.values['claude:a'] = copy.deepcopy(self.values['codex:a'])
        self.reply['recommendations'].append({'provider': 'claude', 'account': 'claude:a', 'reason': 'เหตุผลเฉพาะ Claude', 'plan': 'แผน Claude ' + 'ก' * 900})
        sections = ai_result_sections(self.reply, self.accounts, self.values, {'codex:a': 1, 'claude:a': 2}, self.now)
        self.assertEqual([s['title'] for s in sections], ['Codex', 'Claude'])
        self.assertIn(self.reply['recommendations'][0]['plan'], sections[0]['text'])
        self.assertNotIn('แผน Claude', sections[0]['text'])
        self.assertIn(self.reply['recommendations'][1]['plan'], sections[1]['text'])
        self.assertNotIn(self.reply['recommendations'][0]['reason'], sections[1]['text'])
        self.assertIn('บัญชี 2', sections[1]['text'])

    def test_stale_result_sections_do_not_repeat_old_advice(self):
        from windows_gui import ai_result_sections
        sections = ai_result_sections(self.reply, self.accounts, self.values, {'codex:a': 1}, self.now + timedelta(minutes=16))
        self.assertEqual(len(sections), 2)
        self.assertTrue(all('ยังไม่มีคำแนะนำ AI ที่ใช้ได้' in s['text'] for s in sections))
        self.assertNotIn(self.reply['recommendations'][0]['reason'], str(sections))

    def test_ai_notices_keep_usage_only_and_use_displayed_winner(self):
        from windows_gui import ai_consistent_alerts
        usage = {'provider': 'codex', 'kind': 'usage', 'account': 'codex:b', 'used': 50}
        alerts = [{'provider': 'codex', 'kind': 'winner', 'account': 'codex:b', 'also': [usage, {'kind': 'reset', 'provider': 'codex', 'account': 'codex:b'}]}, {'provider': 'claude', 'kind': 'winner', 'account': 'claude:a'}]
        result = ai_consistent_alerts(alerts, {'codex': {'account': 'codex:a'}})
        self.assertEqual(result[0]['kind'], 'usage')
        self.assertEqual(result[0]['recommendedAccount'], 'codex:a')
        self.assertEqual(result[0]['also'], [])
        self.assertEqual(result[1], alerts[1])
        self.assertEqual(ai_consistent_alerts([{'provider': 'codex', 'kind': 'winner'}], {'codex': {'account': 'codex:a'}}), [])
        self.assertEqual(ai_consistent_alerts(alerts, {}), alerts)

    def setUp(self):
        self.now = datetime(2026, 11, 8, tzinfo=timezone.utc)
        self.accounts = [{'id': 'codex:a', 'provider': 'codex', 'key': 'a'}]
        self.values = {'codex:a': {'updatedAt': self.now.isoformat(), 'secondary': {'usedPercent': 75, 'resetsAt': (self.now + timedelta(days=1)).isoformat()}}}
        self.reply = {'ok': True, 'generatedAt': self.now.isoformat(), 'recommendations': [{'provider': 'codex', 'account': 'codex:a', 'reason': 'ใช้โควตาที่จะหมดก่อน', 'plan': 'ใช้บัญชีนี้วันนี้ แล้ววิเคราะห์ใหม่'}]}

    def test_valid_advice_retains_model_provenance_and_choice(self):
        from windows_gui import validated_ai_advice
        self.accounts.append({'id': 'codex:b', 'provider': 'codex', 'key': 'b'})
        self.values['codex:b'] = {'updatedAt': self.now.isoformat(), 'secondary': {'usedPercent': 0, 'resetsAt': (self.now + timedelta(days=5)).isoformat()}}
        result = validated_ai_advice(self.reply, self.accounts, self.values, self.now)
        self.assertEqual(result['codex']['account'], 'codex:a')
        self.assertEqual(result['codex']['reason'], self.reply['recommendations'][0]['reason'])
        self.assertEqual(result['codex']['source'], 'AI · Codex')

    def test_rejects_unknown_provider_mismatch_stale_and_ineligible(self):
        import copy
        from windows_gui import validated_ai_advice
        for field, value in [('account', 'codex:unknown'), ('provider', 'claude'), ('reason', ''), ('plan', 'x' * 1001)]:
            reply = copy.deepcopy(self.reply)
            reply['recommendations'][0][field] = value
            self.assertEqual(validated_ai_advice(reply, self.accounts, self.values, self.now), {})
        self.assertEqual(validated_ai_advice(self.reply, self.accounts, self.values, self.now + timedelta(minutes=16)), {})
        self.values['codex:a']['secondary']['usedPercent'] = 100
        self.assertEqual(validated_ai_advice(self.reply, self.accounts, self.values, self.now), {})

    def test_unknown_or_future_output_has_no_ai_provenance(self):
        from windows_gui import validated_ai_advice
        for reply in (None, {}, {'ok': False}, {'ok': True, 'generatedAt': self.now.isoformat(), 'recommendations': 'invalid'}):
            self.assertEqual(validated_ai_advice(reply, self.accounts, self.values, self.now), {})
        self.assertEqual(validated_ai_advice(self.reply, self.accounts, self.values, self.now - timedelta(seconds=1)), {})
        self.reply['recommendations'] *= 2
        self.assertEqual(validated_ai_advice(self.reply, self.accounts, self.values, self.now), {})

    def test_busy_does_not_start_or_clear_and_refresh_invalidates(self):
        from windows_gui import begin_account_work
        state = {'busy': True, 'aiAdvice': self.reply}
        self.assertFalse(begin_account_work(state))
        self.assertEqual(state['aiAdvice'], self.reply)
        state['busy'] = False
        self.assertTrue(begin_account_work(state))
        self.assertTrue(state['busy'])
        self.assertIsNone(state['aiAdvice'])

    def test_refresh_accepts_only_explicit_ai_result_after_snapshot(self):
        from windows_gui import apply_account_snapshot, validated_ai_advice
        state = {'aiAdvice': self.reply}
        apply_account_snapshot(state, self.accounts, {}, {})
        self.assertIsNone(state['aiAdvice'])
        apply_account_snapshot(state, self.accounts, {}, {'aiAdvice': self.reply})
        self.assertEqual(validated_ai_advice(state['aiAdvice'], state['accounts'], self.values, self.now)['codex']['source'], 'AI · Codex')


if __name__ == '__main__':
    unittest.main()

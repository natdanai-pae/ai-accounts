"""Headless authority keeps AI choices; quota changes never silently rebalance."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock


class HeadlessAuthorityTests(unittest.TestCase):
    def make(self, directory):
        self.assertIsNotNone(importlib.util.find_spec('headless_authority'), 'headless authority missing')
        from headless_authority import Authority
        return Authority(Path(directory) / 'decision.json')

    @staticmethod
    def records(now=1000):
        return [{'provider':provider,'account_ref':provider+'-'+str(n),'number':n,'used':used,
                 'checked':now,'reset':now+10000,'identity_verified':True,'identity_binding':'a'*64}
                for provider in ('codex','claude') for n,used in ((1,1),(2,50),(3,97))]

    @staticmethod
    def choose_number(number):
        def infer(snapshot):
            return {'recommendations':[
                {'provider':provider,'account':next(a['account'] for a in snapshot['accounts'] if a['provider']==provider and a['number']==number),
                 'reason':'Use the selected account until next AI decision','plan':'Use useful work before reset'}
                for provider in ('codex','claude')]}
        return infer

    def test_only_ai_change_switches_not_quota_or_reads_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as d:
            authority=self.make(d)
            authority.publish(self.records())
            authority.analyze(self.choose_number(3),now=1000)
            before=(Path(d)/'decision.json').read_bytes()
            first=authority.call('ai_accounts_recommend',{'provider':'codex'},now=1000)
            self.assertEqual(first['recommended_account']['account_number'],3)
            self.assertEqual(first['account_ref'],'codex-3')
            self.assertEqual(first['decision_source'],'ai')
            # Account1 has much more quota, but a regular publication cannot change selection.
            authority.publish(self.records(now=1001))
            second=authority.call('ai_accounts_recommend',{'provider':'codex'},now=1001)
            self.assertEqual(second['decision_id'],first['decision_id'])
            self.assertEqual((Path(d)/'decision.json').read_bytes(),before)
            restarted=self.make(d);restarted.publish(self.records(now=1001))
            self.assertEqual(restarted.call('ai_accounts_recommend',{'provider':'codex'},now=1001)['account_ref'],'codex-3')
            restarted.analyze(self.choose_number(2),now=1001)
            self.assertEqual(restarted.call('ai_accounts_recommend',{'provider':'codex'},now=1001)['account_ref'],'codex-2')

    def test_stale_unknown_expired_and_exhausted_queue_without_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            authority=self.make(d);records=self.records();authority.publish(records)
            authority.analyze(self.choose_number(3),now=1000)
            for change,now in (({'used':100},1001),({'identity_verified':False},1001),({'checked':1},1001),({},1901)):
                rows=self.records()
                for row in rows:
                    if row['account_ref']=='codex-3':row.update(change)
                authority.publish(rows)
                result=authority.call('ai_accounts_recommend',{'provider':'codex'},now=now)
                self.assertFalse(result['can_dispatch'])
                self.assertIsNone(result['recommended_account'])
                self.assertEqual(result['account_ref'],'codex-3')
                self.assertIsNotNone(result['decision_id'])

    def test_failed_ai_does_not_overwrite_last_decision_and_no_secrets_in_payload(self):
        with tempfile.TemporaryDirectory() as d:
            authority=self.make(d);rows=self.records()
            for row in rows:row.update(token='secret-value',email='private@example.test',credential_path='/home/private/auth.json')
            authority.publish(rows);authority.analyze(self.choose_number(2),now=1000)
            before=(Path(d)/'decision.json').read_bytes()
            with self.assertRaises(Exception):authority.analyze(lambda snapshot:{'recommendations':[]},now=1001)
            self.assertEqual((Path(d)/'decision.json').read_bytes(),before)
            payload=json.dumps(authority.call('ai_accounts_summary',{},now=1001))
            for private in ('secret-value','private@example.test','/home/private/auth.json','token','credential_path'):
                self.assertNotIn(private,payload)
            result=json.loads(before)
            self.assertNotIn('secret-value',json.dumps(result))

    def test_reads_never_collect_or_infer(self):
        with tempfile.TemporaryDirectory() as d:
            authority=self.make(d)
            authority.publish(self.records())
            infer=Mock(side_effect=self.choose_number(1))
            authority.analyze(infer,now=1000)
            for _ in range(5):
                for name,args in (('ai_accounts_status',{}),('ai_accounts_summary',{}),('ai_accounts_recommend',{'provider':'claude'})):
                    authority.call(name,args,now=1000)
            self.assertEqual(infer.call_count,1)

    def test_router_adapter_rejects_unknown_identity_and_binding_quota(self):
        from headless_authority import router_records
        meta={'checked_epoch':1000,'expires_epoch':10000,'expected_identity':'local-opaque-pin',
              'windows_used_percent':{'weekly':6,'five_hour':20},'windows_reset_epoch':{'weekly':6000,'five_hour':3000},
              'availability':'ready'}
        record=router_records({'claude-1':meta},now=1000)[0]
        self.assertTrue(record['identity_verified']);self.assertEqual(record['primary_used'],20)
        self.assertNotIn('local-opaque-pin',json.dumps(record))
        with tempfile.TemporaryDirectory() as d:
            authority=self.make(d)
            for change in ({'expected_identity':None},{'identity_quarantined':True},{'expires_epoch':1000},{'error':'HTTP429'}):
                projected=router_records({'claude-1':dict(meta,**change)},now=1000)
                authority.publish(projected)
                self.assertEqual(authority.call('ai_accounts_status',{},now=1000)['accounts'][0]['availability'],'error' if change.get('error') else 'unknown')
            blocked=dict(meta,windows_used_percent={'weekly':6,'sonnet':100},windows_reset_epoch={'weekly':6000,'sonnet':3000})
            authority.publish(router_records({'claude-1':blocked},now=1000))
            self.assertEqual(authority.call('ai_accounts_status',{},now=1000)['accounts'][0]['availability'],'exhausted')

    def test_account_identity_changed_after_ai_stays_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            authority=self.make(d);authority.publish(self.records());authority.analyze(self.choose_number(3),now=1000)
            records=self.records(now=1001)
            for row in records:
                if row['account_ref']=='codex-3':row['identity_binding']='b'*64
            authority.publish(records)
            result=authority.call('ai_accounts_recommend',{'provider':'codex'},now=1001)
            self.assertFalse(result['can_dispatch']);self.assertIsNone(result['recommended_account'])

if __name__=='__main__':unittest.main()

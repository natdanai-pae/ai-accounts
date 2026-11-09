import ast
from datetime import datetime, timezone
import importlib.util
import types
import unittest

# Narrow public caller fixture; no legacy worker/runtime payload is vendored.
SOURCE='''def approved_route(candidates, kind, probes):
    try:
        return pool.choose(candidates, kind)
    except ValueError:
        pass
    for r in sorted(candidates, key=lambda r: (r.get('last_used_at') or '', r['id'])):
        probe = probes.get(r['id'])
        if not probe or probe.get('fixture_read_tool_verified') is not True:
            continue
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(probe['observed_at'])).total_seconds()
        if 0 <= age < 3600 and r['provider'] == 'litellm':
            try:
                return pool.choose(candidates, kind, r['id'])
            except ValueError:
                pass
    raise ValueError('No approved fresh route')


def tick(entries, running, executor, routes, probes=None):
    return None
'''

def caller(source,policy):
    paid={'id':'paid-route','provider':'litellm'}
    calls=[]
    def choose(candidates,kind,requested=None):
        calls.append(requested)
        if requested is None:raise ValueError('AI Accounts unavailable; queue')
        return paid
    pool=types.SimpleNamespace(choose=choose,CONTROL_PLANE_VERSION=policy)
    namespace={'pool':pool,'datetime':datetime,'timezone':timezone}
    exec(compile(source,'<continuation-fixture>','exec'),namespace)
    return namespace['approved_route'],pool,paid,calls

class ContinuationPatchTests(unittest.TestCase):
    def patcher(self):
        self.assertIsNotNone(importlib.util.find_spec('continuation_authority_patch'),'continuation policy guard is missing')
        from continuation_authority_patch import patch
        return patch

    def test_authority_failure_must_queue_not_try_paid_probe(self):
        call,_,paid,calls=caller(self.patcher()(SOURCE),'ai_accounts_sticky_v1')
        probes={paid['id']:{'fixture_read_tool_verified':True,'observed_at':datetime.now(timezone.utc).isoformat()}}
        with self.assertRaises(ValueError):call([paid],'review',probes)
        self.assertEqual(calls,[None])

    def test_legacy_policy_keeps_existing_approved_paid_fallback(self):
        call,_,paid,calls=caller(self.patcher()(SOURCE),'native_refresh_v2')
        probes={paid['id']:{'fixture_read_tool_verified':True,'observed_at':datetime.now(timezone.utc).isoformat()}}
        self.assertEqual(call([paid],'review',probes),paid)
        self.assertEqual(calls,[None,'paid-route'])

    def test_success_before_guard_is_unchanged(self):
        call,pool,paid,_=caller(self.patcher()(SOURCE),'ai_accounts_sticky_v1')
        pool.choose=lambda *args:paid
        self.assertEqual(call([paid],'review',{}),paid)

    def test_unrecognized_or_already_patched_source_rejected(self):
        patch=self.patcher()
        for source in ('unrelated',SOURCE.replace('        pass','        return None',1),patch(SOURCE)):
            with self.subTest(source=source[:30]),self.assertRaises(ValueError):patch(source)
        ast.parse(patch(SOURCE))

if __name__=='__main__':unittest.main()

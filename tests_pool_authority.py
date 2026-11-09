"""Read-only AI Accounts selection; changing load must never rotate an account."""
import importlib.util
from datetime import datetime, timezone
import copy
import unittest
from unittest.mock import patch

NOW = 1800000000.0

def stamp(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()

def response(alias='codex-2', decision='decision-one'):
    provider, number = alias.split('-')
    return {'source':'ai', 'decision_id':decision, 'account_ref':alias,
            'generated_at':stamp(NOW-10), 'expires_at':stamp(NOW+890),
            'recommended_account':{'provider':provider,'account_number':int(number),
                'account_alias':'Account '+number,'identity_masked':'n***@example.test',
                'availability':'ready','quota_used_percent':70,
                'quota_remaining_percent':30,'quota_checked_at':stamp(NOW-5),
                'quota_reset_at':stamp(NOW+3600),'quota_reset_in_seconds':3600,
                'data_fresh':True,'note':'weekly'},
            'availability':'ready','quota_remaining_percent':30,
            'reason':'Use selected account','evaluated_at':stamp(NOW-10),
            'alternatives':[], 'can_dispatch':True,
            'dispatch_note':'readiness only'}

def routes():
    return [{'id':'codex-1','provider':'codex','availability':'ready',
             'quota_stale':False,'quota':{'weekly':{'used_percent':0}},
             'active_jobs':0,'capacity':5},
            {'id':'codex-2','provider':'codex','availability':'ready',
             'quota_stale':False,'quota':{'weekly':{'used_percent':70}},
             'active_jobs':3,'capacity':5}]

class AuthoritySelectionTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('pool_authority'),
                             'read-only authority selector is missing')
        import pool_authority
        return pool_authority

    def test_sticks_to_authority_despite_better_headroom_and_lower_load(self):
        m=self.module(); candidates=routes(); before=copy.deepcopy(candidates)
        chosen=m.select_route(candidates,'codex',now=NOW,recommendation=response())
        self.assertEqual(chosen['id'],'codex-2')
        candidates[0].update(active_jobs=0)
        candidates[1].update(active_jobs=4)
        self.assertEqual(m.select_route(candidates,'codex',now=NOW,recommendation=response())['id'],'codex-2')
        candidates[1]['active_jobs']=before[1]['active_jobs']
        self.assertEqual(candidates,before)

    def test_chosen_full_or_unknown_queues_instead_of_falling_back(self):
        m=self.module()
        for field,value in [('active_jobs',5),('availability','unknown'),('quota_stale',True)]:
            candidates=routes();candidates[1][field]=value
            with self.subTest(field=field),self.assertRaises(m.AuthorityUnavailable):
                m.select_route(candidates,'codex',now=NOW,recommendation=response())

    def test_new_decision_affects_only_next_selection_not_existing_object(self):
        m=self.module(); candidates=routes()
        running=m.select_route(candidates,'codex',now=NOW,recommendation=response())
        next_route=m.select_route(candidates,'codex',now=NOW,recommendation=response('codex-1','decision-two'))
        self.assertEqual(running['id'],'codex-2');self.assertEqual(next_route['id'],'codex-1')

    def test_stale_unknown_exhausted_and_bad_provenance_fail_closed(self):
        m=self.module()
        variants=[{'source':'rule'}, {'expires_at':stamp(NOW)}, {'generated_at':stamp(NOW+61)},
                  {'can_dispatch':False}, {'account_ref':'claude-2'}, {'availability':'unknown'},
                  {'decision_id':''}]
        for change in variants:
            payload=response();payload.update(change)
            with self.subTest(change=change),self.assertRaises(m.AuthorityUnavailable):
                m.select_route(routes(),'codex',now=NOW,recommendation=payload)
        for change in [{'data_fresh':False},{'quota_checked_at':stamp(NOW-241)},
                       {'quota_reset_at':stamp(NOW)}, {'quota_remaining_percent':0},
                       {'quota_remaining_percent':99},{'availability':'error'}]:
            payload=response();payload['recommended_account'].update(change)
            with self.subTest(change=change),self.assertRaises(m.AuthorityUnavailable):
                m.select_route(routes(),'codex',now=NOW,recommendation=payload)

    def test_local_identity_or_model_guard_cannot_fallback(self):
        m=self.module()
        with self.assertRaises(m.AuthorityUnavailable):
            m.select_route(routes(),'codex',now=NOW,recommendation=response(),eligible=lambda row:row['id']=='codex-1')

    def test_only_fixed_local_tool_called_and_failure_not_retried(self):
        m=self.module()
        result={'jsonrpc':'2.0','id':1,'result':{'isError':False,'structuredContent':response()}}
        with patch.object(m,'_exchange',return_value=result) as exchange:
            self.assertEqual(m.read_recommendation('codex',now=NOW)['account_ref'],'codex-2')
            self.assertEqual(exchange.call_args.args[0]['params'],{'name':'ai_accounts_recommend','arguments':{'provider':'codex'}})
            self.assertEqual(exchange.call_count,1)
        with patch.object(m,'_exchange',side_effect=OSError('private detail')) as exchange:
            with self.assertRaises(m.AuthorityUnavailable) as error:m.read_recommendation('codex',now=NOW)
            self.assertNotIn('private detail',str(error.exception));self.assertEqual(exchange.call_count,1)

    def test_real_http_fixed_endpoint_has_no_proxy_credentials_or_redirect(self):
        m=self.module()
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading,json,os
        calls=[]; redirect=[False]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append((self.path,payload,self.headers.get('Authorization')))
                if redirect[0]:
                    self.send_response(302);self.send_header('Location','/forbidden');self.end_headers();return
                data=json.dumps({'jsonrpc':'2.0','id':1,'result':{'isError':False,'structuredContent':response()}}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch.object(m,'ENDPOINT','http://127.0.0.1:'+str(server.server_port)+'/mcp'),patch.dict(os.environ,{'HTTP_PROXY':'http://invalid.invalid:1','http_proxy':'http://invalid.invalid:1'}):
                self.assertEqual(m.read_recommendation('codex',now=NOW)['account_ref'],'codex-2')
                redirect[0]=True
                with self.assertRaises(m.AuthorityUnavailable):m.read_recommendation('codex',now=NOW)
            self.assertEqual(len(calls),2)
            self.assertTrue(all(path=='/mcp' and auth is None for path,_,auth in calls))
            self.assertTrue(all(payload['params']=={'name':'ai_accounts_recommend','arguments':{'provider':'codex'}} for _,payload,_ in calls))
        finally:server.shutdown();server.server_close()

    def test_local_guard_exception_is_sanitized_queueable_failure(self):
        m=self.module()
        def broken_guard(row):raise RuntimeError('private identity credential detail')
        with self.assertRaises(m.AuthorityUnavailable) as error:
            m.select_route(routes(),'codex',now=NOW,recommendation=response(),eligible=broken_guard)
        self.assertNotIn('private',str(error.exception))

if __name__=='__main__':unittest.main()

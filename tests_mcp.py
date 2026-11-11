import importlib.util
import unittest

class MCPTests(unittest.TestCase):
    def test_projection_uses_ui_winner_and_never_leaks_private_payload(self):
        self.assertIsNotNone(importlib.util.find_spec('mcp_server'), 'read-only MCP projection missing')
        import mcp_server as m
        snapshot={'evaluated_at':1000,'refreshing':False,'accounts':[
            {'provider':p,'number':i,'email':'name@example.test','used':u,'checked':1000,'reset':2000,'error':False,'token':'sk-secret','path':'/Users/private/auth.json'}
            for p in ('codex','claude') for i,u in ((1,40),(2,95),(3,100))],
            'recommendations':{p:{'number':2,'reason':'UI winner name@example.test','evaluated_at':1000} for p in ('codex','claude')}}
        service=m.Service();service.publish(snapshot)
        status=service.call('ai_accounts_status',{},now=1000)
        self.assertEqual(len(status['accounts']),6)
        for a in status['accounts']: self.assertEqual(a['quota_used_percent']+a['quota_remaining_percent'],100)
        for p in ('codex','claude'):
            r=service.call('ai_accounts_recommend',{'provider':p},now=1000)
            self.assertEqual(r['recommended_account']['account_number'],2)
            self.assertEqual(r['quota_remaining_percent'],5)
        import json
        text=json.dumps(service.call('ai_accounts_summary',{},now=1000))
        self.assertNotIn('name@example.test',text); self.assertNotIn('sk-secret',text); self.assertNotIn('/Users/',text)
        states={a['availability'] for a in status['accounts']}
        self.assertEqual(states,{'ready','near_limit','exhausted'})
        stale=service.call('ai_accounts_recommend',{'provider':'codex'},now=2001)
        self.assertIsNone(stale['recommended_account']);self.assertFalse(stale['can_dispatch'])

    def test_invalid_inputs_and_unknown_data_do_not_infer(self):
        self.assertIsNotNone(importlib.util.find_spec('mcp_server'), 'MCP validation missing')
        import mcp_server as m
        s=m.Service();s.publish({'accounts':[{'provider':'codex','number':1,'used':None,'checked':1000,'reset':2000},{'provider':'claude','number':1,'error':True}], 'recommendations':{}})
        rows=s.call('ai_accounts_status',{},now=1000)['accounts']
        self.assertEqual([r['availability'] for r in rows],['unknown','error'])
        for name,args in [('login',{}),('ai_accounts_status',{'provider':'evil'}),('ai_accounts_summary',{'path':'auth.json'}),('ai_accounts_recommend',{'provider':'all'})]:
            with self.assertRaises(m.InputError):s.call(name,args)

    def test_refreshing_stale_primary_unknown_and_secret_reason(self):
        import mcp_server as m
        service=m.Service()
        base={'provider':'codex','number':1,'used':22,'checked':1000,'reset':5000}
        for overrides,refreshing,expected in [({},True,'refreshing'),({'checked':1},False,'stale'),({'used':None},False,'unknown'),({'primary_present':True},False,'unknown'),({'primary_present':True,'primary_used':100,'primary_reset':5000},False,'exhausted'),({'primary_present':True,'primary_used':95,'primary_reset':5000},False,'near_limit'),({'error':True},False,'error')]:
            service.publish({'accounts':[dict(base,**overrides)],'refreshing':refreshing})
            self.assertEqual(service.call('ai_accounts_status',{},now=1000)['accounts'][0]['availability'],expected)
        for secret in ('Bearer xyz','cookie=abc','sk-secret','/Users/owner/auth.json','C:\\Users\\owner\\auth.json','refresh_token=abc'):
            service.publish({'accounts':[base],'recommendations':{'codex':{'number':1,'reason':secret,'evaluated_at':1000}}})
            self.assertNotIn(secret,service.call('ai_accounts_recommend',{'provider':'codex'},now=1000)['reason'])

    def test_mcp_protocol_has_only_three_read_tools_and_structured_errors(self):
        import mcp_server as m
        service=m.Service()
        names=[t['name'] for t in service.rpc({'jsonrpc':'2.0','id':1,'method':'tools/list'})['result']['tools']]
        self.assertEqual(set(names),{'ai_accounts_status','ai_accounts_recommend','ai_accounts_summary'})
        r=service.rpc({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'ai_accounts_status','arguments':{'provider':'evil'}}})
        self.assertTrue(r['result']['isError']);self.assertEqual(r['result']['structuredContent']['error']['code'],'INVALID_INPUT')

    def test_server_has_no_provider_or_credential_reader_dependency(self):
        import ast
        from pathlib import Path
        tree=ast.parse(Path(__file__).with_name('mcp_server.py').read_text())
        imported=set()
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):imported.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node,ast.ImportFrom):imported.add((node.module or '').split('.')[0])
        self.assertFalse(imported & {'backend','windows_backend','ai_advisor','requests','urllib','sqlite3','subprocess','keyring'})
        calls={node.func.id for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)}
        self.assertNotIn('open',calls)

    def test_malformed_call_params_return_private_structured_errors(self):
        import contextlib, io, json
        import mcp_server as m
        service=m.Service(); logs=io.StringIO()
        with contextlib.redirect_stderr(logs):
            for params in (None, [], 'private@example.test', 42):
                result=service.rpc({'jsonrpc':'2.0','id':7,'method':'tools/call','params':params})
                self.assertTrue(result['result']['isError'])
                self.assertEqual(result['result']['structuredContent']['error']['code'],'INVALID_INPUT')
        for line in logs.getvalue().splitlines():
            self.assertEqual(set(json.loads(line)),{'tool','time','status'})
        self.assertNotIn('private@example.test',logs.getvalue())

    def test_embedded_http_reads_supplied_authority_without_stdin(self):
        import mcp_server as m
        import json, urllib.request
        self.assertTrue(hasattr(m,'start_http'),'headless authority HTTP embedding missing')
        service=m.Service();service.publish({'accounts':[]})
        server=m.start_http(service,port=0)
        try:
            url=f'http://127.0.0.1:{server.server_port}/mcp'
            req=urllib.request.Request(url,data=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'ai_accounts_summary','arguments':{}}}).encode(),headers={'Content-Type':'application/json'})
            result=json.load(urllib.request.urlopen(req,timeout=3))
            self.assertEqual(result['result']['structuredContent']['providers']['codex']['ready_accounts'],[])
        finally:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()

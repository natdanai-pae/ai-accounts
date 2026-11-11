import asyncio,json,os,subprocess,sys,time,socket
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
ROOT=Path(__file__).resolve().parent
async def smoke(endpoint):
 async with streamable_http_client(endpoint) as streams:
  async with ClientSession(streams[0],streams[1]) as session:
   await session.initialize()
   names=[t.name for t in (await session.list_tools()).tools]
   assert set(names)=={'ai_accounts_status','ai_accounts_recommend','ai_accounts_summary'}
   results={}
   for provider in ('codex','claude'):
    status=await session.call_tool('ai_accounts_status',{'provider':provider})
    data=status.structured_content
    assert not status.is_error and len(data['accounts'])==3
    assert all(a['quota_used_percent']+a['quota_remaining_percent']==100 for a in data['accounts'])
    recommend=await session.call_tool('ai_accounts_recommend',{'provider':provider,'task_kind':'review'})
    assert recommend.structured_content['recommended_account']['account_number']==2
    results[provider]={'accounts':len(data['accounts']),'recommended_account':2}
   summary=await session.call_tool('ai_accounts_summary',{})
   assert not summary.is_error
   results['summary']=summary.structured_content
   bad=await session.call_tool('ai_accounts_status',{'provider':'invalid'})
   assert bad.is_error
   return results
if __name__=='__main__':
 p=subprocess.Popen([sys.executable,'-c','import mcp_server; mcp_server.serve(port=0)'],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 try:
  handshake=json.loads(p.stdout.readline());endpoint=handshake['endpoint'];now=time.time()
  snapshot={'accounts':[{'provider':provider,'number':i,'email':'private@example.test','used':used,'checked':now,'reset':now+86400} for provider in ('codex','claude') for i,used in ((1,22),(2,50),(3,99))], 'recommendations':{provider:{'number':2,'reason':'Same UI snapshot recommendation','evaluated_at':now} for provider in ('codex','claude')}}
  p.stdin.write(json.dumps(snapshot)+'\n');p.stdin.flush();time.sleep(.1)
  results=asyncio.run(smoke(endpoint));print(json.dumps(results,indent=2))
  import urllib.request,urllib.error
  for params in (None, [], 'private@example.test', 42):
   request=urllib.request.Request(endpoint,data=json.dumps({'jsonrpc':'2.0','id':7,'method':'tools/call','params':params}).encode(),headers={'Content-Type':'application/json'})
   with urllib.request.urlopen(request,timeout=3) as response:
    error=json.load(response)['result']
    assert error['isError'] and error['structuredContent']['error']['code']=='INVALID_INPUT'
  for headers in ({'Origin':'https://evil.test'},{'Host':'evil.test:47831'}):
   try:urllib.request.urlopen(urllib.request.Request(endpoint,data=b'{}',headers={'Content-Type':'application/json',**headers}));raise AssertionError('Origin/Host accepted')
   except urllib.error.HTTPError as e:assert e.code==403
 finally:
  p.stdin.close();p.wait(timeout=5)
 logs=p.stderr.read()
 assert 'private@example.test' not in logs and 'Same UI snapshot' not in logs
 for line in logs.splitlines():assert set(json.loads(line))=={'tool','time','status'}
 from urllib.parse import urlsplit
 with socket.socket() as s:assert s.connect_ex(('127.0.0.1',urlsplit(endpoint).port))!=0
 print('PASS official MCP SDK2.3.0 initialize/list/call all three tools, both providers x3, invalid input, Host/Origin denial, safe logs and stdin-EOF endpoint shutdown.')

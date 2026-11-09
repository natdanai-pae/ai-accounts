"""Read-only MCP projection of the UI's live snapshot. No provider imports or calls."""
import copy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import re
import sys
import threading
import time

PORT=47831
ENDPOINT=f'http://127.0.0.1:{PORT}/mcp'
PROTOCOLS=('2025-06-18','2025-03-26','2025-11-25')
TASKS=('chat','implementation','review','vision','integration')
class InputError(Exception): pass

def stamp(value):
    try:return datetime.fromtimestamp(value,timezone.utc).isoformat().replace('+00:00','Z') if numeric(value) else None
    except (ValueError,OverflowError,OSError):return None

def numeric(value):return type(value) in (float,int) and math.isfinite(value)

def masked(value):
    if not isinstance(value,str) or not re.fullmatch(r'[^\s@]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',value):return None
    local,domain=value.split('@');return local[0]+'***@'+domain

def safe_text(value):
    if not isinstance(value,str):return ''
    # Free text from AI/provider is never trusted as already sanitized.
    if re.search(r'(?i)(token|cookie|bearer|authorization|credential|session|password|secret|api[_ -]?key|sk-[\w-]+|/Users/|/home/|[A-Z]:[\\/]|refresh[_ -]?token)',value):
        return 'Explanation withheld by privacy filter; see the app.'
    value=re.sub(r'\b(?:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|[A-Za-z0-9_=-]{32,})\b','[masked identifier]',value,flags=re.I)
    return re.sub(r'[^\s@]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',lambda x:masked(x.group()) or '[masked]',value)[:1500]

def schemas():
    def schema(props,required=()):return {'type':'object','properties':props,'required':list(required),'additionalProperties':False}
    provider=lambda all=False:{'type':'string','enum':['codex','claude']+(['all'] if all else [])}
    definitions=[('ai_accounts_status','Read the same quota snapshot displayed by AI Accounts; never refresh.',schema({'provider':dict(provider(True),default='all')})),
      ('ai_accounts_recommend','Read the UI recommendation. task_kind is informational; no dispatch occurs.',schema({'provider':provider(),'task_kind':{'type':'string','enum':list(TASKS)}},['provider'])),
      ('ai_accounts_summary','Compact read-only account and recommendation summary.',schema({}))]
    return [{'name':n,'description':d,'inputSchema':s,'annotations':{'readOnlyHint':True,'destructiveHint':False,'idempotentHint':True,'openWorldHint':False}} for n,d,s in definitions]

class Service:
    def __init__(self):self.lock=threading.Lock();self.snapshot={'accounts':[],'recommendations':{}}
    def publish(self,value):
        if not isinstance(value,dict):raise InputError()
        accounts=[]
        source=value.get('accounts',[])
        if not isinstance(source,list):raise InputError()
        for a in source[:1000]:
            if not isinstance(a,dict) or a.get('provider') not in ('codex','claude') or type(a.get('number')) is not int or not 1<=a['number']<=100000:continue
            used=a.get('used'); used=used if numeric(used) and 0<=used<=100 else None
            primary=a.get('primary_used');primary=primary if numeric(primary) and 0<=primary<=100 else None
            accounts.append({'provider':a['provider'],'number':a['number'],'identity':masked(a.get('email')),'used':used,'primary_used':primary,
                'primary_present':a.get('primary_present') is True,'primary_reset':a.get('primary_reset') if numeric(a.get('primary_reset')) else None,
                'checked':a.get('checked') if numeric(a.get('checked')) else None,'reset':a.get('reset') if numeric(a.get('reset')) else None,'error':a.get('error') is True})
        recommendations={}
        recs=value.get('recommendations',{})
        for p in ('codex','claude'):
            r=recs.get(p,{}) if isinstance(recs,dict) else {}
            if isinstance(r,dict) and type(r.get('number')) is int:
                recommendations[p]={'number':r['number'],'reason':safe_text(r.get('reason')),'evaluated_at':r.get('evaluated_at') if numeric(r.get('evaluated_at')) else None}
        with self.lock:self.snapshot={'accounts':accounts,'recommendations':recommendations,'refreshing':value.get('refreshing') is True}
    def call(self,name,args,now=None):
        now=time.time() if now is None else now
        definitions={x['name']:x['inputSchema'] for x in schemas()}
        if not isinstance(name,str) or name not in definitions or not isinstance(args,dict):raise InputError()
        schema=definitions[name]
        if set(args)-set(schema['properties']) or any(x not in args for x in schema['required']):raise InputError()
        for k,v in args.items():
            if not isinstance(v,str) or v not in schema['properties'][k]['enum']:raise InputError()
        with self.lock:s=copy.deepcopy(self.snapshot)
        rows=[]
        for a in s['accounts']:
            fresh=a['checked'] is not None and -60<=now-a['checked']<=900
            valid=a['used'] is not None and a['reset'] is not None and a['reset']>now
            primary_valid=not a['primary_present'] or (a['primary_used'] is not None and a['primary_reset'] is not None and a['primary_reset']>now)
            used=a['used'];remaining=100-used if used is not None else None
            availability='unknown'
            if a['error']: availability='error'
            elif s['refreshing']:availability='refreshing'
            elif a['checked'] is not None and not fresh:availability='stale'
            elif not valid or not primary_valid or not fresh:availability='unknown'
            elif used==100 or a['primary_used']==100:availability='exhausted'
            elif used>=90 or (a['primary_used'] is not None and a['primary_used']>=90):availability='near_limit'
            else:availability='ready'
            rows.append({'provider':a['provider'],'account_number':a['number'],'account_alias':f'Account {a["number"]}','identity_masked':a['identity'],
             'availability':availability,'quota_used_percent':used,'quota_remaining_percent':remaining,'quota_checked_at':stamp(a['checked']),
             'quota_reset_at':stamp(a['reset']),'quota_reset_in_seconds':max(0,int(a['reset']-now)) if a['reset'] else None,'data_fresh':fresh,
             'note':'Weekly quota. used=consumed; remaining=100-used. Primary window also gates availability when supplied. No refresh or dispatch.'})
        def recommend(provider):
            r=s['recommendations'].get(provider); row=next((a for a in rows if a['provider']==provider and r and a['account_number']==r['number']),None)
            valid=row and row['availability'] in ('ready','near_limit') and r['evaluated_at'] is not None and -60<=now-r['evaluated_at']<=900
            return {'recommended_account':row if valid else None,'availability':row['availability'] if row else 'unknown',
              'quota_remaining_percent':row['quota_remaining_percent'] if valid else None,
              'reason':r['reason'] if valid else 'No fresh usable recommendation from the app; no account inferred.',
              'evaluated_at':stamp(r['evaluated_at']) if r else None,
              'alternatives':[a for a in rows if a['provider']==provider and (not row or a['account_number']!=row['account_number'])],
              'can_dispatch':bool(valid),'dispatch_note':'Readiness signal only; this server cannot dispatch or switch. task_kind does not alter UI ranking.'}
        if name=='ai_accounts_status':return {'accounts':[a for a in rows if args.get('provider','all') in ('all',a['provider'])]}
        if name=='ai_accounts_recommend':return recommend(args['provider'])
        latest=max((a['quota_checked_at'] for a in rows if a['quota_checked_at']),default=None)
        return {'providers':{p:{'ready_accounts':[a['account_number'] for a in rows if a['provider']==p and a['availability']=='ready'],
            'recommended_account':recommend(p)['recommended_account'],
            'attention_accounts':[{'account_number':a['account_number'],'availability':a['availability']} for a in rows if a['provider']==p and a['availability']!='ready']} for p in ('codex','claude')},
            'quota_checked_at':latest,'warning':'Some data is stale, unknown, refreshing or errored; no automatic refresh.' if not rows or any(not a['data_fresh'] or a['availability'] in ('unknown','error','refreshing') for a in rows) else None}
    def rpc(self,message):
        if not isinstance(message,dict) or message.get('jsonrpc')!='2.0':return {'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Invalid request'}}
        ident=message.get('id');method=message.get('method');params=message.get('params',{})
        if ident is not None and type(ident) not in (str,int):return {'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Invalid request id'}}
        if ident is None:return None
        result=None;error=None
        if method=='initialize':
            version=params.get('protocolVersion') if isinstance(params,dict) else None
            result={'protocolVersion':version if version in PROTOCOLS else PROTOCOLS[0],'capabilities':{'tools':{}},'serverInfo':{'name':'ai-accounts','version':'0.4.0'}}
        elif method=='ping':result={}
        elif method=='tools/list':result={'tools':schemas()}
        elif method=='tools/call':
            name=params.get('name') if isinstance(params,dict) else None
            try:
                value=self.call(name,params.get('arguments',{}));result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=True)}],'structuredContent':value,'isError':False}
            except InputError:result={'content':[{'type':'text','text':'{"error":{"code":"INVALID_INPUT","message":"Unknown tool or invalid allowlisted input"}}'}],'structuredContent':{'error':{'code':'INVALID_INPUT','message':'Unknown tool or invalid allowlisted input'}},'isError':True}
            # Never log caller-provided names or values.
            print(json.dumps({'tool':name if isinstance(name,str) and name in {t['name'] for t in schemas()} else 'invalid','time':stamp(time.time()),'status':'error' if result['isError'] else 'ok'}),file=sys.stderr,flush=True)
        else:error={'code':-32601,'message':'Method not found'}
        return {'jsonrpc':'2.0','id':ident,**({'error':error} if error else {'result':result})}

def serve(port=PORT):
    service=Service()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,code,value=None):
            raw=json.dumps(value,ensure_ascii=True).encode() if value is not None else b''
            self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def permitted(self):
            return self.path=='/mcp' and self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}' and (not self.headers.get('Origin') or self.headers.get('Origin')==f'http://127.0.0.1:{self.server.server_port}')
        def do_GET(self):self.reply(405 if self.permitted() else 403)
        def do_DELETE(self):self.reply(405 if self.permitted() else 403)
        def do_POST(self):
            if not self.permitted():self.reply(403);return
            if self.headers.get('MCP-Protocol-Version',PROTOCOLS[0]) not in PROTOCOLS:self.reply(400);return
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':self.reply(415);return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=65536:raise ValueError()
                message=json.loads(self.rfile.read(size));result=service.rpc(message)
                self.reply(202 if result is None else 200,result)
            except (ValueError,TypeError):self.reply(400,{'error':{'code':'INVALID_REQUEST','message':'Invalid JSON request'}})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
    threading.Thread(target=server.serve_forever,daemon=True).start()
    print(json.dumps({'status':'running','endpoint':f'http://127.0.0.1:{server.server_port}/mcp'}),flush=True)
    try:
        for line in sys.stdin:
            if len(line)>1024*1024:continue
            try:service.publish(json.loads(line))
            except (ValueError,TypeError,InputError):pass
    finally:server.shutdown();server.server_close()

if __name__=='__main__':serve()

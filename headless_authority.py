"""Linux AI Accounts authority: shared advisor, sticky decisions, metadata-only MCP.

Collection and inference are explicit publisher operations. MCP reads never invoke
those operations or rotate credentials. No desktop store or Mac endpoint is used.
"""
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

import ai_advisor
from backend import SafeError
from mcp_server import Service, InputError, numeric, safe_text, stamp

PROVIDERS=('codex','claude')
QUOTA_TTL=240
DECISION_TTL=900


def router_records(state, now=None):
    """Project native router metadata; never open a profile/credential store.

    A local number is a display number in GX10's namespace, not a mapping from
    any Mac account. Native expected_identity is hashed for private binding and
    is never sent to inference or returned by MCP.
    """
    now=time.time() if now is None else now
    if not isinstance(state,dict):raise SafeError('Invalid local quota metadata')
    rows=[]
    for alias,meta in state.items():
        match=re.fullmatch(r'(codex|claude)-([1-9][0-9]{0,4})',alias) if isinstance(alias,str) else None
        if not match or not isinstance(meta,dict):continue
        provider,number=match[1],int(match[2])
        windows=meta.get('windows_used_percent',{})
        resets=meta.get('windows_reset_epoch',{})
        windows=windows if isinstance(windows,dict) else {}
        resets=resets if isinstance(resets,dict) else {}
        identity=meta.get('expected_identity')
        checked=meta.get('checked_epoch')
        expires=meta.get('expires_epoch')
        identity_verified=(isinstance(identity,str) and bool(identity) and not meta.get('identity_quarantined')
            and meta.get('availability') in ('ready','near_limit_paused') and numeric(expires) and expires>now+60
            and not meta.get('error'))
        # All reported binding windows must be valid, even if absent in the
        # display's weekly/primary shape. Unknown windows are never invented.
        windows_valid=bool(windows) and all(numeric(v) and 0<=v<=100 and numeric(resets.get(k)) and resets[k]>now for k,v in windows.items())
        rows.append({'provider':provider,'account_ref':provider+'-'+str(number),'number':number,
            'used':windows.get('weekly'),'checked':checked,'reset':resets.get('weekly'),
            'primary_present':'five_hour' in windows,'primary_used':windows.get('five_hour'),
            'primary_reset':resets.get('five_hour'),'identity_verified':bool(identity_verified),
            'identity_binding':hashlib.sha256(identity.encode()).hexdigest() if isinstance(identity,str) and identity else None,
            'windows_valid':windows_valid,'binding_used':max(windows.values()) if windows_valid else None,
            'error':bool(meta.get('error'))})
    return rows


def _allowed_record(row):
    if not isinstance(row,dict) or row.get('provider') not in PROVIDERS or type(row.get('number')) is not int or not 1<=row['number']<=100000:
        return None
    ref=row.get('account_ref')
    if not isinstance(ref,str) or not re.fullmatch(r'(codex|claude)-[1-9][0-9]{0,5}',ref) or ref!=row['provider']+'-'+str(row['number']):
        return None
    out={key:row.get(key) for key in ('provider','account_ref','number','used','checked','reset','primary_used','primary_reset','binding_used','identity_binding')}
    out.update(primary_present=row.get('primary_present') is True,identity_verified=row.get('identity_verified') is True,
        windows_valid=row.get('windows_valid',True) is True,error=row.get('error') is True)
    for key in ('used','primary_used','binding_used'):
        if not numeric(out[key]) or not 0<=out[key]<=100:out[key]=None
    for key in ('checked','reset','primary_reset'):
        if not numeric(out[key]):out[key]=None
    binding=out['identity_binding'] or row.get('identity_fingerprint')
    out['identity_binding']=binding
    if not isinstance(binding,str) or not re.fullmatch(r'[a-f0-9]{64}',binding):out['identity_binding']=None;out['identity_verified']=False
    return out


def _usable(row,now):
    return bool(row and row['identity_verified'] and row['identity_binding'] and not row['error'] and row['windows_valid']
        and numeric(row['checked']) and 0<=now-row['checked']<=QUOTA_TTL
        and numeric(row['used']) and 0<=row['used']<100 and numeric(row['reset']) and row['reset']>now
        and (row['binding_used'] is None or row['binding_used']<100)
        and (not row['primary_present'] or (numeric(row['primary_used']) and 0<=row['primary_used']<100 and numeric(row['primary_reset']) and row['primary_reset']>now)))


class Authority(Service):
    def __init__(self,state_file):
        super().__init__()
        self.authority_lock=threading.RLock()
        self.state_file=Path(state_file)
        self.records=[]
        self.decisions={}
        self.reload_decisions()

    def reload_decisions(self):
        """Load only prior validated metadata; does not renew a decision's age."""
        try:
            if self.state_file.stat().st_size>1024*1024:return
            saved=json.loads(self.state_file.read_text(encoding='utf-8'))
            if saved.get('version')==1 and isinstance(saved.get('decisions'),dict):
                decisions={provider:value for provider,value in saved['decisions'].items()
                    if provider in PROVIDERS and self._decision_valid_shape(value,provider)}
                with self.authority_lock:self.decisions=decisions
        except (OSError,ValueError,TypeError,AttributeError):pass

    @staticmethod
    def _decision_valid_shape(value,provider):
        return (isinstance(value,dict) and value.get('provider')==provider and value.get('source')=='ai'
            and isinstance(value.get('account_ref'),str) and re.fullmatch(provider+r'-[1-9][0-9]{0,5}',value['account_ref'])
            and type(value.get('number')) is int and value['account_ref']==provider+'-'+str(value['number'])
            and isinstance(value.get('decision_id'),str) and re.fullmatch(r'[a-f0-9]{32}',value['decision_id'])
            and isinstance(value.get('identity_binding'),str) and re.fullmatch(r'[a-f0-9]{64}',value['identity_binding'])
            and numeric(value.get('generated_epoch')) and numeric(value.get('expires_epoch'))
            and 0<value['expires_epoch']-value['generated_epoch']<=DECISION_TTL
            and isinstance(value.get('reason'),str) and value['reason']==safe_text(value['reason']))

    def publish(self,records):
        if not isinstance(records,list):raise InputError()
        projected=[];refs=set()
        for value in records[:1000]:
            row=_allowed_record(value)
            if row and row['account_ref'] not in refs:projected.append(row);refs.add(row['account_ref'])
        with self.authority_lock:
            self.records=projected
            # Recommendations are set only by analyze, never by quota order.
            super().publish({'accounts':projected,'recommendations':{}})

    def analyze(self,infer,now=None):
        """Explicit, lease-protected scheduler entry; a callback owns CLI access."""
        started=time.time() if now is None else now
        with self.authority_lock:records=copy.deepcopy(self.records)
        eligible=[r for r in records if _usable(r,started)]
        accounts=[{'id':r['account_ref'],'provider':r['provider'],'email':None,'usageAccount':r['account_ref']} for r in eligible]
        rows=[]
        for r in eligible:
            usage={'updatedAt':stamp(r['checked']),'secondary':{'usedPercent':r['used'],'resetsAt':stamp(r['reset'])}}
            if r['primary_present']:usage['primary']={'usedPercent':r['primary_used'],'resetsAt':stamp(r['primary_reset'])}
            rows.append({'provider':r['provider'],'account':r['account_ref'],'usage':usage})
        snapshot,mapping=ai_advisor.build_snapshot(accounts,rows,datetime.fromtimestamp(started,timezone.utc),{r['account_ref']:r['number'] for r in eligible})
        answer=infer(snapshot)
        completed=time.time() if now is None else now
        checked=ai_advisor.validate_answer(answer,snapshot,mapping,datetime.fromtimestamp(completed,timezone.utc))
        chosen={r['account_ref']:r for r in eligible}
        with self.authority_lock:
            current={r['account_ref']:r for r in self.records}
            decisions=copy.deepcopy(self.decisions)
            for result in checked['recommendations']:
                ref=result['account'];row=current.get(ref)
                if not _usable(row,completed) or row['identity_binding']!=chosen[ref]['identity_binding']:
                    raise SafeError('Local quota or account identity changed during AI analysis')
                reason=safe_text(result['reason'])
                if reason!=result['reason']:raise SafeError('AI explanation failed privacy validation')
                decisions[result['provider']]={'provider':result['provider'],'account_ref':ref,'number':row['number'],
                    'source':'ai','decision_id':uuid.uuid4().hex,'generated_epoch':completed,'expires_epoch':completed+DECISION_TTL,
                    'reason':reason,'identity_binding':row['identity_binding']}
            payload={'version':1,'decisions':decisions}
            self._save(payload)
            self.decisions=decisions
        return {'ok':True,'providers':sorted(r['provider'] for r in checked['recommendations'])}

    def _save(self,value):
        self.state_file.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        temporary=self.state_file.with_name(self.state_file.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with temporary.open('x',encoding='utf-8') as stream:
                os.chmod(temporary,0o600);json.dump(value,stream,ensure_ascii=True);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,self.state_file)
        finally:
            try:temporary.unlink()
            except FileNotFoundError:pass

    def call(self,name,args,now=None):
        with self.authority_lock:
            return self._call_locked(name,args,now)

    def _call_locked(self,name,args,now=None):
        now=time.time() if now is None else now
        # Preserve the existing shared allowlist/input validation and account
        # projection rather than a second MCP protocol implementation.
        super().call(name,args,now=now)
        with self.authority_lock:
            records=copy.deepcopy(self.records);decisions=copy.deepcopy(self.decisions)
        rows=super().call('ai_accounts_status',{},now=now)['accounts']
        by_ref={r['account_ref']:r for r in records}
        for row in rows:
            ref=row['provider']+'-'+str(row['account_number']);raw=by_ref[ref]
            fresh=numeric(raw['checked']) and 0<=now-raw['checked']<=QUOTA_TTL
            row['data_fresh']=fresh
            if not raw['identity_verified'] or not raw['identity_binding'] or not raw['windows_valid']:
                row['availability']='unknown' if not raw['error'] else 'error'
            elif not fresh:row['availability']='stale'
            elif raw['binding_used']==100:row['availability']='exhausted'
            row['note']='GX10-local weekly quota; used=consumed, remaining=100-used. Known binding windows and verified local identity gate readiness. No refresh or dispatch.'
        def recommend(provider):
            decision=decisions.get(provider)
            ref=decision['account_ref'] if decision else None
            row=next((r for r in rows if r['provider']==provider and r['account_number']==decision['number']),None) if decision else None
            raw=by_ref.get(ref)
            valid=bool(decision and row and _usable(raw,now) and raw['identity_binding']==decision['identity_binding']
                and decision['generated_epoch']<=now<decision['expires_epoch'])
            return {'recommended_account':row if valid else None,'availability':row['availability'] if row else 'unknown',
                'quota_remaining_percent':row['quota_remaining_percent'] if valid else None,
                'reason':decision['reason'] if valid else 'No fresh validated AI decision for this local account; queued without fallback.',
                'evaluated_at':stamp(decision['generated_epoch']) if decision else None,
                'alternatives':[r for r in rows if r['provider']==provider and (not row or r['account_number']!=row['account_number'])],
                'can_dispatch':valid,'dispatch_note':'Readiness only. Pool retains account until a new validated AI decision; no automatic balancing.',
                'account_ref':ref,'source':'ai' if decision else None,'generated_at':stamp(decision['generated_epoch']) if decision else None,'expires_at':stamp(decision['expires_epoch']) if decision else None,'decision_id':decision['decision_id'] if decision else None,'decision_source':'ai' if decision else None,
                'decision_generated_at':stamp(decision['generated_epoch']) if decision else None,'decision_expires_at':stamp(decision['expires_epoch']) if decision else None}
        if name=='ai_accounts_status':return {'accounts':[r for r in rows if args.get('provider','all') in ('all',r['provider'])]}
        if name=='ai_accounts_recommend':return recommend(args['provider'])
        return {'providers':{p:{'ready_accounts':[r['account_number'] for r in rows if r['provider']==p and r['availability']=='ready'],
            'recommended_account':recommend(p)['recommended_account'],'decision_id':recommend(p)['decision_id'],
            'decision_source':recommend(p)['decision_source'],'decision_expires_at':recommend(p)['decision_expires_at'],
            'attention_accounts':[{'account_number':r['account_number'],'availability':r['availability']} for r in rows if r['provider']==p and r['availability']!='ready']} for p in PROVIDERS},
            'quota_checked_at':max((r['quota_checked_at'] for r in rows if r['quota_checked_at']),default=None),
            'warning':'Some local quota data or AI decisions are unavailable; queued without fallback.' if any(not recommend(p)['can_dispatch'] for p in PROVIDERS) else None}

#!/usr/bin/env python3
"""GX10-local scheduled metadata publisher and shared AI advisor host.

No collection or inference is called by MCP request handlers. This process owns
its scheduling and reads only the native router's metadata, never credentials.
The existing router exclusively owns native identity/token handling and leases.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

import ai_advisor
from backend import SafeError
from headless_authority import Authority, router_records, _usable
from mcp_server import stamp


def read_metadata(path):
    path=Path(path)
    if path.stat().st_size>1024*1024:raise SafeError('Local metadata is too large')
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict):raise SafeError('Local metadata is invalid')
    return value


class InferenceBackend:
    def __init__(self,executable,resources):
        self.root=Path.home()
        self.resources=Path(resources)
        self.codex_executable=Path(executable)
    def executable(self,name):
        if name!='codex':raise SafeError('Unsupported inference executable')
        return str(self.codex_executable)


def leased_infer(router,state_source,executable,resources=None,clock=time.time,infer_function=ai_advisor.infer):
    """Use the existing codex-1 native home under its exclusive maintenance lease.

    Token refresh, if needed, remains within the official CLI and its original
    local home. No profile copy, Mac credential, API key or fallback is used.
    """
    backend=InferenceBackend(executable,resources or Path(__file__).parent)
    def infer(snapshot):
        with router.leases('codex-1',maintenance=True):
            now=clock();metadata=read_metadata(state_source)
            record=next((r for r in router_records(metadata,now=now) if r['account_ref']=='codex-1'),None)
            if not _usable(record,now):raise SafeError('Local inference account is unavailable')
            native=router.native_identity('codex-1')
            expected=metadata.get('codex-1',{}).get('expected_identity')
            if not isinstance(native,str) or not expected or native!=expected:
                raise SafeError('Local inference identity does not match its verified pin')
            return infer_function(backend,snapshot)
    return infer


class Scheduler:
    def __init__(self,authority,collect,infer,poll_seconds=15,analysis_seconds=600,now=None,analyze_on_start=False):
        if not 5<=poll_seconds<=120 or not 120<=analysis_seconds<=900:raise ValueError('Invalid scheduler interval')
        now=time.time() if now is None else now
        self.authority=authority;self.collect=collect;self.infer=infer
        self.poll_seconds=poll_seconds;self.analysis_seconds=analysis_seconds
        self.next_poll=now;self.next_analysis=now if analyze_on_start else now+analysis_seconds
    def tick(self,now=None):
        now=time.time() if now is None else now
        result={}
        if now>=self.next_poll:
            self.next_poll=now+self.poll_seconds
            self.authority.reload_decisions()
            try:self.authority.publish(self.collect());result['collection']='updated'
            except (SafeError,OSError,ValueError,TypeError,RuntimeError):result['collection']='deferred'
        if now>=self.next_analysis:
            self.next_analysis=now+self.analysis_seconds
            try:self.authority.analyze(self.infer);result['analysis']='updated'
            except (SafeError,OSError,ValueError,TypeError,RuntimeError):result['analysis']='deferred'
        return result


def load_router(path):
    path=Path(path).resolve()
    if not path.is_file():raise SafeError('Native router module unavailable')
    spec=importlib.util.spec_from_file_location('ai_accounts_native_router',path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    if not callable(getattr(module,'leases',None)) or not callable(getattr(module,'native_identity',None)):
        raise SafeError('Native router lease/identity API unavailable')
    return module


def main(argv=None):
    parser=argparse.ArgumentParser(description='GX10-local AI Accounts authority; no Mac dependency')
    parser.add_argument('--state-source',type=Path,default=Path.home()/'ai-pool-pilot/state/quota-router/accounts.json')
    parser.add_argument('--decision-state',type=Path,default=Path.home()/'.local/state/ai-accounts/decision.json')
    parser.add_argument('--router-module',type=Path,default=Path.home()/'ai-pool-pilot/bin/pilot_router.py')
    parser.add_argument('--codex-executable',type=Path,default=Path.home()/'.local/lib/codex/0.162.1/bin/codex')
    parser.add_argument('--port',type=int,default=47831)
    parser.add_argument('--poll-seconds',type=int,default=15)
    parser.add_argument('--analysis-seconds',type=int,default=600)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run',action='store_true')
    mode.add_argument('--once-analysis',action='store_true')
    parser.add_argument('--analyze-on-start',action='store_true')
    args=parser.parse_args(argv)
    if not 1024<=args.port<=65535:parser.error('Invalid loopback port')
    if not args.codex_executable.is_absolute() or not args.codex_executable.is_file() or not os.access(args.codex_executable,os.X_OK):
        raise SafeError('Verified local Codex executable unavailable')
    router=load_router(args.router_module)
    authority=Authority(args.decision_state)
    collect=lambda:router_records(read_metadata(args.state_source))
    infer=leased_infer(router,args.state_source,args.codex_executable)
    if args.once_analysis:
        authority.publish(collect());authority.analyze(infer)
        print(json.dumps({'tool':'publisher','time':stamp(time.time()),'status':'analysis_updated'}),flush=True)
        return
    scheduler=Scheduler(authority,collect,infer,args.poll_seconds,args.analysis_seconds,analyze_on_start=args.analyze_on_start)
    from mcp_server import start_http
    server=start_http(authority,args.port)
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    print(json.dumps({'tool':'publisher','time':stamp(time.time()),'status':'running'}),flush=True)
    try:
        while not stop.is_set():
            outcomes=scheduler.tick()
            for operation,status in outcomes.items():
                print(json.dumps({'tool':'publisher_'+operation,'time':stamp(time.time()),'status':status}),flush=True)
            stop.wait(1)
    finally:
        server.shutdown();server.server_close()


if __name__=='__main__':
    try:main()
    except (SafeError,OSError,ValueError,RuntimeError):
        print(json.dumps({'tool':'publisher','time':stamp(time.time()),'status':'stopped_error'}),file=sys.stderr,flush=True)
        raise SystemExit(1)

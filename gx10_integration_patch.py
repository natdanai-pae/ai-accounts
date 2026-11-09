"""Bounded source transforms for the inspected GX10 routing entry points."""
import re

def replace_once(text,old,new):
    if text.count(old)!=1:raise ValueError('Runtime changed; reconcile before patching')
    return text.replace(old,new,1)

BOOT='''\n# AI Accounts is the sole subscription-account selection authority.\nimport sys\nsys.path.insert(0, str(Path.home() / '.local/lib/ai-accounts/current'))\nfrom pool_authority import read_recommendation, select_route, decision_proof, AuthorityUnavailable, local_identity_matches\nAI_ACCOUNTS_POLICY = 'ai_accounts_sticky_v1'\n'''

def patch_chat(text):
    start=text.index('def rank(') if 'def rank(' in text else -1
    end=text.index('\n\ndef no_duplicates(',start) if start>=0 and '\n\ndef no_duplicates(' in text[start:] else -1
    if start<0 or end<0:raise ValueError('Unknown chat selection implementation')
    text=replace_once(text,'TTL = 240','TTL = 240\n'+BOOT+'\nAUTHORITY_CONTEXT = threading.local()')
    start=text.index('def rank(');end=text.index('\n\ndef no_duplicates(',start)
    text=text[:start]+'''def rank(state, model, now=None, active=None, prefer=None):
    now = time.time() if now is None else now
    provider = MODELS.get(model)
    AUTHORITY_CONTEXT.proof = None
    if not provider:
        return []
    try:
        advice = read_recommendation(provider, now)
        candidates = []
        for alias in PROFILES:
            r = state.get(alias, {})
            if not alias.startswith(provider + '-'):
                continue
            used = r.get('windows_used_percent', {})
            checked, expires = r.get('checked_epoch'), r.get('expires_epoch')
            valid = (type(checked) in (int,float) and 0 <= now-checked <= TTL
                and type(expires) in (int,float) and expires > now+60
                and bool(r.get('expected_identity')) and not r.get('identity_quarantined')
                and not r.get('error') and r.get('availability') in ('ready','near_limit_paused')
                and isinstance(used,dict) and bool(used)
                and all(type(v) in (int,float) and math.isfinite(v) and 0 <= v < 100 for v in used.values()))
            count = (active(alias) if active else sum(busy('route-'+alias+'-slot-'+str(i)) for i in range(5)))
            candidates.append({'id':alias,'provider':provider,'availability':'ready' if valid else 'unknown',
                'quota_stale':not valid,'quota_error':r.get('error'),'identity_quarantined':r.get('identity_quarantined',False),
                'active_jobs':count,'capacity':5,'quota':{k:{'used_percent':v} for k,v in used.items()} if isinstance(used,dict) else {}})
        chosen = select_route(candidates,provider,now,advice,eligible=lambda row:local_identity_matches(advice,state[row['id']].get('expected_identity')))
        AUTHORITY_CONTEXT.proof = decision_proof(advice,provider,now)
        alias=chosen['id'];r=state[alias]
        return [(alias,min(100-v for v in r['windows_used_percent'].values()),chosen['active_jobs'],r.get('last_selected_epoch',0))]
    except AuthorityUnavailable:
        return []
''' +text[end:]
    text=replace_once(text,"'result_verified': False}","'result_verified': False, 'controller_decision': getattr(AUTHORITY_CONTEXT, 'proof', None)}")
    text=replace_once(text,"self.send_header('X-BDA-Account', alias)","self.send_header('X-BDA-Account', alias)\n                self.send_header('X-AI-Accounts-Decision', receipt['controller_decision']['decision_id'])")
    # Do not poll/refresh every provider synchronously on a service handover.
    # Existing collector loop remains; its previous fresh state is retained.
    text=replace_once(text,'    else:\n        maintain()\n        def loop():','    else:\n        def loop():')
    return text

def patch_worker(text):
    if 'def apply(compat' not in text or 'def choose(candidates' not in text:raise ValueError('Unknown worker implementation')
    text=replace_once(text,'TTL = 240','TTL = 240\n'+BOOT)
    text=replace_once(text,"ready = valid and data.get('availability') == 'ready' and not data.get('error')", "ready = (valid and data.get('availability') in ('ready','near_limit_paused') and not data.get('error')\n                     and bool(data.get('expected_identity')) and not data.get('identity_quarantined')\n                     and max(values.values()) < 100)")
    text=replace_once(text,"availability=('near_limit_paused' if maximum is not None and maximum >= 90 else 'ready' if ready else 'unknown'),","availability=('ready' if ready else 'exhausted' if maximum is not None and maximum >= 100 else 'unknown'),")
    text=replace_once(text,'and headroom(r) > 10]','and headroom(r) > 0]')
    old="""        selected = min(ready, key=lambda r: (
                    -headroom(r)/(r['active_jobs']+1), reset_priority(r), r.get('last_used_at') or '', r['id']))"""
    new="""        model = job.get('model', '') if isinstance(job, dict) else ''
        provider = family or ('codex' if model.startswith('gpt-') or kind in ('vision','integration') else 'claude')
        advice = read_recommendation(provider)
        identity_source = json.loads(state_file.read_text())
        selected = select_route(ready, provider, recommendation=advice, eligible=lambda row: local_identity_matches(advice, identity_source.get(row['id'], {}).get('expected_identity')))
        authority_proof = decision_proof(advice, provider)"""
    text=replace_once(text,old,new)
    text=replace_once(text,"'selection_policy': 'compatible_headroom_load_reset_tiebreak_v2',","**authority_proof,")
    text=replace_once(text,"'version': 'native_refresh_v2', 'job_id': execution.job_id,","'version': 'ai_accounts_sticky_v1', 'job_id': execution.job_id,")
    text=replace_once(text,"compat.CONTROL_PLANE_VERSION = 'native_refresh_v2'","compat.CONTROL_PLANE_VERSION = 'ai_accounts_sticky_v1'")
    return text

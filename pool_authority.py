"""Pool routing follows one local AI Accounts decision; it never ranks accounts."""
from datetime import datetime, timezone
import json
import math
import re
import time
import urllib.error
import urllib.request

ENDPOINT = 'http://127.0.0.1:47831/mcp'
QUOTA_TTL = 240
DECISION_TTL = 900
MAX_RESPONSE = 256 * 1024
PROVIDERS = ('codex', 'claude')
RECOMMEND_FIELDS = {'source', 'decision_id', 'generated_at', 'expires_at', 'account_ref',
    'decision_source', 'decision_generated_at', 'decision_expires_at',
    'recommended_account', 'availability', 'quota_remaining_percent', 'reason',
    'evaluated_at', 'alternatives', 'can_dispatch', 'dispatch_note'}

class AuthorityUnavailable(ValueError):
    """A queueable, sanitized admission failure, never an invitation to rebalance."""
    def __init__(self, code='authority_unavailable'):
        self.code = code
        super().__init__('AI Accounts ' + code + '; queued without account fallback')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _epoch(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def validate_recommendation(response, provider, now=None):
    """Validate provenance and fresh usable quota without selecting an alternative."""
    now = time.time() if now is None else now
    if provider not in PROVIDERS or not _number(now):
        raise AuthorityUnavailable('invalid_provider')
    if not isinstance(response, dict) or set(response) - RECOMMEND_FIELDS:
        raise AuthorityUnavailable('invalid_response')
    alias, ident = response.get('account_ref'), response.get('decision_id')
    if (response.get('source') != 'ai' or not isinstance(ident, str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', ident)
            or not isinstance(alias, str) or not re.fullmatch(provider+r'-[1-9][0-9]{0,3}', alias)):
        raise AuthorityUnavailable('invalid_provenance')
    generated, expiry = _epoch(response.get('generated_at')), _epoch(response.get('expires_at'))
    if (generated is None or expiry is None or not 0 <= now-generated <= DECISION_TTL
            or not now < expiry <= generated+DECISION_TTL):
        raise AuthorityUnavailable('expired_decision')
    row = response.get('recommended_account')
    if (response.get('can_dispatch') is not True or response.get('availability') not in ('ready','near_limit')
            or not isinstance(row, dict) or row.get('provider') != provider
            or type(row.get('account_number')) is not int
            or row['account_number'] != int(alias.split('-')[1])
            or row.get('availability') not in ('ready','near_limit') or row.get('data_fresh') is not True):
        raise AuthorityUnavailable('account_not_ready')
    checked, reset = _epoch(row.get('quota_checked_at')), _epoch(row.get('quota_reset_at'))
    used, remaining = row.get('quota_used_percent'), row.get('quota_remaining_percent')
    if (checked is None or not 0 <= now-checked <= QUOTA_TTL or reset is None or reset <= now
            or not _number(used) or not _number(remaining) or not 0 <= used < 100
            or not 0 < remaining <= 100 or not math.isclose(used+remaining,100,abs_tol=1e-6)
            or response.get('quota_remaining_percent') != remaining):
        raise AuthorityUnavailable('quota_not_fresh_or_usable')
    return response


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _exchange(message):
    """Fixed loopback endpoint, no proxy, redirect, credential or automatic retry."""
    request = urllib.request.Request(ENDPOINT,
        data=json.dumps(message, separators=(',', ':')).encode('utf-8'),
        headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream',
                 'MCP-Protocol-Version':'2025-06-18'}, method='POST')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=2) as result:
        if result.status != 200 or result.headers.get_content_type() != 'application/json':
            raise AuthorityUnavailable('transport_unavailable')
        data = result.read(MAX_RESPONSE+1)
    if len(data) > MAX_RESPONSE:
        raise AuthorityUnavailable('response_too_large')
    return json.loads(data)


def read_recommendation(provider, now=None):
    """Read one stateless MCP response. Never refresh, infer, dispatch or retry."""
    if provider not in PROVIDERS:
        raise AuthorityUnavailable('invalid_provider')
    try:
        reply = _exchange({'jsonrpc':'2.0','id':1,'method':'tools/call',
            'params':{'name':'ai_accounts_recommend','arguments':{'provider':provider}}})
        if (not isinstance(reply, dict) or reply.get('jsonrpc') != '2.0' or reply.get('id') != 1
                or reply.get('error') or not isinstance(reply.get('result'), dict)
                or reply['result'].get('isError') is not False):
            raise AuthorityUnavailable('invalid_mcp_response')
        return validate_recommendation(reply['result'].get('structuredContent'), provider, now)
    except AuthorityUnavailable:
        raise
    except (OSError, ValueError, TypeError, OverflowError):
        raise AuthorityUnavailable('transport_unavailable') from None


def _default_eligible(row):
    # Callers retain stricter model/identity/credential/backoff and native leases.
    if (row.get('availability') != 'ready' or row.get('quota_stale') is not False
            or row.get('quota_error') or row.get('identity_quarantined')):
        return False
    count, capacity = row.get('active_jobs'), row.get('capacity')
    if type(count) is not int or type(capacity) is not int or not 0 <= count < capacity:
        return False
    quota = row.get('quota')
    if not isinstance(quota, dict) or not quota:
        return False
    return all(isinstance(window, dict) and _number(window.get('used_percent'))
               and 0 <= window['used_percent'] < 100 for window in quota.values())


def select_route(candidates, provider, now=None, recommendation=None, eligible=None):
    """Return only the authority-designated existing route, or a queueable failure.

    `eligible` is an additional local identity/model/admission guard. It cannot
    turn a quota-unsafe route into a usable route, nor select another account.
    The caller acquires its unchanged native leases before executing.
    """
    response = (read_recommendation(provider, now) if recommendation is None
                else validate_recommendation(recommendation, provider, now))
    if not isinstance(candidates, (list, tuple)):
        raise AuthorityUnavailable('invalid_candidates')
    matching = [r for r in candidates if isinstance(r, dict)
                and r.get('id') == response['account_ref'] and r.get('provider') == provider]
    if len(matching) != 1:
        raise AuthorityUnavailable('local_identity_mapping_unavailable')
    row = matching[0]
    try:
        allowed = _default_eligible(row) and (eligible is None or eligible(row))
    except Exception:
        raise AuthorityUnavailable('local_guard_unavailable') from None
    if not allowed:
        raise AuthorityUnavailable('selected_account_unavailable')
    return row


def decision_proof(response, provider, now=None):
    value = validate_recommendation(response, provider, now)
    return {'selection_policy':'ai_accounts_sticky_v1','decision_source':'ai',
            'decision_id':value['decision_id'],'account_ref':value['account_ref'],
            'decision_generated_at':value['generated_at'],'decision_expires_at':value['expires_at']}

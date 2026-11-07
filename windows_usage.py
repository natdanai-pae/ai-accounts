"""Read-only provider usage. Credentials never leave fixed provider HTTPS origins."""
import json
import math
from datetime import datetime, timezone
import urllib.request
import urllib.error

LIMIT = 2 * 1024 * 1024

class UsageError(Exception):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise UsageError('Provider redirected; request stopped')

def request_json(url, headers):
    if not url.startswith(('https://chatgpt.com/backend-api/', 'https://claude.ai/api/')):
        raise UsageError('Untrusted provider endpoint')
    request = urllib.request.Request(url, headers={**headers, 'Accept': 'application/json', 'User-Agent': 'AI-Accounts/0.3.0'})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
        raw = response.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise UsageError('Provider response too large')
    return json.loads(raw)

def timestamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        try:
            return datetime.fromtimestamp(value, timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            return None
    return value if isinstance(value, str) else None

def normalize_codex(data, account, email):
    rate = data.get('rate_limit') or {}
    def window(name):
        value = rate.get(name) or {}
        return {'usedPercent': value.get('used_percent'), 'resetsAt': timestamp(value.get('reset_at'))}
    weekly_primary = (rate.get('primary_window') or {}).get('limit_window_seconds') == 604800
    usage = {'accountEmail': email, 'updatedAt': datetime.now(timezone.utc).isoformat(), 'secondary': window('primary_window' if weekly_primary else 'secondary_window')}
    if rate.get('primary_window') is not None and not weekly_primary:
        usage['primary'] = window('primary_window')
    result = {'provider': 'codex', 'account': account, 'usage': usage}
    credits = data.get('credits') or {}
    balance = credits.get('balance')
    try:
        balance = float(balance) if balance is not None else None
    except (ValueError, TypeError):
        balance = None
    if balance is not None and (not math.isfinite(balance) or balance < 0):
        balance = None
    result['credits'] = {'remaining': balance, 'balanceReadSucceeded': balance is not None}
    return result

def normalize_claude(data, account, email):
    week = data.get('seven_day') or {}
    usage = {'accountEmail': email, 'updatedAt': datetime.now(timezone.utc).isoformat(), 'secondary': {'usedPercent': week.get('utilization'), 'resetsAt': timestamp(week.get('resets_at'))}}
    if data.get('five_hour') is not None:
        primary = data['five_hour']
        usage['primary'] = {'usedPercent': primary.get('utilization'), 'resetsAt': timestamp(primary.get('resets_at'))}
    return {'provider': 'claude', 'account': account, 'usage': usage}

def codex_usage(profile, key, email=None):
    from pathlib import Path
    path = Path(profile) / 'auth.json'
    if path.is_symlink() or path.stat().st_size > LIMIT:
        raise UsageError('Invalid credential file')
    tokens = json.loads(path.read_text(encoding='utf-8')).get('tokens') or {}
    token = tokens.get('access_token')
    if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
        raise UsageError('Log in to Codex again')
    headers = {'Authorization': 'Bearer ' + token, 'OpenAI-Beta': 'codex-1', 'originator': 'Codex Desktop'}
    account_id = tokens.get('account_id')
    if isinstance(account_id, str):
        headers['ChatGPT-Account-Id'] = account_id
    result = normalize_codex(request_json('https://chatgpt.com/backend-api/wham/usage', headers), key, email)
    try:
        resets = request_json('https://chatgpt.com/backend-api/wham/rate-limit-reset-credits', headers)
        available = resets.get('available_count')
        if isinstance(available, int) and not isinstance(available, bool) and available >= 0:
            result['resetCredits'] = {'available': available}
    except Exception:
        pass  # Optional reset-credit availability must not hide valid quota data.
    return result

def claude_usage(token, key, email=None):
    import re
    if not isinstance(token, str) or not re.fullmatch(r'sk-ant-[A-Za-z0-9_-]+', token):
        raise UsageError('Connect Claude login again')
    headers = {'Cookie': 'sessionKey=' + token}
    identity = request_json('https://claude.ai/api/account', headers)
    verified_email = identity.get('email_address') or identity.get('email')
    if email and verified_email != email:
        raise UsageError('Claude identity changed; reconnect')
    organizations = request_json('https://claude.ai/api/organizations', headers)
    candidates = [org for org in organizations if isinstance(org, dict) and 'chat' in (org.get('capabilities') or [])]
    if len(candidates) != 1:
        raise UsageError('Claude organization is ambiguous or unavailable')
    organization = candidates[0].get('uuid', '')
    if not re.fullmatch(r'[a-fA-F0-9-]{36}', organization):
        raise UsageError('Invalid Claude organization')
    base = 'https://claude.ai/api/organizations/' + organization
    try:
        data = request_json(base + '/usage?cedar_ember=1', headers)
    except urllib.error.HTTPError as error:
        if error.code != 403:
            raise
        data = request_json(base + '/usage', headers)
    result = normalize_claude(data, key, verified_email)
    try:
        credits = request_json(base + '/prepaid/credits', headers)
        amount, currency = credits.get('amount'), credits.get('currency')
        if isinstance(amount, (int, float)) and not isinstance(amount, bool) and math.isfinite(amount) and amount >= 0 and isinstance(currency, str) and currency.strip():
            result['usage']['providerCost'] = {'balance': amount / 100, 'currencyCode': currency.strip().upper()}
    except Exception:
        pass
    return result

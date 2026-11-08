"""Private local adapter. No credential values or upstream error text reach stdout."""
import contextlib
import hashlib
import io
import json
import math
import os
from pathlib import Path
import plistlib
import re
import queue
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid

LIMIT = 8 * 1024 * 1024

class SafeError(Exception):
    pass

class ResetSession:
    """Account-only official app-server RPC; never creates a thread or switches the desktop app."""
    def __init__(self, executable, profile, timeout=25):
        self.deadline = time.monotonic() + timeout
        env = {k: v for k, v in os.environ.items() if not k.startswith(('CODEX_', 'OPENAI_'))}
        env['CODEX_HOME'] = str(profile)
        self.process = subprocess.Popen([executable, 'app-server', '--stdio', '-c', 'cli_auth_credentials_store="file"', '-c', 'chatgpt_base_url="https://chatgpt.com/backend-api/"', '-c', 'mcp_servers={}'], cwd=profile, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.messages = queue.Queue(maxsize=64)
        self.counter = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(LIMIT + 1)
                if not line or len(line) > LIMIT:
                    self.messages.put_nowait(None)
                    return
                self.messages.put_nowait(json.loads(line))
        except Exception:
            try:
                self.messages.put_nowait(None)
            except queue.Full:
                pass

    def request(self, method, params):
        if time.monotonic() >= self.deadline:
            raise SafeError('Codex account service deadline reached; no further request sent')
        self.counter += 1
        self.process.stdin.write((json.dumps({'id': self.counter, 'method': method, 'params': params}) + '\n').encode())
        self.process.stdin.flush()
        deadline = self.deadline
        while time.monotonic() < deadline:
            try:
                response = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if not isinstance(response, dict):
                break
            if response.get('id') != self.counter:
                continue
            if 'error' in response or not isinstance(response.get('result'), dict):
                raise SafeError('Codex account service rejected the request; no upstream details displayed')
            return response['result']
        raise SafeError('Codex account service timed out or disconnected')

    def close(self):
        self.process.terminate()
        try:
            self.process.wait(3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()

def valid_key(key):
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', key):
        raise SafeError('Invalid account identifier')
    return key

def read_json(path, default):
    try:
        with open(path, 'rb') as stream:
            data = stream.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError()
        result = json.loads(data)
        if not isinstance(result, type(default)):
            raise ValueError()
        return result
    except FileNotFoundError:
        return default
    except (ValueError, OSError):
        raise SafeError('Invalid or unreadable local configuration') from None

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if path.is_symlink():
        raise SafeError('Refusing symbolic-link configuration')
    if path.exists():
        old = read_json(path, {})
        backup = path.with_suffix(path.suffix + '.backup')
        _write(backup, json.dumps(old).encode())
    _write(path, json.dumps(value, ensure_ascii=False).encode())

def _write(path, data):
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

@contextlib.contextmanager
def lock(path, nonblocking=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'a') as stream:
        if os.name == 'nt':
            import msvcrt
            stream.write('0')
            stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK if nonblocking else msvcrt.LK_LOCK, 1)
            except OSError:
                raise SafeError('An operation for this account is already running') from None
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
            except OSError:
                raise SafeError('An operation for this account is already running') from None
            yield

class Backend:
    def __init__(self, root=None, resources=None):
        self.root = Path(root) if root else Path.home()
        self.resources = Path(resources) if resources else (Path(sys.executable).resolve().parent.parent if getattr(sys, 'frozen', False) else Path(__file__).parent)
        self.state = self.root / 'Library/Application Support/AI Accounts'
        self.claude_config = self.root / '.config/claude-switcher/config.json'
        base = self.root / '.codex-switch'
        self.codex_base = base if base.exists() or not (self.root / '.codex-relay').exists() else self.root / '.codex-relay'

    def config(self):
        conf = read_json(self.claude_config, {'profiles': {}, 'sync_dirs': []})
        if not isinstance(conf.get('profiles'), dict) or not isinstance(conf.get('sync_dirs', []), list):
            raise SafeError('Invalid Claude profile configuration')
        for key, profile in conf['profiles'].items():
            valid_key(key)
            if not isinstance(profile, dict) or not isinstance(profile.get('data_dir'), str):
                raise SafeError('Invalid Claude profile')
            path = Path(profile['data_dir']).resolve()
            if not path.is_relative_to((self.root / 'Library/Application Support').resolve()):
                raise SafeError('Claude profile is outside Application Support')
        allowed = [(Path(p['data_dir']) / 'claude-code-sessions').resolve() for p in conf['profiles'].values()]
        for directory in conf.get('sync_dirs', []):
            if not isinstance(directory, str) or not any(Path(directory).resolve().is_relative_to(p) for p in allowed):
                raise SafeError('Claude session directory is outside configured profiles')
        return conf

    @contextlib.contextmanager
    def reset_session(self, profile, mutation=False):
        if (profile / 'config.toml').exists():
            raise SafeError('Reset requires a saved profile without custom app-server configuration')
        session = ResetSession(self.executable('codex'), profile, timeout=35 if mutation else 25)
        try:
            session.request('initialize', {'clientInfo': {'name': 'ai_accounts', 'version': '0.5.0'}, 'capabilities': {'experimentalApi': True}})
            session.process.stdin.write(b'{"method":"initialized","params":{}}\n')
            session.process.stdin.flush()
            yield session
        finally:
            session.close()

    def reset_profile(self, provider, key):
        if provider != 'codex':
            raise SafeError('Free reset is supported only for Codex')
        valid_key(key)
        profile = self.codex_base / 'profiles' / key
        if profile.is_symlink() or not profile.resolve().is_relative_to((self.codex_base / 'profiles').resolve()):
            raise SafeError('Invalid saved account path')
        if not (profile / 'auth.json').is_file() or (profile / 'auth.json').is_symlink():
            raise SafeError('Saved account login is unavailable')
        metadata = read_json(profile / 'metadata.json', {})
        if not isinstance(metadata.get('email'), str) or not isinstance(metadata.get('accountId'), str) or not metadata['accountId']:
            raise SafeError('Saved account identity is unavailable')
        return profile, metadata

    def reset_preflight(self, key, metadata, session):
        account = session.request('account/read', {'refreshToken': False}).get('account') or {}
        usage = session.request('account/rateLimits/read', {'excludeResetCreditDetails': False, 'supportsLunaReserve': False})
        attempts = read_json(self.state / 'reset-attempts.json', {})
        pending = attempts.get(key, {})
        uncertain = pending.get('state') == 'uncertain'
        status = {'ok': True, 'supported': True, 'eligible': False, 'availableCount': None, 'expiresAt': None, 'reasonCode': 'identity_unverified', 'reason': 'Identity could not be verified', 'accountId': None, 'accountEmail': None, 'attemptId': pending.get('attemptId') if uncertain else None, 'uncertain': uncertain}
        usage_id = usage.get('accountId')
        # CodexSwitch metadata stores HashPublicIdentifier(account_id), never the raw backend ID.
        usage_identity = 'sha256:' + hashlib.sha256(usage_id.encode()).hexdigest()[:16] if isinstance(usage_id, str) and usage_id else None
        if account.get('type') != 'chatgpt' or not isinstance(account.get('email'), str) or account['email'].casefold() != metadata['email'].casefold() or usage_identity != metadata['accountId']:
            return status, None
        if uncertain and pending.get('accountId') != metadata['accountId']:
            status['reason'] = 'Unresolved reset belongs to a different saved identity'
            status['reasonCode'] = 'identity_changed'
            return status, None
        status.update(accountId=metadata['accountId'], accountEmail=account['email'])
        credits = usage.get('rateLimitResetCredits') or {}
        count = credits.get('availableCount')
        status['availableCount'] = count if type(count) is int and count >= 0 else None
        details = credits.get('credits')
        selected = None
        now = time.time()
        if isinstance(details, list):
            valid = [c for c in details if isinstance(c, dict) and c.get('status') == 'available' and c.get('resetType') == 'codexRateLimits' and isinstance(c.get('id'), str) and c['id'] and (c.get('expiresAt') is None or type(c['expiresAt']) in (int, float) and math.isfinite(c['expiresAt']) and c['expiresAt'] > now)]
            if valid:
                selected = min(valid, key=lambda c: c.get('expiresAt') or float('inf'))
                status['expiresAt'] = selected.get('expiresAt')
            else:
                status['reason'] = 'No verified unexpired free reset credit'
                status['reasonCode'] = 'credit_expired_or_unverified'
                return status, None
        if status['availableCount'] is None or status['availableCount'] < 1:
            status['reason'] = 'No available free reset credit, or credit count unknown'
            status['reasonCode'] = 'credit_unavailable'
            return status, None
        buckets = usage.get('rateLimitsByLimitId')
        core = buckets.get('codex', {}) if isinstance(buckets, dict) else usage.get('rateLimits', {})
        if not isinstance(core, dict) or core.get('limitId') not in (None, 'codex'):
            core = {}
        eligible = False
        for name in ('primary', 'secondary'):
            window = core.get(name) or {}
            used, reset = window.get('usedPercent'), window.get('resetsAt')
            if window.get('windowDurationMins') in (300, 10080) and type(used) in (int, float) and math.isfinite(used) and 90 <= used <= 100 and type(reset) in (int, float) and math.isfinite(reset) and reset > now:
                eligible = True
        status['eligible'] = eligible
        status['reasonCode'] = 'eligible' if eligible else 'usage_not_eligible'
        status['reason'] = 'Fresh core usage has 10% or less remaining; confirmation required' if eligible else 'Core five-hour or weekly remaining must be 10% or less'
        if uncertain and not eligible:
            status['reason'] = 'Previous result remains uncertain; current usage is not eligible for a retry'
            status['reasonCode'] = 'uncertain_ineligible'
        return status, selected

    def reset_status(self, provider, key):
        if provider != 'codex':
            return {'ok': True, 'supported': False, 'eligible': False, 'availableCount': None, 'expiresAt': None, 'reasonCode': 'provider_unsupported', 'reason': 'Free reset is supported only for Codex', 'uncertain': False}
        profile, metadata = self.reset_profile(provider, key)
        with lock(self.state / ('reset-' + key + '.lock'), nonblocking=True), self.reset_session(profile) as session:
            status, _ = self.reset_preflight(key, metadata, session)
            return status

    def reset_account(self, provider, key, confirmed):
        if confirmed is not True:
            raise SafeError('Explicit confirmation is required for each free reset attempt')
        profile, metadata = self.reset_profile(provider, key)
        with lock(self.state / ('reset-' + key + '.lock'), nonblocking=True), self.reset_session(profile, mutation=True) as session:
            status, selected = self.reset_preflight(key, metadata, session)
            if not status['eligible']:
                raise SafeError(status['reason'])
            path = self.state / 'reset-attempts.json'
            attempts = read_json(path, {})
            attempt = attempts.get(key, {})
            if attempt.get('state') != 'uncertain':
                attempt = {'attemptId': str(uuid.uuid4()), 'accountId': metadata['accountId'], 'creditId': selected['id'] if selected else None}
            try:
                uuid.UUID(attempt['attemptId'])
            except (KeyError, TypeError, ValueError):
                raise SafeError('Stored reset request ID is invalid; no reset sent') from None
            # Persist before sending; a crash or timeout must never create a new logical attempt.
            attempt.update(state='uncertain', updatedAt=time.time())
            attempts[key] = attempt
            atomic_json(path, attempts)
            params = {'idempotencyKey': attempt['attemptId']}
            if attempt.get('creditId'):
                params['creditId'] = attempt['creditId']
            try:
                result = session.request('account/rateLimitResetCredit/consume', params)
                outcome = result.get('outcome')
                if outcome not in ('reset', 'alreadyRedeemed', 'noCredit', 'nothingToReset'):
                    raise SafeError('Unknown reset outcome')
            except Exception:
                return {'ok': False, 'outcome': 'uncertain', 'attemptId': attempt['attemptId'], 'message': 'Reset result is uncertain. No new attempt will be created; any eligible retry uses the same request ID.'}
            attempt.update(state=outcome, updatedAt=time.time())
            try:
                atomic_json(path, attempts)
            except OSError:
                # The provider outcome is definitive even if local bookkeeping cannot be updated.
                return {'ok': outcome in ('reset', 'alreadyRedeemed'), 'outcome': outcome, 'attemptId': attempt['attemptId'], 'message': 'Provider returned ' + outcome + '; local receipt could not be updated. Do not start a new reset attempt.'}
            # A completed reset stays complete; an optional later quota refresh is a separate operation.
            return {'ok': outcome in ('reset', 'alreadyRedeemed'), 'outcome': outcome, 'attemptId': attempt['attemptId'], 'message': {'reset': 'One free reset completed', 'alreadyRedeemed': 'This reset attempt was already completed', 'noCredit': 'No free reset credit was consumed: none available', 'nothingToReset': 'No reset applied: no eligible usage window'}[outcome]}

    def list_accounts(self):
        identities = read_json(self.state / 'identities.json', {})
        labels = read_json(self.state / 'labels.json', {})
        accounts = []
        for path in sorted((self.codex_base / 'profiles').glob('*/metadata.json')):
            key = valid_key(path.parent.name)
            if path.is_symlink() or path.parent.is_symlink():
                raise SafeError('Refusing symbolic-link profile metadata')
            metadata = read_json(path, {})
            email = metadata.get('email')
            accounts.append(dict(id='codex:' + key, provider='codex', key=key, label=labels.get(key, key), email=email if isinstance(email, str) else None, usageAccount=key))
        for key, profile in self.config()['profiles'].items():
            identity = identities.get(key, {})
            accounts.append(dict(id='claude:' + key, provider='claude', key=key, label=profile.get('label', key), email=identity.get('email'), usageAccount=identity.get('usageAccount')))
        return {'accounts': accounts, 'dependencies': {'codexApp': Path('/Applications/Codex.app').exists(), 'claudeApp': Path('/Applications/Claude.app').exists()}, 'platform': 'macOS Apple Silicon'}

    def executable(self, name):
        choices = [self.resources / 'bin' / name]
        if not getattr(sys, 'frozen', False):
            choices += [self.root / '.local/bin' / name]
        for path in choices:
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
        raise SafeError('Required bundled tool is missing')

    def run(self, args, timeout=60, output=False, allow_nonzero=False, tool_dir=None):
        env = os.environ.copy()
        env['PATH'] = str(self.resources / 'bin') + ':/usr/bin:/bin:/usr/sbin:/sbin'
        if tool_dir is not None:
            env['PATH'] = str(tool_dir) + ':' + env['PATH']
        # Prevent a developer shell override from redirecting account storage.
        for name in ('CODEX_HOME', 'CODEX_SWITCH_HOME', 'CODEX_LOCAL_SWITCH_HOME', 'CS_STATE_DIR', 'CS_DIRS'):
            env.pop(name, None)
        with tempfile.TemporaryFile() as result:
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=result, stderr=subprocess.DEVNULL, env=env)
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if time.monotonic() > deadline or os.fstat(result.fileno()).st_size > LIMIT:
                    process.terminate()
                    try:
                        process.wait(3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise SafeError('Operation timed out or returned too much data')
                time.sleep(0.1)
            if process.returncode and not allow_nonzero:
                raise SafeError('Provider operation failed or was cancelled; existing accounts were retained')
            result.seek(0)
            return result.read(LIMIT + 1) if output else b''

    def usage(self, provider):
        self.provider(provider)
        cli = self.resources / 'codexbar/Helpers/CodexBarCLI'
        raw = self.run([str(cli), 'usage', '--provider', provider, '--all-accounts', '--json', '--source', 'oauth' if provider == 'codex' else 'web'], output=True, timeout=90, allow_nonzero=True)
        data = json.loads(raw)
        if not isinstance(data, list):
            raise SafeError('Invalid quota response')
        return data

    @staticmethod
    def provider(provider):
        if provider not in ('codex', 'claude'):
            raise SafeError('Unknown provider')

    def claude_modules(self):
        sys.path.insert(0, str(Path(__file__).parent / 'vendor/claude-switcher'))
        import claude_switch
        return claude_switch

    def switch(self, provider, key):
        self.provider(provider)
        valid_key(key)
        if not any(row['id'] == provider + ':' + key for row in self.list_accounts()['accounts']):
            raise SafeError('Unknown account')
        if provider == 'codex':
            import macos_codex
            try:
                app, cli = macos_codex.select_desktop()
            except macos_codex.LaunchError as exc:
                raise SafeError(str(exc)) from exc
            with macos_codex.switch_tool_dir(app, cli) as directory:
                self.run([self.executable('codex-switch'), 'switch', key], timeout=120, tool_dir=directory)
        else:
            switcher = self.claude_modules()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                if switcher.cmd_switch(self.config(), key, False, False):
                    raise SafeError('Claude could not switch safely; finish active work and try again')
        return 'Switch command completed'

    def add(self, provider, label):
        self.provider(provider)
        if not isinstance(label, str) or not label.strip() or len(label) > 120 or any(ord(c) < 32 for c in label):
            raise SafeError('Enter an account label of 1–120 characters')
        key = str(uuid.uuid4())
        if provider == 'codex':
            self.run([self.executable('codex-switch'), 'profile', 'add', key], timeout=600)
            labels = read_json(self.state / 'labels.json', {})
            labels[key] = label
            atomic_json(self.state / 'labels.json', labels)
            return 'Codex login completed and account saved'
        conf = self.config()
        path = self.root / 'Library/Application Support' / ('Claude AI Accounts ' + key)
        path.mkdir(parents=True, mode=0o700)
        try:
            self.run(['/usr/bin/open', '-na', '/Applications/Claude.app', '--args', '--user-data-dir=' + str(path)])
        except Exception:
            # An empty failed-launch directory is safe to remove; never delete app-created files.
            if not any(path.iterdir()):
                path.rmdir()
            raise
        conf['profiles'][key] = {'label': label, 'data_dir': str(path)}
        atomic_json(self.claude_config, conf)
        return 'Claude login window opened. Complete login, open Code tab once, then Connect and Setup. Authentication is not yet verified.'

    def connect(self):
        conf_path = self.root / '.config/codexbar/config.json'
        identities = read_json(self.state / 'identities.json', {})
        imported = []
        profiles = self.config()['profiles']
        password = None
        for key, profile in profiles.items():
            cookies = Path(profile['data_dir']) / 'Cookies'
            if not cookies.exists():
                continue
            with sqlite3.connect(cookies.as_uri() + '?mode=ro', uri=True) as db:
                rows = db.execute("SELECT host_key, encrypted_value FROM cookies WHERE host_key='.claude.ai' AND name='sessionKey'").fetchall()
            if len(rows) != 1:
                continue
            if password is None:
                password = self.run(['/usr/bin/security', 'find-generic-password', '-w', '-s', 'Claude Safe Storage'], output=True).rstrip(b'\r\n')
            token = decrypt_cookie(rows[0][0], rows[0][1], password)
            request = urllib.request.Request('https://claude.ai/api/account', headers={'Cookie': 'sessionKey=' + token, 'Accept': 'application/json', 'User-Agent': 'AI-Accounts/0.3.0'})
            opener = urllib.request.build_opener(NoRedirect)
            with opener.open(request, timeout=20) as response:
                raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise SafeError('Identity response too large')
            identity = json.loads(raw)
            email = identity.get('email_address') or identity.get('email')
            if not isinstance(email, str) or '@' not in email:
                raise SafeError('Claude account identity could not be verified')
            imported.append((key, profile['label'], token, email))
        with lock(conf_path.with_suffix('.json.lock')):
            conf = read_json(conf_path, {'version': 1, 'providers': []})
            original = json.loads(json.dumps(conf))
            providers = conf.setdefault('providers', [])
            if not isinstance(providers, list):
                raise SafeError('Unsupported quota configuration')
            for name in ('codex', 'claude'):
                entry = next((p for p in providers if p.get('id') == name), None)
                if entry is None:
                    entry = {'id': name}
                    providers.append(entry)
                entry.update(enabled=True, source='oauth' if name == 'codex' else 'web', cookieSource='off' if name == 'codex' else 'manual')
                if name == 'codex':
                    entry['codexProfileHomePaths'] = [str(p.parent) for p in sorted((self.codex_base / 'profiles').glob('*/metadata.json'))]
                else:
                    accounts = entry.setdefault('tokenAccounts', {'version': 1, 'activeIndex': 0, 'accounts': []})['accounts']
                    for key, label, token, email in imported:
                        account = next((a for a in accounts if a.get('token') == token or a.get('id') == identities.get(key, {}).get('usageAccount')), None)
                        if account is None:
                            account = {'id': str(uuid.uuid4()), 'label': label, 'addedAt': time.time()}
                            accounts.append(account)
                        account['token'] = token
                        identities[key] = {'email': email, 'usageAccount': account['id']}
            atomic_json(conf_path, conf)
            try:
                atomic_json(self.state / 'identities.json', identities)
            except Exception:
                atomic_json(conf_path, original)
                raise
        return f'Quota configured; verified {len(imported)} Claude identities'

    def setup(self):
        if not getattr(sys, 'frozen', False):
            raise SafeError('Install the packaged app before registering background sync')
        if Path(sys.executable).resolve().is_relative_to('/Volumes'):
            raise SafeError('Copy AI Accounts to Applications before registering background sync')
        switcher = self.claude_modules()
        conf = self.config()
        dirs = switcher.C.detect_session_dirs([p['data_dir'] for p in conf['profiles'].values()])
        if not dirs:
            raise SafeError('Open the Claude Code tab once for each account, then retry Setup')
        original_conf = json.loads(json.dumps(conf))
        conf['sync_dirs'] = dirs
        # Replace the same label after unloading it; never register a second concurrent job.
        existing = self.root / 'Library/LaunchAgents/io.github.claude-switcher.sync.plist'
        plist = {'Label': 'io.github.claude-switcher.sync', 'ProgramArguments': [sys.executable, 'sync'], 'StartInterval': 20, 'RunAtLoad': True}
        existing.parent.mkdir(parents=True, exist_ok=True)
        original = existing.read_bytes() if existing.exists() else None
        if original:
            _write(existing.with_suffix('.plist.backup'), original)
            self.run(['/bin/launchctl', 'bootout', f'gui/{os.getuid()}', str(existing)], allow_nonzero=True)
        try:
            atomic_json(self.claude_config, conf)
            _write(existing, plistlib.dumps(plist))
            self.run(['/bin/launchctl', 'bootstrap', f'gui/{os.getuid()}', str(existing)])
        except Exception:
            atomic_json(self.claude_config, original_conf)
            if original:
                _write(existing, original)
                self.run(['/bin/launchctl', 'bootstrap', f'gui/{os.getuid()}', str(existing)])
            elif existing.exists():
                existing.unlink()
            raise
        return 'Session sync registered'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SafeError('Identity endpoint redirected; connection stopped')

def decrypt_cookie(host, encrypted, password):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7
    if not encrypted.startswith(b'v10') or len(encrypted) > 32768:
        raise SafeError('Unsupported Claude cookie format')
    key = hashlib.pbkdf2_hmac('sha1', password, b'saltysalt', 1003, 16)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(b' ' * 16)).decryptor()
    unpad = PKCS7(128).unpadder()
    value = unpad.update(decryptor.update(encrypted[3:]) + decryptor.finalize()) + unpad.finalize()
    if value[:32] == hashlib.sha256(host.encode()).digest():
        value = value[32:]
    token = value.decode('utf-8')
    if not re.fullmatch(r'sk-ant-[A-Za-z0-9_-]+', token):
        raise SafeError('Invalid Claude session')
    return token

def main(args):
    if args == ['--self-test']:
        # No user-selected root and no inherited credential access in frozen smoke tests.
        with tempfile.TemporaryDirectory(prefix='ai-accounts-fixture-') as tmp:
            fixture = Backend(tmp)
            if fixture.list_accounts()['accounts']:
                raise SafeError('Fixture is not empty')
            for i in range(40):
                atomic_json(fixture.codex_base / 'profiles' / str(i) / 'metadata.json', {'email': f'fixture{i}@example.test'})
            if len(fixture.list_accounts()['accounts']) != 40:
                raise SafeError('Fixture accounts missing')
        return {'ok': True, 'message': 'Frozen fixture: empty and 40 accounts passed; no provider processes launched'}
    if os.name == 'nt':
        from windows_backend import WindowsBackend
        backend = WindowsBackend()
    else:
        backend = Backend()
    if args == ['advise']:
        from ai_advisor import advise
        return advise(backend)
    if args == ['list']:
        return backend.list_accounts()
    if len(args) == 2 and args[0] == 'usage':
        return backend.usage(args[1])
    if len(args) == 3 and args[0] == 'reset-status':
        return backend.reset_status(args[1], args[2])
    with lock(backend.state / 'operation.lock'):
        if len(args) == 4 and args[0] == 'reset' and args[3] == '--confirmed':
            return backend.reset_account(args[1], args[2], True)
        if len(args) == 3 and args[0] in ('add', 'switch', 'login') and hasattr(backend, args[0]):
            message = getattr(backend, args[0])(*args[1:])
        elif args == ['connect']:
            message = backend.connect()
        elif args == ['setup']:
            message = backend.setup()
        elif args == ['sync']:
            if hasattr(backend, 'sync'):
                message = backend.sync()
            else:
                switcher = backend.claude_modules()
                if switcher.cs_sync.sync(backend.config().get('sync_dirs', [])):
                    raise SafeError('Session sync paused for safety')
                message = 'Sync complete'
        else:
            raise SafeError('Unknown helper command')
    return {'ok': True, 'message': message}

if __name__ == '__main__':
    # Windows adapters must share this entrypoint's SafeError type when frozen.
    sys.modules.setdefault('backend', sys.modules[__name__])
    os.umask(0o077)
    try:
        # Escaped JSON preserves Thai even when Windows pipes use a legacy code page.
        print(json.dumps(main(sys.argv[1:])))
    except Exception as error:
        print(json.dumps({'ok': False, 'message': str(error) if isinstance(error, SafeError) else 'Operation failed safely; check login and local configuration'}))
        sys.exit(1)

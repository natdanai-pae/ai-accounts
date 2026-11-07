"""Windows paths and normal provider login, using the shared helper contract."""
import base64
import contextlib
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from backend import Backend, SafeError, read_json, atomic_json, valid_key, _write
from windows_usage import codex_usage, claude_usage, request_json

def unprotect(value):
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_char))]
    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise SafeError('Windows could not unlock this login for the current user')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)

def decrypt_cookie(profile, host, encrypted):
    if encrypted.startswith(b'v20'):
        raise SafeError('This Claude login uses app-bound encryption; quota connection is unsupported')
    if encrypted.startswith((b'v10', b'v11')):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        state = read_json(Path(profile) / 'Local State', {})
        wrapped = base64.b64decode(state.get('os_crypt', {}).get('encrypted_key', ''), validate=True)
        if not wrapped.startswith(b'DPAPI'):
            raise SafeError('Unsupported Windows login encryption')
        value = AESGCM(unprotect(wrapped[5:])).decrypt(encrypted[3:15], encrypted[15:], None)
    else:
        value = unprotect(encrypted)
    if value[:32] == hashlib.sha256(host.encode()).digest():
        value = value[32:]
    token = value.decode('utf-8')
    if not re.fullmatch(r'sk-ant-[A-Za-z0-9_-]+', token):
        raise SafeError('Unsupported Claude login cookie')
    return token

class WindowsBackend(Backend):
    def __init__(self, root=None, resources=None):
        super().__init__(root, resources)
        self.local = Path(os.environ.get('LOCALAPPDATA', self.root / 'AppData/Local')) if root is None else self.root / 'AppData/Local'
        self.roaming = Path(os.environ.get('APPDATA', self.root / 'AppData/Roaming')) if root is None else self.root / 'AppData/Roaming'
        self.state = self.local / 'AI Accounts'

    def config(self):
        conf = read_json(self.claude_config, {'profiles': {}, 'sync_dirs': []})
        if not isinstance(conf.get('profiles'), dict) or not isinstance(conf.get('sync_dirs'), list):
            raise SafeError('Invalid Claude profile configuration')
        roots = []
        for key, profile in conf['profiles'].items():
            valid_key(key)
            if not isinstance(profile, dict) or not isinstance(profile.get('data_dir'), str):
                raise SafeError('Invalid Claude profile')
            path = Path(profile['data_dir'])
            if path.is_symlink() or not path.resolve().is_relative_to(self.roaming.resolve()):
                raise SafeError('Claude profile is outside user Application Data')
            roots.append(path.resolve() / 'claude-code-sessions')
        for directory in conf['sync_dirs']:
            if not isinstance(directory, str) or not any(Path(directory).resolve().is_relative_to(p) for p in roots):
                raise SafeError('Session path is outside configured profiles')
        return conf

    def list_accounts(self):
        result = super().list_accounts()
        result['platform'] = 'Windows x64 beta'
        result['dependencies'] = {'claudeApp': self.claude_app() is not None, 'codexApp': (self.local / 'Microsoft/WindowsApps/codex.exe').is_file()}
        return result

    def claude_app(self):
        legacy = self.local / 'AnthropicClaude/claude.exe'
        if legacy.is_file():
            return legacy
        # Resolve the current user's registered package, so Store updates do not stale the path.
        script = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-AppxPackage -Name Claude | Where-Object {$_.PackageFamilyName -eq 'Claude_pzs8sxrjxfjjc'} | Select-Object -First 1 -ExpandProperty InstallLocation | ConvertTo-Json -Compress"
        try:
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            location = json.loads(result.stdout.decode('utf-8-sig')) if result.returncode == 0 else None
            if isinstance(location, str) and Path(location).is_absolute():
                app = Path(location) / 'app/Claude.exe'
                if app.is_file():
                    return app
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        return None

    def claude_modules(self):
        switcher = super().claude_modules()
        app = self.claude_app()
        if app is None:
            raise SafeError('Install the official Claude desktop app first')
        switcher.C.APP = str(app)
        return switcher

    def executable(self, name):
        path = self.resources / 'bin' / (name + '.exe')
        if not path.is_file():
            raise SafeError('Required bundled tool is missing')
        return str(path)

    def run(self, args, timeout=60, output=False):
        env = os.environ.copy()
        env['PATH'] = str(self.resources / 'bin') + os.pathsep + env.get('PATH', '')
        for name in ('CODEX_HOME', 'CODEX_SWITCH_HOME', 'CODEX_LOCAL_SWITCH_HOME', 'CS_STATE_DIR', 'CS_DIRS'):
            env.pop(name, None)
        try:
            result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise SafeError('Operation timed out; check provider login before retrying') from None
        if result.returncode or len(result.stdout) > 8 * 1024 * 1024:
            raise SafeError('Provider operation failed or was cancelled; accounts were retained')
        return result.stdout if output else b''

    def add(self, provider, label):
        self.provider(provider)
        if provider == 'codex':
            return super().add(provider, label)
        if not isinstance(label, str) or not label.strip() or len(label) > 120 or any(ord(c) < 32 for c in label):
            raise SafeError('Enter an account label of 1–120 characters')
        app = self.claude_app()
        if app is None:
            raise SafeError('Install the official Claude desktop app first')
        key = str(uuid.uuid4())
        profile = self.roaming / ('Claude AI Accounts ' + key)
        profile.mkdir(parents=True, mode=0o700)
        subprocess.Popen([str(app), '--user-data-dir=' + str(profile)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        conf = self.config()
        conf['profiles'][key] = {'label': label, 'data_dir': str(profile)}
        atomic_json(self.claude_config, conf)
        return 'Claude login opened. Finish login and open Code once, then Connect and Setup. Identity is not yet verified.'

    def switch(self, provider, key):
        if provider == 'codex':
            rows = self.run(['tasklist', '/FO', 'CSV', '/NH'], output=True).decode('utf-8', errors='replace').lower()
            if re.search(r'"codex\.exe"|"chatgpt\.exe"', rows):
                raise SafeError('Close the running Codex desktop app first, then retry. No process was forced closed.')
        return super().switch(provider, key)

    def usage(self, provider):
        from concurrent.futures import ThreadPoolExecutor
        self.provider(provider)
        accounts = [a for a in self.list_accounts()['accounts'] if a['provider'] == provider]
        conf = read_json(self.root / '.config/codexbar/config.json', {'providers': []})
        entry = next((p for p in conf['providers'] if p.get('id') == 'claude'), {})
        tokens = entry.get('tokenAccounts', {}).get('accounts', [])
        def fetch(account):
            try:
                if provider == 'codex':
                    value = codex_usage(self.codex_base / 'profiles' / account['key'], account['usageAccount'], account.get('email'))
                else:
                    token = next(t['token'] for t in tokens if t.get('id') == account.get('usageAccount'))
                    value = claude_usage(token, account['usageAccount'], account.get('email'))
                return value
            except Exception:
                return {'provider': provider, 'account': account.get('usageAccount'), 'error': 'Quota unavailable; reconnect or refresh login'}
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(fetch, accounts))

    def connect(self):
        identities = read_json(self.state / 'identities.json', {})
        path = self.root / '.config/codexbar/config.json'
        conf = read_json(path, {'version': 1, 'providers': []})
        original = json.dumps(conf, ensure_ascii=False).encode('utf-8')
        entry = next((p for p in conf['providers'] if p.get('id') == 'claude'), None)
        if entry is None:
            entry = {'id': 'claude', 'tokenAccounts': {'version': 1, 'activeIndex': 0, 'accounts': []}}
            conf['providers'].append(entry)
        tokens = entry.setdefault('tokenAccounts', {'version': 1, 'activeIndex': 0, 'accounts': []})['accounts']
        count = 0
        for key, profile in self.config()['profiles'].items():
            directory = Path(profile['data_dir'])
            cookies = next((p for p in (directory / 'Network/Cookies', directory / 'Cookies') if p.is_file()), None)
            if cookies is None:
                continue
            with sqlite3.connect(cookies.resolve().as_uri() + '?mode=ro', uri=True) as db:
                rows = db.execute("SELECT host_key, encrypted_value FROM cookies WHERE host_key='.claude.ai' AND name='sessionKey'").fetchall()
            if len(rows) != 1:
                continue
            token = decrypt_cookie(directory, *rows[0])
            identity = request_json('https://claude.ai/api/account', {'Cookie': 'sessionKey=' + token})
            email = identity.get('email_address') or identity.get('email')
            if not isinstance(email, str) or '@' not in email:
                raise SafeError('Claude identity could not be verified')
            old_id = identities.get(key, {}).get('usageAccount')
            account = next((a for a in tokens if a.get('id') == old_id), None)
            if account is None:
                account = {'id': str(uuid.uuid4()), 'label': profile['label'], 'addedAt': time.time()}
                tokens.append(account)
            account['token'] = token
            identities[key] = {'email': email, 'usageAccount': account['id']}
            count += 1
        atomic_json(path, conf)
        try:
            atomic_json(self.state / 'identities.json', identities)
        except Exception:
            _write(path, original)
            raise
        return f'Connected {count} Claude identities. Codex quotas use existing official login.'

    def setup(self):
        switcher = self.claude_modules()
        conf = self.config()
        directories = switcher.C.detect_session_dirs([p['data_dir'] for p in conf['profiles'].values()])
        if not directories:
            raise SafeError('Open the Claude Code tab once for each account, then retry Setup')
        conf['sync_dirs'] = directories
        atomic_json(self.claude_config, conf)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if switcher.cs_sync.sync(directories):
                raise SafeError('Session sync paused for safety')
        return 'Shared session folders registered. Sync runs on switching and while AI Accounts is open.'

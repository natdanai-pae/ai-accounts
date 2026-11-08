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
    def claude_primary_data(self):
        migrated = self.local / 'Claude-Data/claude_pzs8sxrjxfjjc'
        if migrated.is_dir():
            return migrated
        return self.claude_store_roaming / 'Claude'

    def primary_mode(self):
        app = self.claude_app()
        return app is not None and app != self.local / 'AnthropicClaude/claude.exe'

    def auth_store(self):
        from windows_claude_profiles import AuthStore
        return AuthStore(self.claude_primary_data(), self.state / 'claude-auth')

    def close_primary_claude(self):
        switcher = self.claude_modules()
        rows = [(pid, switcher.win_data_dir(cmd)) for pid, _, name, cmd in switcher.win_processes() if switcher.win_is_app(name, cmd)]
        if any(switcher.busy_sessions(pid) for pid, _ in rows):
            raise SafeError('Claude ยังมีงานกำลังทำ กรุณารอให้เสร็จก่อนสลับบัญชี')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            for pid, directory in rows:
                if switcher.alive(pid) and not switcher.quit_app(pid, directory):
                    raise SafeError('Claude ยังปิดไม่เสร็จ ไม่มีการบังคับปิดหรือสลับข้อมูล')

    def primary_identity(self):
        directory = self.claude_primary_data()
        self.auth_store().check_tree(directory / 'Network')
        cookies = directory / 'Network/Cookies'
        if not cookies.is_file():
            return None
        try:
            with contextlib.closing(sqlite3.connect(cookies.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
                rows = db.execute("SELECT host_key, encrypted_value FROM cookies WHERE host_key='.claude.ai' AND name='sessionKey'").fetchall()
        except sqlite3.OperationalError:
            raise SafeError('Claude ยังล็อกข้อมูลอยู่ กรุณาออกจากแอปตามปกติก่อนลองใหม่') from None
        if len(rows) != 1:
            return None
        token = decrypt_cookie(directory, *rows[0])
        identity = request_json('https://claude.ai/api/account', {'Cookie': 'sessionKey=' + token})
        email = identity.get('email_address') or identity.get('email')
        account = identity.get('uuid') or identity.get('account_uuid')
        if not isinstance(email, str) or '@' not in email or not isinstance(account, str):
            raise SafeError('Claude account identity could not be verified')
        config = read_json(directory / 'config.json', {})
        if config.get('lastKnownAccountUuid') != account:
            raise SafeError('บัญชี Chat กับ Code ยังไม่ตรงกัน กรุณาเปิด Code ของบัญชีนี้ก่อน')
        return {'email': email, 'uuid': account, 'token': token}

    def remember_primary_identity(self, key, identity):
        valid_key(key)
        identities = read_json(self.state / 'identities.json', {})
        existing = identities.get(key, {})
        if existing.get('email') and (existing['email'].casefold() != identity['email'].casefold() or existing.get('uuid', identity['uuid']) != identity['uuid']):
            raise SafeError('บัญชีที่เปิดอยู่ไม่ตรงกับรายการเดิม จึงไม่เขียนทับข้อมูลล็อกอินที่บันทึกไว้')
        if any(other != key and value.get('email', '').casefold() == identity['email'].casefold() for other, value in identities.items()):
            raise SafeError('บัญชีนี้ถูกบันทึกในรายการอื่นแล้ว ข้อมูลเดิมยังอยู่ กรุณาใช้บัญชีคนละอีเมล')
        path = self.root / '.config/codexbar/config.json'
        conf = read_json(path, {'version': 1, 'providers': []})
        original = json.dumps(conf).encode()
        entry = next((p for p in conf['providers'] if p.get('id') == 'claude'), None)
        if entry is None:
            entry = {'id': 'claude', 'tokenAccounts': {'version': 1, 'activeIndex': 0, 'accounts': []}}
            conf['providers'].append(entry)
        accounts = entry['tokenAccounts']['accounts']
        old_id = identities.get(key, {}).get('usageAccount')
        account = next((a for a in accounts if a.get('id') == old_id), None)
        if account is None:
            account = {'id': str(uuid.uuid4()), 'label': key, 'addedAt': time.time()}
            accounts.append(account)
        account['token'] = identity['token']
        identities[key] = {'email': identity['email'], 'uuid': identity['uuid'], 'usageAccount': account['id']}
        atomic_json(path, conf)
        try:
            atomic_json(self.state / 'identities.json', identities)
        except Exception:
            _write(path, original)
            raise

    def checkpoint_primary(self, enrollment_key=None):
        store = self.auth_store()
        store.recover()
        identity = self.primary_identity()
        if identity is None:
            return store
        key = store.state()['active']
        identities = read_json(self.state / 'identities.json', {})
        if key not in identities:
            # A pending slot may have signed into an already saved account.
            # Checkpoint that real identity without binding it to a second slot.
            key = next((k for k, v in identities.items() if v.get('email', '').casefold() == identity['email'].casefold()), None)
            if key is None:
                key = store.state()['active']
        profiles = self.config()['profiles']
        # Adopt an existing verified login only for the first explicitly selected slot.
        if key is None and enrollment_key is not None and set(profiles) == {enrollment_key} and not identities and not store.state()['snapshots']:
            key = enrollment_key
        if key is None or key not in profiles:
            raise SafeError('ยังระบุรายการของบัญชีที่เปิดอยู่ไม่ได้ ข้อมูลล็อกอินเดิมยังไม่ถูกเปลี่ยน')
        self.remember_primary_identity(key, identity)
        store.capture(key)
        return store

    def primary_sync_directories(self):
        profiles = self.config()['profiles']
        identities = read_json(self.state / 'identities.json', {})
        snapshots = self.auth_store().state()['snapshots']
        accounts = [identities.get(key, {}).get('uuid') for key in profiles]
        if len(profiles) < 2 or any(not value for value in accounts) or len(set(accounts)) != len(profiles) or any(key not in snapshots for key in profiles):
            raise SafeError('ยังแชร์ session ไม่ครบ ต้องบันทึกบัญชีคนละตัวตนครบทุกรายการก่อน')
        directories = []
        session_root = self.claude_primary_data() / 'claude-code-sessions'
        self.auth_store().check_tree(session_root)
        for account in accounts:
            valid_key(account)
            root = session_root / account
            found = [str(p) for p in root.glob('*') if p.is_dir() and not p.is_symlink()]
            if not found:
                raise SafeError('ยังไม่มีโฟลเดอร์ Code จริงของทุกบัญชี เปิด Code ของแต่ละบัญชีก่อนแชร์ session')
            directories.extend(found)
        return sorted(set(directories))

    def launch_primary(self):
        app = self.claude_app()
        if app is None:
            raise SafeError('Install the official Claude desktop app first')
        subprocess.Popen([str(app)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def __init__(self, root=None, resources=None):
        super().__init__(root, resources)
        self.fixture_root = root is not None and Path(root).resolve() != Path.home().resolve()
        self.local = Path(os.environ.get('LOCALAPPDATA', self.root / 'AppData/Local')) if root is None else self.root / 'AppData/Local'
        self.roaming = Path(os.environ.get('APPDATA', self.root / 'AppData/Roaming')) if root is None else self.root / 'AppData/Roaming'
        self.claude_store_roaming = self.local / 'Packages/Claude_pzs8sxrjxfjjc/LocalCache/Roaming'
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
            if path.is_symlink() or not any(path.resolve().is_relative_to(root.resolve()) for root in (self.roaming, self.claude_store_roaming)):
                raise SafeError('Claude profile is outside user Application Data')
            # Store Claude redirects Roaming writes; read and launch the actual profile thereafter.
            if path.is_relative_to(self.roaming):
                physical = self.claude_store_roaming / path.relative_to(self.roaming)
                if physical.is_dir():
                    if physical.is_symlink() or not physical.resolve().is_relative_to(self.claude_store_roaming.resolve()):
                        raise SafeError('Claude profile is outside user Application Data')
                    conf['sync_dirs'] = [str(physical / Path(d).relative_to(path)) if isinstance(d, str) and Path(d).is_relative_to(path) else d for d in conf['sync_dirs']]
                    path = physical
                    profile['data_dir'] = str(path)
            roots.append(path.resolve() / 'claude-code-sessions')
        roots.append(self.claude_primary_data().resolve() / 'claude-code-sessions')
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
        if self.fixture_root:
            return None
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
        if app != self.local / 'AnthropicClaude/claude.exe':
            switcher.C.PRIMARY_DATA = str(self.claude_primary_data())
            switcher.C._ROAMING = str(self.claude_store_roaming)
            switcher.C._LOCAL = str(self.claude_store_roaming.parent / 'Local')
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
        data_root = self.roaming if app == self.local / 'AnthropicClaude/claude.exe' else self.claude_store_roaming
        profile = data_root / ('Claude AI Accounts ' + key)
        profile.mkdir(parents=True, mode=0o700)
        conf = self.config()
        conf['profiles'][key] = {'label': label, 'data_dir': str(profile)}
        atomic_json(self.claude_config, conf)
        if self.primary_mode():
            return self.login('claude', key)
        subprocess.Popen([str(app), '--user-data-dir=' + str(profile)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 'Claude login opened. Finish login and open Code once, then Connect and Setup. Identity is not yet verified.'

    def switch(self, provider, key):
        if provider == 'claude' and self.primary_mode():
            valid_key(key)
            if key not in self.config()['profiles'] or key not in self.auth_store().state()['snapshots']:
                raise SafeError('บัญชีนี้ยังไม่บันทึกการเข้าสู่ระบบ กดเข้าสู่ระบบต่อบนรายการเดิม')
            self.close_primary_claude()
            store = self.checkpoint_primary()
            store.activate(key)
            try:
                self.primary_sync_directories()
            except SafeError:
                pass  # First-time enrollment must work before every account is ready.
            else:
                self.setup()
            self.launch_primary()
            return 'สลับบัญชี Claude แล้ว · เก็บ session เดิมไว้'
        if provider == 'codex':
            rows = self.run(['tasklist', '/FO', 'CSV', '/NH'], output=True).decode('utf-8', errors='replace').lower()
            if re.search(r'"codex\.exe"|"chatgpt\.exe"', rows):
                raise SafeError('Close the running Codex desktop app first, then retry. No process was forced closed.')
        return super().switch(provider, key)

    def login(self, provider, key):
        if provider != 'claude':
            raise SafeError('การเข้าสู่ระบบต่อรองรับเฉพาะ Claude')
        valid_key(key)
        conf = self.config()
        if key not in conf['profiles']:
            raise SafeError('ไม่พบบัญชีนี้')
        if self.primary_mode():
            self.close_primary_claude()
            store = self.checkpoint_primary(enrollment_key=key)
            store.activate(key)
            self.launch_primary()
            return 'เปิดรายการเดิมใน Claude หลักแล้ว · เข้าสู่ระบบครั้งแรก เปิด Code แล้วกดเชื่อมข้อมูลโควตา'
        switcher = self.claude_modules()
        self.close_idle_claude(conf, switcher, keep=key)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            switcher.launch(conf, key)
        return 'เปิดบัญชีเดิมให้เข้าสู่ระบบต่อแล้ว · ใช้การเข้าสู่ระบบด้วยอีเมลเพื่อเลี่ยง Google กลับผิดหน้าต่าง · เสร็จแล้วกดเชื่อมข้อมูลโควตา'

    def close_idle_claude(self, conf, switcher, keep=None):
        running = switcher.running(conf)
        others = {k: pid for k, pid in running.items() if k != keep}
        if any(switcher.busy_sessions(pid) for pid in others.values()):
            raise SafeError('Claude ยังมีงานกำลังทำ กรุณารอให้เสร็จก่อนเชื่อมหรือเข้าสู่ระบบอีกบัญชี')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            for other, pid in others.items():
                if not switcher.quit_app(pid, conf['profiles'][other]['data_dir']):
                    raise SafeError('Claude ยังปิดไม่เสร็จ กรุณาออกจากแอปตามปกติแล้วลองอีกครั้ง')

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
        if self.primary_mode():
            self.close_primary_claude()
            requested = self.auth_store().state()['active']
            store = self.checkpoint_primary()
            if self.primary_identity() is None:
                raise SafeError('Claude ยังไม่ได้บันทึกการเข้าสู่ระบบในหน้าต่างหลัก ข้อมูลบัญชีเดิมยังอยู่')
            if requested != store.state()['active']:
                raise SafeError('บัญชีที่ล็อกอินเป็นรายการที่บันทึกไว้แล้ว จึงไม่เชื่อมซ้ำกับรายการใหม่ กรุณาเลือกอีเมลอีกบัญชี')
            return 'บันทึกบัญชี Claude แล้ว · เปิดกลับได้จากปุ่มใช้บัญชีนี้ · session เดิมยังอยู่'
        profiles = self.config()['profiles']
        if profiles:
            self.close_idle_claude(self.config(), self.claude_modules())
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
        for key, profile in profiles.items():
            directory = Path(profile['data_dir'])
            cookies = next((p for p in (directory / 'Network/Cookies', directory / 'Cookies') if p.is_file()), None)
            if cookies is None:
                continue
            try:
                with contextlib.closing(sqlite3.connect(cookies.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                    rows = db.execute("SELECT host_key, encrypted_value FROM cookies WHERE host_key='.claude.ai' AND name='sessionKey'").fetchall()
            except sqlite3.OperationalError:
                raise SafeError('Claude ยังล็อกข้อมูลเข้าสู่ระบบอยู่ กรุณาออกจาก Claude ตามปกติแล้วกดเชื่อมข้อมูลอีกครั้ง') from None
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
        pending = len(profiles) - count
        return f'เชื่อม Claude สำเร็จ {count} บัญชี' + (f' · อีก {pending} รายการยังไม่ได้เข้าสู่ระบบ กดเข้าสู่ระบบต่อบนการ์ดเดิม ไม่ต้องเพิ่มบัญชีซ้ำ' if pending else ' · กดใช้บัญชีนี้เพื่อเปิดกลับได้')

    def sync(self):
        switcher = self.claude_modules()
        if self.primary_mode():
            try:
                self.primary_sync_directories()
            except SafeError:
                return 'ยังไม่ได้ซิงก์ · รอบัญชีและโฟลเดอร์ Code ครบทุกรายการ'
            if any(switcher.win_is_app(name, cmd) for _, _, name, cmd in switcher.win_processes()):
                return 'ข้ามซิงก์ระหว่าง Claude เปิดอยู่ · ซิงก์เมื่อออกและสลับบัญชี'
            return self.setup()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if switcher.cs_sync.sync(self.config().get('sync_dirs', [])):
                raise SafeError('Session sync paused for safety')
        return 'Sync complete'

    def setup(self):
        switcher = self.claude_modules()
        conf = self.config()
        primary = self.primary_mode()
        if primary:
            directories = self.primary_sync_directories()
            self.close_primary_claude()
        else:
            roots = [Path(p['data_dir']) / 'claude-code-sessions' for p in conf['profiles'].values()]
            roots.append(self.claude_primary_data() / 'claude-code-sessions')
            directories = sorted({str(p) for root in roots for p in root.glob('*/*') if p.is_dir() and not p.is_symlink()})
        if not directories:
            raise SafeError('Open the Claude Code tab once for each account, then retry Setup')
        if primary:
            store = self.auth_store()
            store.prepare()
            backup = store.root / 'session-backups' / uuid.uuid4().hex
            for index, directory in enumerate(directories):
                store.copy_item(Path(directory), backup / str(index))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if switcher.cs_sync.sync(directories):
                raise SafeError('Session sync paused for safety')
        if primary:
            manifests = [{p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(directory).glob('*.json') if p.is_file()} for directory in directories]
            if not all(value == manifests[0] for value in manifests[1:]):
                raise SafeError('ยังแชร์ session ไม่ครบทุกไฟล์ สำเนาก่อนซิงก์ยังอยู่ ไม่มีการยืนยันสำเร็จ')
        conf['sync_dirs'] = directories
        atomic_json(self.claude_config, conf)
        return 'Shared session folders registered. Sync runs on switching and while AI Accounts is open.'

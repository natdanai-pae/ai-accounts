import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

SOURCE = pathlib.Path(__file__).with_name('backend.py')

class BackendTests(unittest.TestCase):
    def test_backend_exists(self):
        self.assertTrue(SOURCE.exists(), 'portable backend is not implemented')

    @unittest.skipUnless(SOURCE.exists(), 'implementation pending')
    def test_private_list_and_validation(self):
        spec = importlib.util.spec_from_file_location('backend', SOURCE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            backend = mod.Backend(root)
            self.assertEqual(backend.list_accounts()['accounts'], [])
            profiles = root / '.codex-switch/profiles'
            for i in range(40):
                mod.atomic_json(profiles / str(i) / 'metadata.json', {'email': f'user{i}@example.test'})
            accounts = backend.list_accounts()['accounts']
            self.assertEqual(len(accounts), 40)
            self.assertEqual(len({a['id'] for a in accounts}), 40)
            self.assertNotIn('token', json.dumps(accounts))
            for key in ['../a', '/tmp', '', 'a/b', 'a\\b']:
                with self.assertRaises(mod.SafeError):
                    mod.valid_key(key)
            path = root / 'private/config.json'
            mod.atomic_json(path, {'old': 1})
            mod.atomic_json(path, {'new': 2})
            if os.name != 'nt':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(json.loads(path.with_suffix('.json.backup').read_text()), {'old': 1})
            path.write_text('{broken')
            with self.assertRaises(mod.SafeError):
                mod.read_json(path, {})

    @unittest.skipUnless(SOURCE.exists(), 'implementation pending')
    def test_failed_login_does_not_register_account(self):
        import backend as mod
        with tempfile.TemporaryDirectory() as tmp:
            backend = mod.Backend(tmp)
            with patch.object(backend, 'run', side_effect=mod.SafeError('cancelled')):
                with self.assertRaises(mod.SafeError):
                    backend.add('claude', 'New account')
            self.assertEqual(backend.list_accounts()['accounts'], [])
            self.assertFalse(backend.claude_config.exists())

    @unittest.skipUnless(SOURCE.exists(), 'implementation pending')
    def test_connect_failure_retains_configuration(self):
        import backend as mod
        with tempfile.TemporaryDirectory() as tmp:
            backend = mod.Backend(tmp)
            conf = pathlib.Path(tmp) / '.config/codexbar/config.json'
            mod.atomic_json(conf, {'version': 1, 'providers': [{'id': 'unrelated', 'enabled': True}]})
            original = conf.read_bytes()
            with patch.object(backend, 'config', side_effect=mod.SafeError('malformed')):
                with self.assertRaises(mod.SafeError):
                    backend.connect()
            self.assertEqual(conf.read_bytes(), original)

    @unittest.skipUnless(SOURCE.exists(), 'implementation pending')
    def test_cookie_host_binding_and_invalid_token(self):
        import backend as mod
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
        password = b'fixture-only-password'
        key = mod.hashlib.pbkdf2_hmac('sha1', password, b'saltysalt', 1003, 16)
        def encrypt(data):
            pad = PKCS7(128).padder()
            enc = Cipher(algorithms.AES(key), modes.CBC(b' ' * 16)).encryptor()
            return b'v10' + enc.update(pad.update(data) + pad.finalize()) + enc.finalize()
        token = b'sk-ant-fixture-only'
        encoded = encrypt(mod.hashlib.sha256(b'.claude.ai').digest() + token)
        self.assertEqual(mod.decrypt_cookie('.claude.ai', encoded, password), token.decode())
        with self.assertRaises((mod.SafeError, UnicodeDecodeError)):
            mod.decrypt_cookie('.wrong-origin.test', encoded, password)
        with self.assertRaises(mod.SafeError):
            mod.decrypt_cookie('.claude.ai', encrypt(b'invalid'), password)

    @unittest.skipUnless(SOURCE.exists(), 'implementation pending')
    def test_connect_preserves_other_providers(self):
        import backend as mod
        with tempfile.TemporaryDirectory() as tmp:
            backend = mod.Backend(tmp)
            conf = pathlib.Path(tmp) / '.config/codexbar/config.json'
            mod.atomic_json(conf, {'version': 1, 'providers': [{'id': 'unrelated', 'enabled': True}]})
            backend.connect()
            self.assertEqual(mod.read_json(conf, {})['providers'][0], {'id': 'unrelated', 'enabled': True})

    @unittest.skipUnless(SOURCE.exists(), 'implementation pending')
    def test_connect_rolls_back_if_identity_write_fails(self):
        import backend as mod
        with tempfile.TemporaryDirectory() as tmp:
            backend = mod.Backend(tmp)
            conf = pathlib.Path(tmp) / '.config/codexbar/config.json'
            original = {'version': 1, 'providers': []}
            mod.atomic_json(conf, original)
            write = mod.atomic_json
            def fail_identity(path, data):
                if pathlib.Path(path).name == 'identities.json':
                    raise OSError('fixture disk failure')
                write(path, data)
            with patch.object(mod, 'atomic_json', side_effect=fail_identity):
                with self.assertRaises(OSError):
                    backend.connect()
            self.assertEqual(mod.read_json(conf, {}), original)

    @unittest.skipIf(os.name == 'nt', 'Mac CodexBar subprocess fixture')
    def test_partial_quota_nonzero_keeps_valid_rows(self):
        import backend as mod
        with tempfile.TemporaryDirectory() as tmp:
            backend = mod.Backend(tmp, tmp)
            cli = pathlib.Path(tmp) / 'codexbar/Helpers/CodexBarCLI'
            cli.parent.mkdir(parents=True)
            cli.write_text('#!/bin/sh\nprintf \'[{"provider":"codex","account":"healthy"}]\'\nexit 1\n')
            cli.chmod(0o700)
            self.assertEqual(backend.usage('codex')[0]['account'], 'healthy')
            with self.assertRaises(mod.SafeError):
                backend.run([str(cli)])

    def test_sync_rejects_foreign_directory(self):
        import backend as mod
        with tempfile.TemporaryDirectory() as tmp:
            backend = mod.Backend(tmp)
            mod.atomic_json(backend.claude_config, {'profiles': {}, 'sync_dirs': ['/tmp/unrelated']})
            with self.assertRaises(mod.SafeError):
                backend.config()

    @unittest.skipIf(os.name == 'nt', 'Mac launchd fixture; Windows adapter has separate tests')
    def test_setup_replaces_same_job_and_rolls_back_failure(self):
        import backend as mod
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as tmp:
                backend = mod.Backend(tmp)
                profile = pathlib.Path(tmp) / 'Library/Application Support/Claude'
                session = profile / 'claude-code-sessions/account/org'
                session.mkdir(parents=True)
                old_conf = {'profiles': {'a': {'label': 'A', 'data_dir': str(profile)}}, 'sync_dirs': []}
                mod.atomic_json(backend.claude_config, old_conf)
                agent = pathlib.Path(tmp) / 'Library/LaunchAgents/io.github.claude-switcher.sync.plist'
                agent.parent.mkdir(parents=True)
                original = mod.plistlib.dumps({'Label': 'io.github.claude-switcher.sync', 'ProgramArguments': ['old-helper']})
                agent.write_bytes(original)
                calls = []
                def run(args, **kwargs):
                    calls.append(args)
                    if fail and len(calls) == 2:
                        raise mod.SafeError('fixture bootstrap failed')
                modules = SimpleNamespace(C=SimpleNamespace(detect_session_dirs=lambda _: [str(session)]))
                with patch.object(mod.sys, 'frozen', True, create=True), patch.object(mod.sys, 'executable', '/Applications/AI Accounts.app/Contents/Resources/backend/aiaccounts-helper'), patch.object(backend, 'claude_modules', return_value=modules), patch.object(backend, 'run', side_effect=run):
                    if fail:
                        with self.assertRaises(mod.SafeError):
                            backend.setup()
                        self.assertEqual(agent.read_bytes(), original)
                        self.assertEqual(mod.read_json(backend.claude_config, {}), old_conf)
                    else:
                        backend.setup()
                        self.assertEqual(mod.plistlib.loads(agent.read_bytes())['ProgramArguments'][-1], 'sync')
                        self.assertEqual(backend.config()['sync_dirs'], [str(session)])
                self.assertEqual(calls[0][1], 'bootout')
                self.assertEqual(agent.with_suffix('.plist.backup').read_bytes(), original)

if __name__ == '__main__':
    unittest.main()

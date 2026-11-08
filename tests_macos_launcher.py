"""Regression: account switching must not reopen an older desktop core."""
import importlib.util
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.find_spec('macos_codex')

@unittest.skipIf(os.name == 'nt', 'macOS launcher fixture uses POSIX executables')
class MacLauncherTests(unittest.TestCase):
    def fixture(self, root, name, version, build=1, bundle='com.openai.codex'):
        app = root / name
        contents = app / 'Contents'
        cli = contents / 'Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
        cli.parent.mkdir(parents=True)
        cli.write_text('#!/bin/sh\nif [ "$1" = --version ]; then echo "codex-cli '+version+'"; else printf "%s\\n" "$@"; fi\n')
        cli.chmod(0o700)
        (contents / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':bundle,'CFBundleVersion':str(build)}))
        return app, cli

    def test_newest_signed_core_selected_not_first_app_name(self):
        self.assertIsNotNone(SPEC, 'explicit desktop/core selection is missing')
        import macos_codex as mod
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            self.fixture(root,'ChatGPT.app','0.144.0-alpha.4',99)
            expected=self.fixture(root,'Codex.app','0.167.0-alpha.3.2',1)
            with patch.object(mod,'verify_signature', return_value=True):
                self.assertEqual(mod.select_desktop([root]), expected)

    def test_old_or_unsigned_desktop_blocked_before_switch(self):
        self.assertIsNotNone(SPEC, 'desktop compatibility preflight is missing')
        import macos_codex as mod
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            self.fixture(root,'ChatGPT.app','0.144.0-alpha.4')
            with patch.object(mod,'verify_signature',return_value=True):
                with self.assertRaises(mod.LaunchError): mod.select_desktop([root])
            self.fixture(root,'Codex.app','0.167.0-alpha.3.2')
            with patch.object(mod,'verify_signature',return_value=False):
                with self.assertRaises(mod.LaunchError): mod.select_desktop([root])

    def test_shim_opens_selected_app_and_overrides_stale_core(self):
        self.assertIsNotNone(SPEC, 'scoped desktop launcher is missing')
        import macos_codex as mod
        with tempfile.TemporaryDirectory(prefix="launcher's fixture ") as d:
            root=Path(d); app,cli=self.fixture(root,'Codex.app','0.167.0-alpha.3.2')
            opener=root/'open'; receipt=root/'receipt'
            opener.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$RECEIPT"\n')
            opener.chmod(0o700)
            with mod.switch_tool_dir(app,cli,opener=opener) as directory:
                env=dict(os.environ,RECEIPT=str(receipt),CODEX_CLI_PATH='/old/codex')
                subprocess.run([str(directory/'codex'),'app'],env=env,check=True)
                self.assertEqual(receipt.read_text().splitlines(),['-a',str(app),'--env','CODEX_CLI_PATH='+str(cli)])
                r=subprocess.run([str(directory/'codex'),'features','list'],capture_output=True,text=True,check=True)
                self.assertEqual(r.stdout.splitlines(),['features','list'])
            self.assertFalse(directory.exists())

    def test_real_backend_switch_uses_selected_core_and_never_legacy_cli(self):
        import backend
        import macos_codex as mod
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); apps=root/'apps'
            app,cli=self.fixture(apps,'Codex.app','0.167.0-alpha.3.2')
            b=backend.Backend(root)
            b.resources=root/'resources'; tools=b.resources/'bin'; tools.mkdir(parents=True)
            receipt=root/'opened'
            opener=root/'open'; opener.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > '+__import__('shlex').quote(str(receipt))+'\n'); opener.chmod(0o700)
            switch=tools/'codex-switch'; switch.write_text('#!/bin/sh\nexec codex app\n'); switch.chmod(0o700)
            legacy=tools/'codex'; legacy.write_text('#!/bin/sh\nexit 91\n'); legacy.chmod(0o700)
            profile=root/'.codex-switch/profiles/fixture'; profile.mkdir(parents=True)
            (profile/'metadata.json').write_text('{"email":"fixture@example.test"}')
            select=mod.select_desktop; scope=mod.switch_tool_dir
            with patch.object(mod,'verify_signature',return_value=True), patch.object(mod,'select_desktop',side_effect=lambda: select([apps])), patch.object(mod,'switch_tool_dir',side_effect=lambda a,c:scope(a,c,opener=opener)):
                b.switch('codex','fixture')
            self.assertEqual(receipt.read_text().splitlines(),['-a',str(app),'--env','CODEX_CLI_PATH='+str(cli)])

    def test_backend_blocks_old_core_without_invoking_account_switch(self):
        import backend
        import macos_codex as mod
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); apps=root/'apps'
            self.fixture(apps,'ChatGPT.app','0.144.0-alpha.4')
            b=backend.Backend(root); b.resources=root/'resources'
            tools=b.resources/'bin'; tools.mkdir(parents=True)
            touched=root/'account-changed'
            switch=tools/'codex-switch'; switch.write_text('#!/bin/sh\ntouch '+__import__('shlex').quote(str(touched))+'\n'); switch.chmod(0o700)
            profile=root/'.codex-switch/profiles/fixture'; profile.mkdir(parents=True)
            (profile/'metadata.json').write_text('{"email":"fixture@example.test"}')
            select=mod.select_desktop
            with patch.object(mod,'verify_signature',return_value=True),patch.object(mod,'select_desktop',side_effect=lambda:select([apps])):
                with self.assertRaises(backend.SafeError): b.switch('codex','fixture')
            self.assertFalse(touched.exists())

if __name__=='__main__': unittest.main()

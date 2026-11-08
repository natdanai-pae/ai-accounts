import base64
import json
import subprocess
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch


class NotificationTests(unittest.TestCase):
    @unittest.skipUnless(__import__('sys').platform == 'win32', 'Actual Windows Shell shortcut fixture')
    def test_registration_backup_and_legacy_migration_actual_shell(self):
        import hashlib
        import os
        import tempfile
        from pathlib import Path
        import windows_notifications as n
        ps = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        def execute(script, succeeds=True):
            command = base64.b64encode(script.encode('utf-16le')).decode('ascii')
            completed = subprocess.run([str(ps), '-NoProfile', '-NonInteractive', '-EncodedCommand', command], capture_output=True, timeout=30, creationflags=0x08000000)
            if succeeds:
                self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors='replace'))
            else:
                self.assertNotEqual(completed.returncode, 0)
            return completed.stdout.decode('utf-8-sig', errors='replace')
        for scenario in ('missing', 'existing', 'legacy', 'unrelated', 'unowned', 'collision'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                programs, local = base / 'Programs', base / 'Local'
                programs.mkdir(); local.mkdir()
                target = local / 'Programs' / 'AI Accounts-notifications-beta3' / 'AI Accounts.exe'
                target.parent.mkdir(parents=True); target.touch()
                current_target = target
                if scenario in ('legacy', 'collision'):
                    current_target = local / 'Programs' / 'AI Accounts-beta4' / 'AI Accounts.exe'
                    current_target.parent.mkdir(); current_target.touch()
                payload = {'operation': 'register', 'appId': n.APP_ID, 'executable': str(current_target), 'arguments': '', 'icon': str(current_target) + ',0'}
                prefix = "$data = '" + json.dumps(payload).replace("'", "''") + "' | ConvertFrom-Json\n"
                literal = lambda path: "'" + str(path).replace("'", "''") + "'"
                canonical = programs / 'AI Accounts.lnk'
                legacy = programs / 'AI Accounts.before-notifications.lnk'
                original = None
                if scenario != 'missing':
                    path = canonical if scenario == 'existing' else legacy
                    description = 'Unrelated App' if scenario == 'unrelated' else 'AI Accounts 0.3.0 Beta 3'
                    old_target = target
                    if scenario == 'unowned':
                        old_target = base / 'unowned' / 'AI Accounts.exe'
                        old_target.parent.mkdir(); old_target.touch()
                    execute(prefix + "$l=(New-Object -ComObject WScript.Shell).CreateShortcut(" + literal(path) + "); $l.TargetPath=" + literal(old_target) + "; $l.Description='" + description + "'; $l.Save()")
                    original = path.read_bytes()
                backups = local / 'AI Accounts' / 'shortcut-backups'
                if scenario == 'collision':
                    backups.mkdir(parents=True)
                    collision = backups / ('legacy-' + hashlib.sha256(original).hexdigest().upper() + '.lnk')
                    collision.write_bytes(b'keep unrelated collision')
                # Execute production registration through COM identity readback; stop
                # before any WinRT notifier/bootstrap, never touch real Start Menu.
                fragment = n._SCRIPT.split('  [Windows.UI.Notifications.ToastNotificationManager,', 1)[0]
                fragment = fragment.replace("[Environment]::GetFolderPath('Programs')", literal(programs)).replace("[Environment]::GetFolderPath('LocalApplicationData')", literal(local))
                script = prefix + fragment + "\nWrite-Output 'fixture-registered'\n} catch { Write-Error $_; exit 1 }"
                if scenario == 'collision':
                    execute(script, succeeds=False)
                    self.assertEqual(legacy.read_bytes(), original)
                    self.assertEqual(collision.read_bytes(), b'keep unrelated collision')
                    self.assertFalse(canonical.exists())
                    continue
                self.assertIn('fixture-registered', execute(script))
                self.assertTrue(canonical.exists())
                if scenario == 'existing':
                    self.assertEqual((backups / 'AI Accounts.before-notifications.lnk').read_bytes(), original)
                if scenario == 'legacy':
                    self.assertFalse(legacy.exists())
                    self.assertIn(original, [p.read_bytes() for p in backups.glob('*.lnk')])
                if scenario in ('unrelated', 'unowned'):
                    self.assertEqual(legacy.read_bytes(), original)
                before = {p.name: p.read_bytes() for p in backups.glob('*.lnk')} if backups.exists() else {}
                self.assertIn('fixture-registered', execute(script))
                for name, data in before.items():
                    self.assertEqual((backups / name).read_bytes(), data)
                self.assertFalse((programs / 'AI Accounts.before-notifications.lnk').exists() if scenario in ('missing', 'existing', 'legacy') else False)

    def test_xml_round_trip_and_no_actions(self):
        from windows_notifications import toast_xml
        title, body = 'AI Accounts <ทดสอบ> & "', 'Codex บัญชี 2 > 50% $(whoami)'
        tree = ET.fromstring(toast_xml(title, body))
        self.assertEqual([e.text for e in tree.findall('.//text')], [title, body])
        self.assertIsNone(tree.find('actions'))
        for value in ('bad\x00text', 'bad\ud800text', '', 'a' * 1001):
            with self.assertRaises(ValueError):
                toast_xml('AI Accounts', value)

    def test_payload_is_data_not_powershell(self):
        from windows_notifications import encoded_script
        payload = {'body': "'; Start-Process evil; # ไทย"}
        script = base64.b64decode(encoded_script(payload)).decode('utf-16le')
        self.assertNotIn(payload['body'], script)
        encoded = script.split("FromBase64String('", 1)[1].split("')", 1)[0]
        self.assertEqual(json.loads(base64.b64decode(encoded)), payload)

    def test_result_parser_rejects_untrusted_output(self):
        from windows_notifications import parse_result
        self.assertEqual(parse_result('{"status":"accepted"}')['ok'], True)
        self.assertEqual(parse_result('{"status":"disabled"}')['ok'], False)
        for raw in ('', 'secret-token', '{"status":"secret-token"}', '[]', '{"status":"accepted","secret":"x"}'):
            result = parse_result(raw)
            self.assertNotIn('secret', json.dumps(result))
        self.assertEqual(parse_result('[]')['status'], 'failed')

    def test_timeout_is_safe_and_non_windows_is_noop(self):
        import windows_notifications as n
        with patch.object(n.sys, 'platform', 'darwin'), patch.object(n.subprocess, 'run') as run:
            self.assertEqual(n.send_notification('AI Accounts', 'Codex บัญชี 1')['status'], 'unsupported')
            run.assert_not_called()
        with patch.object(n.sys, 'platform', 'win32'), patch.object(n.subprocess, 'run', side_effect=subprocess.TimeoutExpired('secret', 20)):
            self.assertEqual(n.send_notification('AI Accounts', 'Codex บัญชี 1')['status'], 'timeout')

    def test_privacy_guard_and_invalid_target_do_not_launch(self):
        import windows_notifications as n
        with patch.object(n.subprocess, 'run') as run:
            self.assertEqual(n.send_notification('AI Accounts', 'a@example.com')['status'], 'invalid')
            self.assertEqual(n.register_notifications(executable='/missing/aiaccounts.exe')['status'], 'invalid')
            run.assert_not_called()

    def test_subprocess_failure_never_exposes_output(self):
        import windows_notifications as n
        for code, output in ((1, b'secret-token'), (0, b'not-json'), (0, b'{"status":"disabled"}')):
            with patch.object(n.sys, 'platform', 'win32'), patch.object(n.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, output, b'private')) as run:
                result = n.send_notification('AI Accounts', 'Claude บัญชี 3')
                self.assertFalse(result['ok'])
                self.assertNotIn('private', str(result))
                self.assertNotIn('secret-token', str(result))
                self.assertEqual(run.call_args.kwargs['timeout'], 20)
                self.assertNotIn('shell', run.call_args.kwargs)

    def test_registration_arguments_round_trip(self):
        import tempfile
        from pathlib import Path
        import windows_notifications as n
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'AI Accounts.exe'
            executable.touch()
            with patch.object(n, '_run', return_value={'ok': True}) as run:
                n.register_notifications(executable, ['a path', "'; harmless"])
                payload = run.call_args.args[0]
                self.assertEqual(payload['appId'], 'AIAccounts.Desktop')
                self.assertEqual(payload['executable'], str(executable.resolve()))
                self.assertEqual(payload['arguments'], subprocess.list2cmdline(['a path', "'; harmless"]))
                self.assertEqual(payload['operation'], 'register')


    def test_failure_diagnostics_are_bounded_and_do_not_leak_raw_errors(self):
        from windows_notifications import parse_result
        value=parse_result('{"status":"failed","stage":"setting","code":"0x80070490","message":"private-token"}')
        self.assertEqual(value['diagnostic'],{'stage':'setting','code':'0x80070490'})
        self.assertIn('0x80070490',value['message'])
        self.assertNotIn('private-token',str(value))
        for stage,code in [('private-token','0x80070490'),('setting','private-token')]:
            value=parse_result(json.dumps({'status':'failed','stage':stage,'code':code}))
            self.assertNotIn('diagnostic',value)
            self.assertNotIn('private-token',str(value))

    @unittest.skipUnless(__import__('sys').platform == 'win32', 'Windows PowerShell regression')
    def test_powershell_failure_reports_innermost_hresult_without_raw_exception(self):
        import os
        from pathlib import Path
        import windows_notifications as n
        ps=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
        catch=n._SCRIPT.rsplit('} catch {',1)[1]
        script="$ErrorActionPreference='Stop'; $stage='setting'; try { throw [Exception]::new('private-token', [Runtime.InteropServices.COMException]::new('private-token', -2147023728)) } catch {"+catch
        command=base64.b64encode(script.encode('utf-16le')).decode('ascii')
        completed=subprocess.run([str(ps),'-NoProfile','-NonInteractive','-EncodedCommand',command],capture_output=True,timeout=20,creationflags=0x08000000)
        self.assertEqual(completed.returncode,0,completed.stderr.decode(errors='replace'))
        result=n.parse_result(completed.stdout.decode('utf-8-sig').strip())
        self.assertEqual(result['diagnostic'],{'stage':'setting','code':'0x80070490'})
        self.assertNotIn('private-token',str(result))

    def test_saved_opt_in_registers_on_startup_but_opt_out_and_fixture_do_not(self):
        from windows_gui import restore_notification_registration
        from unittest.mock import Mock
        for enabled,synthetic,expected in [(True,False,1),(False,False,0),(True,True,0)]:
            callback=Mock()
            restore_notification_registration(enabled,synthetic,callback)
            self.assertEqual(callback.call_count,expected)
            if expected:callback.assert_called_once_with('',register=True)

if __name__ == '__main__':
    unittest.main()

import base64
import json
import subprocess
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch


class NotificationTests(unittest.TestCase):
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

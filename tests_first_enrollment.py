import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from backend import atomic_json,read_json,SafeError
from windows_backend import WindowsBackend

class FirstEnrollmentTests(unittest.TestCase):
    def test_add_adopts_verified_primary_without_erasing_login_or_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=WindowsBackend(root=Path(tmp).resolve())
            live=b.local/'Claude-Data/claude_pzs8sxrjxfjjc'
            live.mkdir(parents=True)
            atomic_json(live/'config.json',{'lastKnownAccountUuid':'fixture-uuid'})
            (live/'Local State').write_text('fixture-encryption-state')
            session=live/'claude-code-sessions/fixture-uuid/org/local_test.json'
            atomic_json(session,{'test':'original-session'})
            before={str(p.relative_to(live)):p.read_bytes() for p in live.rglob('*') if p.is_file()}
            identity={'email':'first@example.test','uuid':'fixture-uuid','token':'fixture-token'}
            with patch.object(b,'claude_app',return_value=Path(tmp)/'Store/app/Claude.exe'),patch.object(b,'primary_mode',return_value=True),patch.object(b,'close_primary_claude'),patch.object(b,'primary_identity',return_value=identity),patch.object(b,'launch_primary') as launch:
                b.add('claude','First account')
            profiles=b.config()['profiles'];self.assertEqual(len(profiles),1)
            key=next(iter(profiles));store=b.auth_store();state=store.state()
            self.assertEqual(state['active'],key)
            saved=store.root/'snapshots'/state['snapshots'][key]
            self.assertEqual((saved/'Local State').read_text(),'fixture-encryption-state')
            self.assertEqual(read_json(b.state/'identities.json',{})[key]['uuid'],'fixture-uuid')
            self.assertEqual(before,{str(p.relative_to(live)):p.read_bytes() for p in live.rglob('*') if p.is_file()})
            launch.assert_called_once()

    def test_enrollment_does_not_guess_among_existing_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=WindowsBackend(root=Path(tmp).resolve())
            profiles={k:{'data_dir':str(b.roaming/k)} for k in ('a','b')}
            atomic_json(b.claude_config,{'profiles':profiles,'sync_dirs':[]})
            identity={'email':'first@example.test','uuid':'fixture-uuid','token':'fixture-token'}
            with patch.object(b,'primary_mode',return_value=True),patch.object(b,'close_primary_claude'),patch.object(b,'primary_identity',return_value=identity),patch.object(b,'launch_primary') as launch:
                with self.assertRaises(SafeError):b.login('claude','b')
            self.assertEqual(b.auth_store().state(),{'active':None,'snapshots':{}})
            self.assertFalse((b.state/'identities.json').exists())
            launch.assert_not_called()

    def test_unverified_primary_is_not_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=WindowsBackend(root=Path(tmp).resolve())
            atomic_json(b.claude_config,{'profiles':{'a':{'data_dir':str(b.roaming/'a')}},'sync_dirs':[]})
            with patch.object(b,'primary_mode',return_value=True),patch.object(b,'close_primary_claude'),patch.object(b,'primary_identity',side_effect=SafeError('Chat/Code mismatch')),patch.object(b,'launch_primary') as launch:
                with self.assertRaises(SafeError):b.login('claude','a')
            self.assertFalse((b.state/'identities.json').exists())
            self.assertFalse(b.auth_store().state()['snapshots'])
            launch.assert_not_called()

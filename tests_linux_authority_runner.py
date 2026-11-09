import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

class RunnerTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('linux_authority_runner'),'Linux local scheduler missing')
        import linux_authority_runner as runner
        return runner

    def test_metadata_poll_and_analysis_schedules_are_independent(self):
        r=self.module()
        a=Mock();collect=Mock(return_value=[]);infer=Mock()
        scheduler=r.Scheduler(a,collect,infer,poll_seconds=15,analysis_seconds=600,now=1000)
        scheduler.tick(now=1000)
        collect.assert_called_once();a.analyze.assert_not_called()
        scheduler.tick(now=1010);self.assertEqual(collect.call_count,1)
        scheduler.tick(now=1015);self.assertEqual(collect.call_count,2)
        scheduler.tick(now=1600);a.analyze.assert_called_once_with(infer)
        a.call('ai_accounts_summary',{})
        self.assertEqual(collect.call_count,3);self.assertEqual(a.analyze.call_count,1)

    def test_busy_inference_keeps_last_decision_and_no_fallback(self):
        r=self.module();from backend import SafeError
        a=Mock();a.analyze.side_effect=SafeError('must not log private contents')
        scheduler=r.Scheduler(a,lambda:[],Mock(),now=1000,analyze_on_start=True)
        self.assertEqual(scheduler.tick(now=1000)['analysis'],'deferred')
        a.reload_decisions.assert_called_once()
        # It does not retry the analysis on each poll.
        scheduler.tick(now=1015);self.assertEqual(a.analyze.call_count,1)

    def test_native_lease_identity_is_verified_before_running_shared_advisor(self):
        r=self.module()
        import contextlib
        lease_events=[]
        class Router:
            def leases(self,alias,maintenance=False):
                @contextlib.contextmanager
                def scope():
                    lease_events.append((alias,maintenance));yield
                return scope()
            def native_identity(self,alias):return 'native-pin'
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'accounts.json'
            source.write_text(json.dumps({'codex-1':{'expected_identity':'native-pin','checked_epoch':1000,'expires_epoch':10000,
                'availability':'ready','windows_used_percent':{'weekly':10},'windows_reset_epoch':{'weekly':6000}}}))
            run=Mock(return_value={'recommendations':[]})
            callback=r.leased_infer(Router(),source,Path('/bin/codex-fixture'),resources=Path(d),clock=lambda:1000,infer_function=run)
            self.assertEqual(callback({'accounts':[]}),{'recommendations':[]})
            self.assertEqual(lease_events,[('codex-1',False)])
            run.assert_called_once()
            source.write_text(source.read_text().replace('native-pin','different-pin'))
            with self.assertRaises(Exception):callback({'accounts':[]})
            self.assertEqual(run.call_count,1)

    def test_once_analysis_runs_publisher_pipeline_with_fixture_cli_only(self):
        self.module()
        import os,subprocess,sys,time
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);now=time.time()
            source=root/'accounts.json';state=root/'decision.json'
            meta={p+'-1':{'expected_identity':'native-pin','checked_epoch':now,'expires_epoch':now+10000,
                'availability':'ready','windows_used_percent':{'weekly':10},'windows_reset_epoch':{'weekly':now+6000}}
                for p in ('codex','claude')}
            source.write_text(json.dumps(meta))
            router=root/'router.py'
            router.write_text('import contextlib\n@contextlib.contextmanager\ndef leases(alias,maintenance=False):\n assert alias=="codex-1" and not maintenance\n yield\ndef native_identity(alias):return "native-pin"\n')
            cli=root/'codex'
            cli.write_text('#!'+sys.executable+'\nimport json,sys\nprompt=sys.stdin.read()\ns=json.loads(prompt.split("SNAPSHOT\\n")[-1])\na={"recommendations":[{"provider":p,"account":next(a["account"] for a in s["accounts"] if a["provider"]==p),"reason":"Fixture quota advice","plan":"Useful work before reset"} for p in ("codex","claude")]}\nopen(sys.argv[sys.argv.index("--output-last-message")+1],"w").write(json.dumps(a))\n')
            cli.chmod(0o700)
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('linux_authority_runner.py')),'--once-analysis','--state-source',str(source),'--decision-state',str(state),'--router-module',str(router),'--codex-executable',str(cli)],capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            decision=json.loads(state.read_text())
            self.assertEqual(set(decision['decisions']),{'codex','claude'})
            self.assertEqual(json.loads(result.stdout)['status'],'analysis_updated')
            self.assertNotIn('native-pin',state.read_text())
            self.assertEqual(state.stat().st_mode & 0o777,0o600)

    def test_inference_defers_when_normal_capacity_lease_is_busy(self):
        r=self.module()
        import contextlib
        for reason in ('account_busy','global_capacity','memory_capacity','maintenance_gate'):
            class Router:
                @contextlib.contextmanager
                def leases(self,alias,maintenance=False):
                    self.maintenance=maintenance
                    raise RuntimeError(reason)
                    yield
                def native_identity(self,alias):raise AssertionError('Must not read identity before capacity admission')
            router=Router();run=Mock()
            callback=r.leased_infer(router,Path('/unused/source'),Path('/unused/codex'),infer_function=run)
            with self.assertRaises(RuntimeError):callback({'accounts':[]})
            self.assertFalse(router.maintenance);run.assert_not_called()

    def test_inference_requires_180_seconds_of_credential_runway(self):
        r=self.module()
        import contextlib
        class Router:
            def leases(self,alias,maintenance=False):return contextlib.nullcontext()
            def native_identity(self,alias):return 'native-pin'
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'accounts.json'
            meta={'codex-1':{'expected_identity':'native-pin','checked_epoch':1000,'expires_epoch':1179,
                'availability':'ready','windows_used_percent':{'weekly':10},'windows_reset_epoch':{'weekly':6000}}}
            source.write_text(json.dumps(meta));run=Mock(return_value={})
            callback=r.leased_infer(Router(),source,Path('/unused/codex'),clock=lambda:1000,infer_function=run)
            with self.assertRaises(Exception):callback({'accounts':[]})
            run.assert_not_called()
            meta['codex-1']['expires_epoch']=1180;source.write_text(json.dumps(meta))
            self.assertEqual(callback({'accounts':[]}),{})
            run.assert_called_once()

if __name__=='__main__':unittest.main()

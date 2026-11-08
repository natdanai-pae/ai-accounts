import unittest

class ConfirmationTests(unittest.TestCase):
    def test_confirmation_reserves_worker_until_answer(self):
        from windows_gui import confirm_idle, refresh_due
        state = {'busy': False}
        def ask():
            self.assertTrue(state['busy'])
            self.assertFalse(refresh_due(0, 400, state['busy']))
            return True
        self.assertTrue(confirm_idle(state, ask))
        self.assertFalse(state['busy'])

    def test_cancel_and_exception_release_worker(self):
        from windows_gui import confirm_idle
        state = {'busy': False}
        self.assertFalse(confirm_idle(state, lambda: False))
        self.assertFalse(state['busy'])
        def failed():
            raise RuntimeError('closed dialog')
        with self.assertRaises(RuntimeError): confirm_idle(state, failed)
        self.assertFalse(state['busy'])

    def test_busy_worker_does_not_open_confirmation(self):
        from windows_gui import confirm_idle
        from unittest.mock import Mock
        state = {'busy': True}; ask=Mock()
        self.assertFalse(confirm_idle(state, ask))
        ask.assert_not_called()
        self.assertTrue(state['busy'])
    def test_connect_dialog_cannot_start_background_sync(self):
        import ast, pathlib
        import windows_gui
        tree=ast.parse(pathlib.Path(windows_gui.__file__).read_text(encoding='utf-8'))
        fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='connect_accounts')
        state={'busy':False,'accounts':[{'provider':'claude'}]}; calls=[]
        def ask(*args, **kwargs):
            self.assertTrue(state['busy'])
            return True
        from types import SimpleNamespace
        namespace={'state':state,'status':SimpleNamespace(set=lambda _:None),'messagebox':SimpleNamespace(askokcancel=ask),'confirm_idle':windows_gui.confirm_idle,'root':None,'work':lambda args:calls.append((args,state['busy']))}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'connect_callback','exec'),namespace)
        namespace['connect_accounts']()
        self.assertEqual(calls,[(['connect'],False)])

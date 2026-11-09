import importlib.util
import unittest
class PatchTests(unittest.TestCase):
    def test_wrong_runtime_revision_is_rejected_without_partial_output(self):
        self.assertIsNotNone(importlib.util.find_spec('gx10_integration_patch'),'scoped runtime integration patch missing')
        from gx10_integration_patch import patch_chat,patch_worker
        for patch in (patch_chat,patch_worker):
            with self.assertRaises(ValueError):patch('unrelated runtime')
if __name__=='__main__':unittest.main()

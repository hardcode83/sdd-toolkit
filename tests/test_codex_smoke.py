from __future__ import annotations

import os
import subprocess
import unittest


class NativeCodexSmokeTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("SDD_NATIVE_CODEX_SMOKE_CMD"), "opt-in native Codex smoke")
    def test_native_smoke_is_explicitly_opt_in(self):
        # The configured host command owns real spawn/wait/sandbox assertions;
        # CI remains deterministic and never requires paid model execution.
        completed = subprocess.run(os.environ["SDD_NATIVE_CODEX_SMOKE_CMD"], shell=True, check=False)
        self.assertEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main()

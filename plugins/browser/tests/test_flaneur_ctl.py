"""flaneur-ctl against a fake flaneur: start, reuse, endpoint, stop, failures, the VPN login."""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

CTL = Path(__file__).resolve().parent.parent / "bin" / "flaneur-ctl"

FAKE = textwrap.dedent("""\
    #!/bin/sh
    # Fake flaneur: records its arguments and VPN user, prints an endpoint, then runs until killed.
    echo "$@" >> "$FAKE_LOG"
    echo "user=${FLANEUR_VPN_USER:-}" >> "$FAKE_LOG"
    [ -n "$FAKE_FAIL" ] && { echo "boom: $FAKE_FAIL" >&2; exit 7; }
    echo "ws://127.0.0.1:1/secret-$$"
    exec sleep 60
""")


class FlaneurCtlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        fake = self.tmp / "fake-flaneur"
        fake.write_text(FAKE)
        fake.chmod(0o755)
        self.log = self.tmp / "calls"
        self.env = {
            **{k: v for k, v in os.environ.items() if not k.startswith("FLANEUR_VPN_")},
            "FLANEUR_CTL_DIR": str(self.tmp / "state"),
            "FLANEUR_CTL_COMMAND": str(fake),
            "FAKE_LOG": str(self.log),
        }

    def tearDown(self):
        self.ctl("stop")
        self.ctl("stop", "--vpn", "US Texas")

    def ctl(self, *args, **env):
        return subprocess.run([sys.executable, str(CTL), *args], capture_output=True, text=True,
                              env={**self.env, **env}, timeout=30)

    def test_start_reuses_the_running_browser_and_never_prints_the_endpoint(self):
        first = self.ctl("start")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertNotIn("ws://", first.stdout)
        second = self.ctl("start")
        self.assertIn("already running", second.stdout)
        self.assertEqual(self.log.read_text().count("user="), 1)
        self.assertTrue(self.ctl("endpoint").stdout.startswith("ws://127.0.0.1:1/secret-"))

    def test_stop_ends_the_browser(self):
        self.ctl("start")
        self.assertIn("stopped", self.ctl("stop").stdout)
        gone = self.ctl("endpoint")
        self.assertEqual(gone.returncode, 1)
        self.assertIn("not running", gone.stderr)

    def test_a_failed_start_shows_the_log(self):
        result = self.ctl("start", FAKE_FAIL="no chrome")
        self.assertEqual(result.returncode, 1)
        self.assertIn("boom: no chrome", result.stderr)
        self.assertEqual(self.ctl("endpoint").returncode, 1)

    def test_vpn_without_a_login_refuses(self):
        result = self.ctl("start", "--vpn", "US Texas", "--vpn-provider", "pia")
        self.assertEqual(result.returncode, 3)
        self.assertFalse(self.log.exists())

    def test_vpn_login_comes_from_the_environment_and_the_region_gets_its_own_browser(self):
        self.assertEqual(self.ctl("start").returncode, 0)
        vpn = self.ctl("start", "--vpn", "US Texas", "--vpn-provider", "pia",
                       FLANEUR_VPN_USER="alice", FLANEUR_VPN_PASSWORD="pw")
        self.assertEqual(vpn.returncode, 0, vpn.stderr)
        calls = self.log.read_text()
        self.assertIn("--vpn US Texas --vpn-provider pia --user-data-dir", calls)
        self.assertIn("vpn-us-texas/profile", calls)
        self.assertIn("user=alice", calls)
        self.assertNotEqual(self.ctl("endpoint").stdout, self.ctl("endpoint", "--vpn", "US Texas").stdout)


if __name__ == "__main__":
    unittest.main()

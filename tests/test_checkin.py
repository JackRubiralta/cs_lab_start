"""Check-in driver against the stand-in TUI, every screen and failure. Run: python3 -m unittest discover tests"""
import io
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import lab_start  # noqa: E402

FAKE = os.path.join(HERE, "fake_lab_checkin.py")


class CheckIn(unittest.TestCase):
    def run_mode(self, mode, **kw):
        log = tempfile.NamedTemporaryFile(delete=False).name
        os.environ.update(FAKE_CHECKIN_MODE=mode, FAKE_CHECKIN_LOG=log, TERM="xterm-256color")
        os.environ.pop("FAKE_OPENS_ON_RETRY", None)
        os.environ.pop("FAKE_FAIL_THEN_OK", None)
        os.environ.update(kw.pop("env", {}))
        lab_start.LAB_CHECKIN = FAKE
        out = io.StringIO()
        start = time.time()
        with redirect_stdout(out):
            ok = lab_start.lab_checkin(**kw)
        with open(log) as f:
            keys = f.read()
        os.unlink(log)
        return ok, out.getvalue(), keys, time.time() - start

    def test_one_session(self):
        ok, out, keys, _ = self.run_mode("one")
        self.assertTrue(ok)
        self.assertIn("CHECKED IN", out)
        self.assertEqual(keys.splitlines(), ["key 'y' on confirm", "key 'q' on done", "exit from done"])
        self.assertLess(_, 15)

    def test_session_list(self):
        ok, out, keys, _ = self.run_mode("list")
        self.assertTrue(ok)
        self.assertTrue(keys.startswith("key '\\r' on list"))

    def test_slow_kerberos(self):
        ok, _, _, _ = self.run_mode("slow")
        self.assertTrue(ok)

    def test_nothing_open(self):
        ok, out, keys, _ = self.run_mode("none")
        self.assertFalse(ok)
        self.assertIn("no attendance session open", out)
        self.assertIn("exit from none", keys)

    def test_wait_until_open(self):
        ok, out, keys, _ = self.run_mode("none", wait_minutes=2, env={"FAKE_OPENS_ON_RETRY": "1"})
        self.assertTrue(ok)
        self.assertIn("key 'r' on none", keys)

    def test_server_failure(self):
        ok, out, keys, _ = self.run_mode("fail")
        self.assertFalse(ok)
        self.assertIn("the check-in service is temporarily unavailable", out)
        self.assertIn("exit from fail", keys)

    def test_crash_shows_its_error(self):
        ok, out, _, secs = self.run_mode("crash")
        self.assertFalse(ok)
        self.assertIn("could not determine the current systemd-logind session", out)
        self.assertLess(secs, 10)

    def test_hang_times_out_and_is_killed(self):
        ok, out, _, secs = self.run_mode("hang", timeout=8)
        self.assertFalse(ok)
        self.assertLess(secs, 80)          # timeout + the 60 s hard cap for a spinning screen
        self.assertIn("by hand", out)      # not a terminal here, so it says what to do

    def test_keys_lost_are_pressed_again(self):
        ok, out, keys, _ = self.run_mode("deaf")
        self.assertTrue(ok)
        self.assertEqual(keys.count("key 'y' on confirm"), 3)

    def test_failure_retried_then_ok(self):
        ok, out, keys, _ = self.run_mode("fail", env={"FAKE_FAIL_THEN_OK": "1"})
        self.assertTrue(ok)
        self.assertIn("key 'r' on fail", keys)

    def test_unknown_screen_hands_over(self):
        ok, out, keys, secs = self.run_mode("unknown")
        self.assertFalse(ok)
        self.assertIn("couldn't finish it by itself", out)
        self.assertLess(secs, 30)

    def test_summary_names_the_class(self):
        ok, out, _, _ = self.run_mode("one")
        self.assertIn("CHECKED IN – CS1002, 2m 12s after start", out)

    def test_log_is_written(self):
        ok, out, _, _ = self.run_mode("one")
        self.assertIn("screen log: logs/checkin-", out)


class RealScreens(unittest.TestCase):
    """Bytes recorded from the real /cs/studres/ct/lab-checkin binary (5 Nov 2026)."""

    def test_real_failed_screen_is_read(self):
        with open(os.path.join(HERE, "real_checkin_failed.out"), "rb") as f:
            flat = lab_start.screen_text(f.read())
        self.assertEqual(lab_start.checkin_state(flat), "failed")
        self.assertIn("native Kerberos authentication failed", flat)

    def test_raw_stream_never_holds_whole_words(self):
        """Why the old byte-matching driver got stuck: redraws carry only changed cells."""
        with open(os.path.join(HERE, "real_checkin_failed.out"), "rb") as f:
            raw = f.read()
        self.assertIn(b"\x1b[?1003h", raw)       # mouse capture on, like the real one
        self.assertIn("CHECK-IN FAILED", lab_start.screen_text(raw))

    def test_missing_program(self):
        lab_start.LAB_CHECKIN = "/nonexistent/lab-checkin"
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertFalse(lab_start.lab_checkin())
        self.assertIn("not found", out.getvalue())


if __name__ == "__main__":
    unittest.main()

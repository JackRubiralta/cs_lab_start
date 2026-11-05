"""Sign-in loop against a fake Marionette server: it must always give up on time.
Run: python3 -m unittest discover tests"""
import io
import json
import os
import socket
import sys
import threading
import time
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lab_start  # noqa: E402
from marionette import Marionette  # noqa: E402


class FakeFirefox(threading.Thread):
    """Speaks just enough Marionette. reply(name, params) -> result, or None = never answer."""

    def __init__(self, reply):
        super().__init__(daemon=True)
        self.reply = reply
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.start()

    def run(self):
        conn, _ = self.srv.accept()
        send = lambda obj: conn.sendall(b"%d:%s" % (len(json.dumps(obj)), json.dumps(obj).encode()))
        send({"applicationType": "gecko", "marionetteProtocol": 3})
        buf = b""
        while True:
            try:
                chunk = conn.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b":" in buf:
                n, _, rest = buf.partition(b":")
                if len(rest) < int(n):
                    break
                msg, buf = json.loads(rest[:int(n)]), rest[int(n):]
                result = self.reply(msg[2], msg[3])
                if result is not None:
                    send([1, msg[1], None, {"value": result}])


def page(kind, url="https://login.microsoftonline.com/x", **extra):
    return dict({"url": url, "ready": "complete", "kind": kind, "page": "Sign in"}, **extra)


class SignIn(unittest.TestCase):
    def setUp(self):
        lab_start.LOGIN_TIMEOUT = 4

    def drive(self, reply, call_timeout=1):
        fake = FakeFirefox(reply)
        m = Marionette(fake.port, call_timeout=call_timeout).connect(5)
        out = io.StringIO()
        start = time.time()
        with redirect_stdout(out):
            try:
                ok = lab_start.sign_in(m, lab_start.STUDRES_URL, "a@b", "pw", {})
                err = None
            except lab_start.LoginFailed as e:
                ok, err = False, str(e)
        m.close()
        return ok, err, out.getvalue(), time.time() - start

    def test_crashed_tab_is_reloaded(self):
        calls = {"js": 0, "nav": []}

        def reply(name, p):
            if name == "WebDriver:Navigate":
                calls["nav"].append(p.get("url"))
                return None if False else {}
            if name == "WebDriver:ExecuteScript":
                calls["js"] += 1
                if calls["js"] <= 2:
                    return {"url": "about:tabcrashed?e=tabcrashed", "ready": "complete", "kind": "wait",
                            "page": "Tab Crashed | Gah. Your tab just crashed."}
                return page("wait", url=lab_start.STUDRES_URL, page="Index of /CS1002 | Index of /CS1002")
            return {}
        ok, err, out, _ = self.drive(reply)
        self.assertTrue(ok, err)
        self.assertIn("crashed – loading it again (1/3)", out)
        self.assertEqual(calls["nav"][:1], [lab_start.STUDRES_URL])

    def test_tab_that_keeps_crashing_gives_up(self):
        def reply(name, p):
            if name == "WebDriver:ExecuteScript":
                return {"url": "about:tabcrashed", "ready": "complete", "kind": "wait", "page": "Tab Crashed"}
            return {}
        ok, err, out, secs = self.drive(reply)
        self.assertFalse(ok)
        self.assertIn("keeps crashing", err)
        self.assertLess(secs, 10)

    def test_firefox_never_answers(self):
        ok, err, _, secs = self.drive(lambda name, p: None)
        self.assertFalse(ok)
        self.assertIn("timed out", err)
        self.assertLess(secs, 10)

    def test_ignored_authenticator_request(self):
        ok, err, out, secs = self.drive(lambda name, p: page("number", number="64"))
        self.assertIn("timed out", err)
        self.assertEqual(out.count("Type  64"), 1)   # shown once, not every poll
        self.assertLess(secs, 10)

    def test_denied_request_stops_at_once(self):
        ok, err, _, secs = self.drive(
            lambda name, p: page("error", error="Authenticator: We didn't hear from you"))
        self.assertIn("didn't hear", err)
        self.assertLess(secs, 3)

    def test_slow_but_working(self):
        calls = {"n": 0}

        def reply(name, p):
            calls["n"] += 1
            if calls["n"] % 3 == 0:
                time.sleep(1.5)   # every third answer is late
            return {"url": "https://studres.cs.st-andrews.ac.uk/CS1002/", "ready": "complete",
                    "kind": "wait", "page": "Index of /CS1002"}
        ok, err, _, _ = self.drive(reply)
        self.assertTrue(ok, err)

    def test_signed_in_only_when_page_says_so(self):
        # Outlook's address before the redirect must not count as signed in.
        ok, err, _, _ = self.drive(lambda name, p: {
            "url": "https://studres.cs.st-andrews.ac.uk/CS1002/", "ready": "complete",
            "kind": "wait", "page": "Loading…"})
        self.assertFalse(ok)


class CloseTerminal(unittest.TestCase):
    def test_left_alone_without_a_terminal(self):
        # The unit tests run with stdin not a tty, or under a non-shell parent.
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertFalse(lab_start.close_my_terminal())


if __name__ == "__main__":
    unittest.main()

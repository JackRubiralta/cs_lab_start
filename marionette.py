"""Tiny Marionette client: drives Firefox through its built-in remote port.

Standard library only (the lab PCs have no pip packages and no sudo), and
works on Python 3.6+. Marionette frames every message as "<length>:<json>";
a command is [0, id, name, params] and the reply is [1, id, error, result].
"""

import json
import socket
import time

ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"
WINDOW_KEY = "window-fcc6-11e5-b4f8-330a88ab9d7f"


class MarionetteError(Exception):
    def __init__(self, error, message=""):
        super().__init__("%s: %s" % (error, message))
        self.error = error


class Marionette:
    def __init__(self, port=2828, host="127.0.0.1"):
        self.host, self.port = host, port
        self.sock = None
        self.msg_id = 0
        self.buf = b""

    # ---- connection -----------------------------------------------------
    def connect(self, timeout=60):
        """Connect, retrying until Firefox has opened its Marionette port."""
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                self.sock = socket.create_connection((self.host, self.port), timeout=5)
                self.sock.settimeout(120)
                self._read()  # greeting: {"applicationType": "gecko", ...}
                return self
            except (OSError, ValueError) as e:
                last = e
                if self.sock:
                    self.sock.close()
                    self.sock = None
                time.sleep(0.5)
        raise MarionetteError("no connection", "port %d: %s" % (self.port, last))

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _read(self):
        while b":" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise OSError("Marionette closed the connection")
            self.buf += chunk
        length, _, rest = self.buf.partition(b":")
        length = int(length)
        while len(rest) < length:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise OSError("Marionette closed the connection")
            rest += chunk
        self.buf = rest[length:]
        return json.loads(rest[:length].decode("utf-8"))

    def send(self, name, params=None):
        self.msg_id += 1
        data = json.dumps([0, self.msg_id, name, params or {}]).encode("utf-8")
        self.sock.sendall(str(len(data)).encode() + b":" + data)
        while True:
            msg = self._read()
            if msg[0] == 1 and msg[1] == self.msg_id:
                break
        error, result = msg[2], msg[3]
        if error:
            raise MarionetteError(error.get("error"), error.get("message", ""))
        if isinstance(result, dict) and set(result) == {"value"}:
            return result["value"]
        return result

    # ---- session and windows --------------------------------------------
    def new_session(self):
        return self.send("WebDriver:NewSession", {"capabilities": {"alwaysMatch": {
            "pageLoadStrategy": "none",   # never block on slow pages; we poll instead
            "unhandledPromptBehavior": "ignore",
        }}})

    def delete_session(self):
        try:
            self.send("WebDriver:DeleteSession")
        except (MarionetteError, OSError):
            pass

    def handles(self):
        return self.send("WebDriver:GetWindowHandles")

    def current_handle(self):
        return self.send("WebDriver:GetWindowHandle")

    def switch_to(self, handle):
        self.send("WebDriver:SwitchToWindow", {"handle": handle, "focus": True})

    def new_tab(self):
        return self.send("WebDriver:NewWindow", {"type": "tab", "focus": False})["handle"]

    def close_tab(self):
        return self.send("WebDriver:CloseWindow")

    def navigate(self, url):
        self.send("WebDriver:Navigate", {"url": url})

    def url(self):
        return self.send("WebDriver:GetCurrentURL")

    def js(self, script, *args):
        return self.send("WebDriver:ExecuteScript",
                         {"script": script, "args": list(args), "sandbox": None})

    # ---- elements --------------------------------------------------------
    def find(self, css):
        """First element matching the CSS selector, or None."""
        found = self.send("WebDriver:FindElements", {"using": "css selector", "value": css})
        return found[0] if found else None

    def send_keys(self, element, text):
        self.send("WebDriver:ElementSendKeys", {"id": element[ELEMENT_KEY], "text": text})

    def clear(self, element):
        self.send("WebDriver:ElementClear", {"id": element[ELEMENT_KEY]})

    def click(self, element):
        self.send("WebDriver:ElementClick", {"id": element[ELEMENT_KEY]})

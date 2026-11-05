#!/usr/bin/env python3
"""Stand-in for /cs/studres/ct/lab-checkin, for testing the key driver off-site.

Behaves like the real one (a Rust ratatui TUI, checked against the real binary
on 5 Nov 2026): alternate screen + mouse capture, a header box, a centred
panel per state, a spinner that animates while it works, a clock that ticks,
and - the important part - it redraws ONLY the cells that changed, so the
output stream never holds whole words once the screen is up. Screen texts are
the binary's own strings.

Logs every key it receives to $FAKE_CHECKIN_LOG.
Mode from $FAKE_CHECKIN_MODE: one | list | none | fail | slow | hang | crash | deaf | unknown
  deaf     ignores the first two keys on the confirm screen (keys lost)
  unknown  shows a screen with no known title and never moves on
"""
import os
import select
import sys
import termios
import time
import tty

MODE = os.environ.get("FAKE_CHECKIN_MODE", "one")
LOG = os.environ.get("FAKE_CHECKIN_LOG", "/tmp/fake-checkin.log")
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def log(msg):
    with open(LOG, "a") as f:
        f.write(msg + "\n")


class Term:
    """Cell buffer + diff flush, the way ratatui's terminal backend does it."""

    def __init__(self):
        import fcntl, struct
        try:
            self.rows, self.cols = struct.unpack("HHHH", fcntl.ioctl(1, termios.TIOCGWINSZ, b"\0" * 8))[:2]
        except OSError:
            self.rows, self.cols = 40, 120
        self.rows, self.cols = self.rows or 40, self.cols or 120
        self.prev = None
        self.buf = None

    def begin(self):
        self.buf = [[" "] * self.cols for _ in range(self.rows)]

    def put(self, r, c, text):
        for i, ch in enumerate(text):
            if 0 <= r < self.rows and 0 <= c + i < self.cols:
                self.buf[r][c + i] = ch

    def box(self, r, c, h, w, title=""):
        self.put(r, c, "╭" + "─" * (w - 2) + "╮")
        for i in range(1, h - 1):
            self.put(r + i, c, "│" + " " * (w - 2) + "│")
        self.put(r + h - 1, c, "╰" + "─" * (w - 2) + "╯")
        if title:
            self.put(r, c + 1, " %s " % title)

    def center(self, r, text):
        self.put(r, max(0, (self.cols - len(text)) // 2), text)

    def flush(self):
        out = []
        if self.prev is None:
            out.append("\x1b[?1049h\x1b[?2004h\x1b[?1000h\x1b[?1002h\x1b[?1003h\x1b[?1015h\x1b[?1006h\x1b[?25l")
            self.prev = [[None] * self.cols for _ in range(self.rows)]
        colour = 0
        for r in range(self.rows):
            c = 0
            while c < self.cols:
                if self.buf[r][c] == self.prev[r][c]:
                    c += 1
                    continue
                out.append("\x1b[%d;%dH" % (r + 1, c + 1))
                while c < self.cols and self.buf[r][c] != self.prev[r][c]:
                    colour = (colour + 1) % 3          # style changes inside words, like the real one
                    out.append("\x1b[38;2;%d;211;238m%s" % (34 + colour, self.buf[r][c]))
                    self.prev[r][c] = self.buf[r][c]
                    c += 1
        sys.stdout.write("".join(out))
        sys.stdout.flush()


def frame(t, title, lines, keys, spinning=False):
    t.begin()
    t.box(0, 0, 3, t.cols)
    t.put(1, 2, "CSORE   CHECK-IN")
    t.put(1, t.cols - 45, "https://csore.cs.st-andrews.ac.uk/api  |  Kerberos")
    top = 9
    t.box(top, 11, 14, t.cols - 22, title)
    for i, line in enumerate(lines):
        if spinning and i == 0:
            line = SPIN[int(time.time() * 12) % len(SPIN)] + "  " + line
        t.center(top + 2 + i, line)
    t.center(top + 11, keys)
    t.center(t.rows - 2, "Machine  pc7-042-l   " + time.strftime("%H:%M:%S UTC", time.gmtime()))
    t.center(t.rows - 1, keys)
    t.flush()


def wait_key(t, draw, seconds=None):
    """Redraw (spinner/clock) every 80 ms until a key or `seconds` pass."""
    end = time.time() + seconds if seconds else None
    while True:
        draw()
        r, _, _ = select.select([0], [], [], 0.08)
        if r:
            return os.read(0, 16)
        if end and time.time() > end:
            return None


def main():
    t = Term()
    auth = lambda: frame(t, "AUTHENTICATING", ["Verifying your native Kerberos credential",
                                               "Using the credential cache of this login session"],
                         "Ctrl-C quits", spinning=True)
    wait_key(t, auth, 6 if MODE == "slow" else 1.2)
    if MODE == "hang":
        while True:
            wait_key(t, auth, 60)
    screen = {"none": "none", "fail": "fail", "list": "list", "unknown": "unknown"}.get(MODE, "confirm")
    ignored = 0
    while True:
        if screen == "list":
            d = lambda: frame(t, "ELIGIBLE SESSIONS", [
                "MODULE   ACADEMIC YEAR   GROUP               START   END",
                "CS1002   2026/7          Exercise class 02   11:05   11:55",
                "CS1002   2026/7          Tutorial 19         11:05   11:55",
                "", "Selection expires  09:41"], "↑↓ select   Enter review   Ctrl-C quits")
        elif screen == "confirm":
            d = lambda: frame(t, "CONFIRM CHECK-IN", [
                " SELECTED SESSION ", "MODULE  CS1002     GROUP  Exercise class 02",
                "Check in as jrk25?"], "Enter / y check in    Esc / n go back")
        elif screen == "done":
            d = lambda: frame(t, "CHECK-IN RECORDED", [
                "CS1002  Exercise class 02", "checked in 11:07:12 UTC  2m 12s after start"],
                "Enter / q close")
        elif screen == "none":
            d = lambda: frame(t, "NO ELIGIBLE SESSION", [
                "No attendance session is currently open for jrk25.",
                "Check-in opens 10 minutes before a session starts",
                "and closes when that session ends."], "r try again    q quit")
        elif screen == "fail":
            d = lambda: frame(t, "CHECK-IN FAILED", [
                "the check-in service is temporarily unavailable", "",
                "Retrying performs a fresh Kerberos authentication and session search."],
                "r retry    q quit")
        else:
            d = lambda: frame(t, "PLEASE WAIT", ["Something new the driver doesn't know"], "Ctrl-C quits",
                              spinning=True)
        k = wait_key(t, d)
        ch = k.decode("latin-1")
        log("key %r on %s" % (ch if len(ch) == 1 else ch, screen))
        if ch == "\x03":
            return
        if screen == "confirm" and MODE == "deaf" and ignored < 2:
            ignored += 1
            continue
        if screen == "none" and ch == "r":
            if os.environ.get("FAKE_OPENS_ON_RETRY"):
                screen = "confirm"
            else:
                wait_key(t, auth, 0.8)
        elif screen == "fail" and ch == "r":
            wait_key(t, auth, 0.8)
            if os.environ.get("FAKE_FAIL_THEN_OK"):
                screen = "confirm"
        elif screen == "list" and ch in ("\r", "\n"):
            screen = "confirm"
        elif screen == "confirm" and ch in ("\r", "\n", "y"):
            rec = lambda: frame(t, "RECORDING CHECK-IN", ["Submitting securely..."], "", spinning=True)
            wait_key(t, rec, 1.0)
            screen = "done"
        elif screen == "confirm" and ch in ("\x1b", "n"):
            screen = "list"
        elif screen == "done" and ch in ("\r", "\n", "q"):
            log("exit from done")
            return
        elif screen in ("none", "fail") and ch == "q":
            log("exit from %s" % screen)
            return


if MODE == "crash":   # what the real one prints off a lab PC
    print("Error: could not read workstation metadata\n\nCaused by:\n"
          "    could not determine the current systemd-logind session")
    raise SystemExit(1)
old = termios.tcgetattr(0) if os.isatty(0) else None
try:
    if old:
        tty.setraw(0)
    main()
finally:
    sys.stdout.write("\x1b[?1049l\x1b[?25h")
    sys.stdout.flush()
    if old:
        termios.tcsetattr(0, termios.TCSADRAIN, old)

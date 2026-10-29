#!/usr/bin/env python3
"""Stand-in for /cs/studres/ct/lab-checkin, for testing the key driver off-site.

Draws the same screens as the real TUI (text taken from the binary) with
curses on the alternate screen, and logs every key it receives to
$FAKE_CHECKIN_LOG. Mode from $FAKE_CHECKIN_MODE: one | list | none | fail.
"""
import curses
import os
import time

MODE = os.environ.get("FAKE_CHECKIN_MODE", "one")
LOG = os.environ.get("FAKE_CHECKIN_LOG", "/tmp/fake-checkin.log")


def log(msg):
    with open(LOG, "a") as f:
        f.write(msg + "\n")


def draw(scr, title, lines, keys):
    scr.erase()
    scr.border()
    scr.addstr(0, 2, " CSORE / CHECK-IN ", curses.A_BOLD)
    scr.addstr(2, 3, " %s " % title, curses.A_REVERSE)
    for i, line in enumerate(lines):
        scr.addstr(4 + i, 3, line)
    scr.addstr(curses.LINES - 2, 3, keys, curses.A_DIM)
    scr.refresh()


def main(scr):
    curses.curs_set(0)
    draw(scr, "AUTHENTICATING", ["Verifying your native Kerberos credential",
                                 "Using the credential cache of this login session"], "Ctrl-C quits")
    time.sleep(1)
    if MODE == "none":
        screen = "none"
    elif MODE == "fail":
        screen = "fail"
    elif MODE == "list":
        screen = "list"
    else:
        screen = "confirm"
    while True:
        if screen == "list":
            draw(scr, "ELIGIBLE SESSIONS", ["> CS1002  2026/7  Exercise class 02  11:05  11:55",
                                            "  CS1002  2026/7  Tutorial 19        11:05  11:55"],
                 "Enter select   Ctrl-C quits")
        elif screen == "confirm":
            draw(scr, "CONFIRM CHECK-IN", ["MODULE CS1002   GROUP Exercise class 02",
                                           "Check in as jrk25?"],
                 "Enter / y check in    Esc / n go back")
        elif screen == "done":
            draw(scr, "CHECK-IN RECORDED", ["CS1002 Exercise class 02",
                                            "11:07:12 UTC  2m 12s after start"], "Enter / q close")
        elif screen == "none":
            draw(scr, "NO ELIGIBLE SESSION", ["No attendance session is currently open for jrk25.",
                                              "Check-in opens 10 minutes before a session starts"],
                 "r try again   q quit")
        elif screen == "fail":
            draw(scr, "CHECK-IN FAILED", ["the check-in service is temporarily unavailable",
                                          "Retrying performs a fresh Kerberos authentication"],
                 "r retry   q quit")
        k = scr.getch()
        log("key %r on %s" % (chr(k) if 0 <= k < 256 else k, screen))
        if screen == "none" and k == ord("r") and os.environ.get("FAKE_OPENS_ON_RETRY"):
            screen = "confirm"
        elif screen == "list" and k in (10, 13):
            screen = "confirm"
        elif screen == "confirm" and k in (10, 13, ord("y")):
            draw(scr, "RECORDING CHECK-IN", ["Submitting securely..."], "")
            time.sleep(1)
            screen = "done"
        elif screen == "confirm" and k in (27, ord("n")):
            screen = "list"
        elif screen in ("done", "none", "fail") and k in (10, 13, ord("q")) and not (
                screen != "done" and k in (10, 13)):
            log("exit from %s" % screen)
            return


curses.wrapper(main)

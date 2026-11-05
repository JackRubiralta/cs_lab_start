#!/usr/bin/env python3
"""cs_lab_start: set up a St Andrews CS lab PC the way Jack likes it, in one go.

  1. desktop    taskbar always shown with Firefox/VS Code/Terminal/Files pinned,
                mouse at half speed
  2. checkin    the exercise-class check-in (/cs/studres/ct/lab-checkin):
                selects the open session, presses y, then q; if it can't, it
                opens the check-in in this terminal for you
  3. exercises  copy every new CS1002 exercise week from /cs/studres into
                ~/Documents/CS1002/Exercises (never overwrites a file)
  4. vscode     VS Code on the newest week, main .java file open, terminal
                already in the folder stacscheck runs from
  5. browser    Firefox with StudRes CS1002, Outlook and MMS CS1002 open and
                signed in (email + password from .env; you approve the
                Authenticator number on your phone)

Usage:  ./start                    everything
        ./start checkin            just the check-in (several parts allowed)
        ./start browser --no-login          open the tabs, don't sign in
        ./start exercises --dry-run         show what would be copied

Standard library only; no sudo, no pip. Lab PCs wipe the local home folder
on restart, so this lives in ~/Documents and re-applies itself every login.
"""

import argparse
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from marionette import Marionette, MarionetteError, ELEMENT_KEY  # noqa: E402

# ---------------------------------------------------------------- settings
STUDRES_URL = "https://studres.cs.st-andrews.ac.uk/CS1002/"
OUTLOOK_URL = "https://outlook.office.com/mail/"
MMS_URL = "https://mms.st-andrews.ac.uk/mms/module/2026_7/S1/CS1002/"

STUDRES_EXERCISES = os.environ.get("CS_LAB_STUDRES", "/cs/studres/CS1002/Exercises")
MY_EXERCISES = os.environ.get(
    "CS_LAB_EXERCISES", os.path.expanduser("~/Documents/CS1002/Exercises"))

MOUSE_SPEED = "-0.5"   # GNOME scale -1..1, 0 = default; -0.5 = half way to slowest
# Pinned first, in this order; anything already pinned stays after them.
# Each entry lists alternatives: the terminal is Ptyxis on AlmaLinux 10.
PINNED_APPS = [["firefox.desktop"], ["code.desktop"],
               ["org.gnome.Terminal.desktop", "org.gnome.Ptyxis.desktop", "org.gnome.Console.desktop"],
               ["org.gnome.Nautilus.desktop"]]
MARIONETTE_PORT = 2828
LOGIN_TIMEOUT = 300    # seconds per site, long enough to find your phone

ENV_FILE = os.path.join(HERE, ".env")
ENV_TEMPLATE = """# Your St Andrews sign-in, used only to type into the Microsoft login page.
# Keep this file private: ./start keeps it readable by you alone (chmod 600).
EMAIL=jrk25@st-andrews.ac.uk
PASSWORD=
"""

# How to tell each site is really open and signed in: (hosts, regex on title + start of page).
# The address alone isn't enough: right after opening, Outlook's tab still shows
# outlook.office.com for a moment before it redirects to the login page.
SIGNED_IN = {
    STUDRES_URL: (("studres.cs.st-andrews.ac.uk",), r"Index of /CS1002"),
    OUTLOOK_URL: (("outlook.office.com", "outlook.cloud.microsoft", "outlook.office365.com"),
                  r"Mail - .+ - Outlook|Inbox - .+ - Outlook"),
    MMS_URL: (("mms.st-andrews.ac.uk",), r"Sign out"),
}

LOGIN_HOSTS = ("login.microsoftonline.com", "login.microsoft.com", "login.live.com",
               "login.st-andrews.ac.uk", "login.windows.net", "device.login.microsoftonline.com")


def say(msg=""):
    """Print, never crash: odd file names (bad UTF-8) or a closed terminal can't stop the run."""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(msg.encode(enc, "replace").decode(enc, "replace"), flush=True)
    except (OSError, ValueError):
        pass


def head(title):
    say("\n== " + title)


def run(cmd, **kw):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, **kw)


# ================================================================== desktop
def gsettings(*args, schemadir=None):
    cmd = ["gsettings"] + (["--schemadir", schemadir] if schemadir else []) + list(args)
    return run(cmd)


def gs_set(schema, key, value, schemadir=None):
    r = gsettings("set", schema, key, value, schemadir=schemadir)
    return r.returncode == 0


def extension_dirs():
    """uuid -> install dir for every installed GNOME Shell extension."""
    found = {}
    data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
    for base in [os.path.expanduser("~/.local/share")] + data_dirs:
        d = os.path.join(base, "gnome-shell", "extensions")
        if os.path.isdir(d):
            for uuid in os.listdir(d):
                found.setdefault(uuid, os.path.join(d, uuid))
    return found


def enable_extension(uuid):
    if run(["gnome-extensions", "enable", uuid]).returncode == 0:
        return True
    # Older shells: edit the list directly.
    cur = gsettings("get", "org.gnome.shell", "enabled-extensions").stdout.strip()
    items = re.findall(r"'([^']+)'", cur)
    if uuid not in items:
        items.append(uuid)
    return gs_set("org.gnome.shell", "enabled-extensions",
                  "[" + ", ".join("'%s'" % i for i in items) + "]")


def schemadir_for(ext_dir):
    d = os.path.join(ext_dir, "schemas")
    return d if os.path.isfile(os.path.join(d, "gschemas.compiled")) else None


def setup_desktop():
    head("Desktop")
    if not shutil.which("gsettings"):
        say("  gsettings not found: not a GNOME desktop, skipped")
        return False
    ok = True

    if gs_set("org.gnome.desktop.peripherals.mouse", "speed", MOUSE_SPEED):
        say("  mouse speed set to half (%s)" % MOUSE_SPEED)
    else:
        say("  could not set the mouse speed")
        ok = False

    gs_set("org.gnome.shell", "disable-user-extensions", "false")
    exts = extension_dirs()
    taskbar = None
    for uuid, ext_dir in exts.items():
        if uuid.startswith("dash-to-panel@"):
            enable_extension(uuid)
            sd = schemadir_for(ext_dir)
            gs_set("org.gnome.shell.extensions.dash-to-panel", "intellihide", "false", sd)
            taskbar = "Dash to Panel, auto-hide off"
            break
    if not taskbar:
        for uuid, ext_dir in exts.items():
            if uuid.startswith(("dash-to-dock@", "ubuntu-dock@")):
                enable_extension(uuid)
                sd = schemadir_for(ext_dir)
                schema = "org.gnome.shell.extensions.dash-to-dock"
                gs_set(schema, "dock-fixed", "true", sd)
                gs_set(schema, "autohide", "false", sd)
                gs_set(schema, "intellihide", "false", sd)
                taskbar = "Dash to Dock, pinned (always shown)"
                break
    if not taskbar and "window-list@gnome-shell-extensions.gcampax.github.com" in exts:
        enable_extension("window-list@gnome-shell-extensions.gcampax.github.com")
        gs_set("org.gnome.shell.extensions.window-list", "show-on-all-monitors", "true")
        taskbar = "bottom window list, always shown"
    if taskbar:
        say("  taskbar: " + taskbar)
    else:
        say("  no taskbar extension installed on this PC (have: %s)" % ", ".join(sorted(exts)))
        ok = False

    wanted = [next((a for a in alts if desktop_file_exists(a)), None) for alts in PINNED_APPS]
    wanted = [a for a in wanted if a]
    current = re.findall(r"'([^']+)'", gsettings("get", "org.gnome.shell", "favorite-apps").stdout)
    apps = wanted + [a for a in current if a not in wanted]
    if apps and gs_set("org.gnome.shell", "favorite-apps",
                       "[" + ", ".join("'%s'" % a for a in apps) + "]"):
        say("  pinned first: " + ", ".join(a.replace(".desktop", "") for a in wanted))
    return ok


def desktop_file_exists(name):
    dirs = [os.path.expanduser("~/.local/share")] + \
        os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
    return any(os.path.isfile(os.path.join(d, "applications", name)) for d in dirs)


# ================================================================== checkin
LAB_CHECKIN = os.environ.get("CS_LAB_CHECKIN", "/cs/studres/ct/lab-checkin")
LOG_DIR = os.path.join(HERE, "logs")
CHECKIN_ROWS, CHECKIN_COLS = 40, 120

# Screen titles of the real check-in (a ratatui TUI; text from the binary), most specific first.
#   state        text on screen                                  key
CHECKIN_SCREENS = [
    ("recorded",  r"CHECK-IN RECORDED",                           b"q"),
    ("failed",    r"CHECK-IN FAILED",                             None),
    ("none",      r"NO ELIGIBLE SESSION|No attendance session is currently open", None),
    ("recording", r"RECORDING CHECK-IN|Submitting securely",      None),
    ("confirm",   r"CONFIRM CHECK-IN|Check in as \S+",            b"y"),
    ("list",      r"ELIGIBLE SESSIONS|SELECTED SESSION",          b"\r"),
    ("auth",      r"AUTHENTICATING|Verifying your native Kerberos", None),
]
# Failures worth one more go (r = "a fresh Kerberos authentication and session search")
RETRYABLE = r"temporarily unavailable|timed out|could not connect|grant has expired|no longer available"


def screen_text(raw):
    """Terminal bytes -> what the screen shows, as one line (for messages and tests)."""
    from vtscreen import Screen
    s = Screen(CHECKIN_ROWS, CHECKIN_COLS)
    s.feed(raw if isinstance(raw, bytes) else raw.encode())
    return s.flat()


def checkin_state(flat):
    for state, pattern, _ in CHECKIN_SCREENS:
        if re.search(pattern, flat):
            return state
    return None


def _open_log():
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        old = sorted(f for f in os.listdir(LOG_DIR) if f.startswith("checkin-"))
        for f in old[:-30]:          # keep the last 30 runs
            os.unlink(os.path.join(LOG_DIR, f))
        path = os.path.join(LOG_DIR, time.strftime("checkin-%Y%m%d-%H%M%S.out"))
        return path, open(path, "wb")
    except OSError:
        return None, None


def _spawn(rows, cols):
    import pty, fcntl, termios, struct   # POSIX only
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = os.environ.get("TERM") or "xterm-256color"
        try:
            os.execv(LAB_CHECKIN, [LAB_CHECKIN])
        finally:
            os._exit(127)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    return pid, fd


def _reap(pid, fd):
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    for _ in range(20):
        try:
            if os.waitpid(pid, os.WNOHANG)[0]:
                break
        except OSError:
            break
        time.sleep(0.05)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except OSError:
            pass
    try:
        os.close(fd)
    except OSError:
        pass


def _drive(wait_minutes, timeout, log):
    """Run lab-checkin in a hidden terminal and press the keys a person would.

    The screen is rebuilt cell by cell (vtscreen), because the TUI only redraws
    what changed and animates a spinner, so the raw output never holds whole
    words. Returns (outcome, last screen text, keys sent)."""
    import select
    from vtscreen import Screen
    pid, fd = _spawn(CHECKIN_ROWS, CHECKIN_COLS)
    scr = Screen(CHECKIN_ROWS, CHECKIN_COLS)
    sent, outcome = [], None
    start = time.time()
    deadline = start + timeout
    wait_until = start + wait_minutes * 60
    hard = max(wait_until, start) + timeout + 60     # never longer than this, whatever the screen
    state, state_since, last_key_at, presses_here = None, start, 0.0, 0
    retries, last_retry = 0, 0.0
    exited = False
    snap = ""

    def press(key, why):
        nonlocal last_key_at, presses_here
        try:
            os.write(fd, key)
        except OSError:
            return
        sent.append(why)
        last_key_at = time.time()
        presses_here += 1
        if log:
            log.write(b"\n<<<sent %r at +%.1fs>>>\n" % (key, time.time() - start))

    try:
        while time.time() < min(deadline, hard):
            r, _, _ = select.select([fd], [], [], 0.15)
            if r:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    exited = True
                    break
                if log:
                    log.write(chunk)
                scr.feed(chunk)
                reply = scr.take_replies()      # e.g. cursor-position queries
                if reply:
                    try:
                        os.write(fd, reply)
                    except OSError:
                        pass
            now = time.time()
            flat = scr.flat()
            st = checkin_state(flat)
            if st or flat.strip():
                snap = scr.text()            # the TUI wipes its screen on exit; keep the last one
            if st != state:
                state, state_since, presses_here = st, now, 0
            if now - state_since < 0.5:
                continue                         # let the new screen finish drawing
            if st is None and now - state_since > 20:
                break                            # a screen we don't know: hand over
            # a key on this screen already went in: give it 4 s, then press again (max 3)
            if presses_here and now - last_key_at < 4:
                continue
            if presses_here >= 3 and st not in ("none",):
                break                            # keys aren't landing: hand over

            if st == "recorded":
                outcome = "recorded"
                press(b"q" if presses_here == 0 else b"\r", "q (close)")
            elif st == "failed":
                if retries and now - last_retry < 6:
                    continue                     # the retry may still be on its way
                if re.search(RETRYABLE, flat) and retries < 2:
                    retries += 1
                    last_retry = now
                    deadline = max(deadline, now + 45)
                    press(b"r", "r (retry)")
                    presses_here = 0
                else:
                    outcome = "failed"
                    press(b"q", "q (quit)")
            elif st == "none":
                if now < wait_until:
                    if now - last_retry > 30:
                        if not last_retry:
                            say("  no session open yet; trying again every 30 s (Ctrl-C to stop)")
                        last_retry = now
                        deadline = max(deadline, now + 60)
                        press(b"r", "r (try again)")
                        presses_here = 0
                    continue
                outcome = "none open"
                press(b"q", "q (quit)")
            elif st == "confirm":
                press(b"y", "y (check in)")
            elif st == "list":
                press(b"\r", "Enter (select session)")
            elif st in ("auth", "recording"):
                deadline = max(deadline, now + 20)   # server is working; don't give up mid-way
            if outcome and presses_here >= 2:
                break
    finally:
        # Let a final screen finish (e.g. after q), then stop it.
        _reap(pid, fd)
    text = scr.text() if scr.flat().strip() else snap
    if outcome is None and exited:
        outcome = "exited"
    return outcome, text, sent


def _interactive(log):
    """Hand the real check-in to the person at the keyboard, watching the screen.

    Their keys go straight to it; we only look for CHECK-IN RECORDED."""
    import select, termios, tty, fcntl, struct
    from vtscreen import Screen
    try:
        rows, cols = struct.unpack("HHHH", fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b"\0" * 8))[:2]
    except OSError:
        rows, cols = CHECKIN_ROWS, CHECKIN_COLS
    rows, cols = rows or CHECKIN_ROWS, cols or CHECKIN_COLS
    pid, fd = _spawn(rows, cols)
    scr = Screen(rows, cols)
    stdin = sys.stdin.fileno()
    old = termios.tcgetattr(stdin)
    recorded = False
    try:
        tty.setraw(stdin)
        while True:
            r, _, _ = select.select([fd, stdin], [], [], 0.5)
            if fd in r:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    break
                os.write(sys.stdout.fileno(), chunk)
                if log:
                    log.write(chunk)
                scr.feed(chunk)
                scr.take_replies()           # the real terminal answers for itself
                if re.search(r"CHECK-IN RECORDED", scr.flat()):
                    recorded = True
            if stdin in r:
                data = os.read(stdin, 1024)
                if not data:
                    break
                os.write(fd, data)
    finally:
        termios.tcsetattr(stdin, termios.TCSADRAIN, old)
        _reap(pid, fd)
        os.write(sys.stdout.fileno(), b"\x1b[?1049l\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?2004l\x1b[?25h\r\n")
    return recorded, scr.text()


def _screen_lines(text, n=8):
    lines = [re.sub(r"[─-╿]+", " ", l).strip() for l in text.split("\n")]
    lines = [re.sub(r"\s{2,}", "  ", l) for l in lines if l.strip(" │")]
    return lines[-n:]


def lab_checkin(wait_minutes=0, timeout=90, manual=False):
    """The exercise-class check-in: Enter on the session, y on "Check in as …?",
    q when it says CHECK-IN RECORDED. If it can't get there by itself it opens
    the check-in right here for you to press the keys, so it never just hangs."""
    head("Lab check-in")
    if not os.access(LAB_CHECKIN, os.X_OK):
        say("  %s not found (not on a lab PC?), skipped" % LAB_CHECKIN)
        return False
    log_path, log = _open_log()
    try:
        if manual:
            outcome, text, sent = None, "", []
        else:
            outcome, text, sent = _drive(wait_minutes, timeout, log)
        flat = re.sub(r"[─-╿]+", " ", text)
        flat = re.sub(r"\s+", " ", flat)

        if outcome == "recorded":
            m = re.search(r"\b([A-Z]{2}\d{4})\b.*?(on time|\d+m \d+s after start|\d+s after start|early|late)", flat)
            say("  CHECKED IN" + (" – %s, %s" % (m.group(1), m.group(2)) if m else ""))
            return True
        if outcome == "none open":
            say("  no attendance session open right now (it opens 10 minutes before the class)")
            say("  run ./start checkin again closer to the start, or ./start checkin --wait 15")
            return False
        if outcome == "failed":
            m = re.search(r"CHECK-IN FAILED\s*(.{0,200}?)\s*(Retrying|r retry|q quit|$)", flat)
            say("  check-in FAILED: %s" % (m.group(1).strip() if m else "see below"))
            for line in _screen_lines(text):
                say("    | " + line[:150])
            return False
        if outcome == "exited" and text.strip():
            say("  lab-checkin stopped by itself:")
            for line in _screen_lines(text):
                say("    | " + line[:150])
            if "workstation metadata" in flat or "logind" in flat:
                say("  (it needs the lab PC's own desktop login – not ssh or su)")
            return False

        # Stuck on a screen we can't read, or keys not landing: give it to Jack.
        if not manual:
            say("  couldn't finish it by itself (keys sent: %s). Last screen:" % (", ".join(sent) or "none"))
            for line in _screen_lines(text):
                say("    | " + line[:150])
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            say("  run %s by hand: Enter, then y, then q" % LAB_CHECKIN)
            return False
        say("  opening the check-in here – press Enter, then y, then q")
        time.sleep(1.5)
        recorded, text = _interactive(log)
        say("  CHECKED IN" if recorded else "  check-in closed without CHECK-IN RECORDED")
        return recorded
    finally:
        if log:
            log.close()
            say("  (screen log: %s)" % os.path.relpath(log_path, HERE))


# ================================================================ exercises
WEEK_RE = re.compile(r"^W\d+$")
SKIP_NAMES = {".DS_Store", "__MACOSX", "Thumbs.db"}
DOC_EXT = {".html", ".htm", ".pdf", ".css", ".gif", ".png", ".jpg", ".jpeg", ".svg"}


def read_srcdir(config_path):
    try:
        with open(config_path, encoding="utf-8", errors="replace") as f:
            m = re.search(r"^\s*srcdir\s*=\s*(\S+)", f.read(), re.M)
            return m.group(1) if m else None
    except OSError:
        return None


def week_tests(week_dir):
    """[(tests_dir, srcdir)] for every Tests folder (and Tests/<part>) in a week."""
    out = []
    for root, dirs, files in os.walk(week_dir):
        dirs.sort()
        if "practical.config" in files and "Tests" in root.split(os.sep):
            srcdir = read_srcdir(os.path.join(root, "practical.config"))
            if srcdir:
                out.append((root, srcdir))
    return out


def place(rel_parts, srcdirs, here_srcdir, is_doc):
    """Where a StudRes file goes, relative to the week folder.

    Code goes into the folder stacscheck expects (the test's srcdir), directly
    under the week: W07/W07Exercises/W07Exercises.java. Sheets and their
    css/images keep their StudRes place so the HTML still renders."""
    for i, part in enumerate(rel_parts[:-1]):
        if part in srcdirs:
            return rel_parts[i:]
    if not is_doc and here_srcdir:
        return [here_srcdir, rel_parts[-1]]
    return rel_parts


def plan_week(week_src):
    """[(dest_rel_path, kind, source)]: kind 'file' (source path) or 'zip' ((zip, member))."""
    tests = week_tests(week_src)
    srcdirs = {s for _, s in tests}
    # srcdir for files sitting next to a Tests folder (e.g. W07/W07Exercises.java)
    beside = {}
    for tdir, s in tests:
        parts = tdir.split(os.sep)
        idx = len(parts) - 1 - parts[::-1].index("Tests")
        beside.setdefault(os.sep.join(parts[:idx]), s)

    plan, problems = [], []
    for root, dirs, files in os.walk(week_src, onerror=lambda e: problems.append(
            "%s (%s)" % (os.path.relpath(getattr(e, "filename", "") or week_src, week_src), _why(e)))):
        dirs[:] = sorted(d for d in dirs if d != "Tests" and d not in SKIP_NAMES)
        rel_root = os.path.relpath(root, week_src)
        rel_root_parts = [] if rel_root == "." else rel_root.split(os.sep)
        for name in sorted(files):
            if name in SKIP_NAMES or name.startswith("._"):
                continue
            path = os.path.join(root, name)
            ext = os.path.splitext(name)[1].lower()
            if ext == ".zip":
                try:
                    with zipfile.ZipFile(path) as z:
                        for member in z.namelist():
                            mparts = [p for p in member.split("/") if p]
                            if (member.endswith("/") or not mparts
                                    or any(p in SKIP_NAMES or p.startswith("._") or p == ".."
                                           for p in mparts)):
                                continue
                            mext = os.path.splitext(mparts[-1])[1].lower()
                            dest = place(rel_root_parts + mparts, srcdirs,
                                         beside.get(root), mext in DOC_EXT)
                            plan.append((os.path.join(*dest), "zip", (path, member)))
                except (zipfile.BadZipFile, OSError, RuntimeError, ValueError) as e:
                    problems.append("%s (%s)" % (os.path.join(*(rel_root_parts + [name])), _why(e)))
                continue
            dest = place(rel_root_parts + [name], srcdirs, beside.get(root), ext in DOC_EXT)
            plan.append((os.path.join(*dest), "file", path))
    # A loose StudRes file beats the same file inside a zip (W02's zip has an empty copy).
    plan.sort(key=lambda p: p[1] != "file")
    return plan, tests, problems


def _why(e):
    return getattr(e, "strerror", None) or str(e) or type(e).__name__


def _copy_one(kind, source, dest):
    """Copy one file to dest, which must not exist yet (never overwrites).
    If the copy breaks half way, only the file this call created is removed."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if kind == "file":
        src = open(source, "rb")
    else:
        zpath, member = source
        z = zipfile.ZipFile(zpath)
        try:
            src = z.open(member)
        except BaseException:
            z.close()
            raise
    try:
        out = open(dest, "xb")          # FileExistsError if it's there: nothing is touched
    except BaseException:
        src.close()
        raise
    try:
        with src, out:
            shutil.copyfileobj(src, out)
    except BaseException:
        try:
            os.unlink(dest)             # ours, half written
        except OSError:
            pass
        raise
    finally:
        if kind != "file":
            z.close()
    if kind == "file":
        try:
            shutil.copystat(source, dest)   # keep the date; fine if the file system won't
        except OSError:
            pass
    try:
        os.chmod(dest, os.stat(dest).st_mode | stat.S_IWUSR | stat.S_IRUSR)
    except OSError:
        pass


def sync_exercises(dry_run=False):
    """Copy new StudRes exercise files into ~/Documents. Never overwrites, never
    crashes: a file, zip or week that can't be read is listed and skipped."""
    head("CS1002 exercises")
    try:
        weeks = sorted((w for w in os.listdir(STUDRES_EXERCISES) if WEEK_RE.match(w)),
                       key=lambda w: int(w[1:]))
    except OSError as e:
        say("  can't read %s (%s) – not on a lab PC?, skipped" % (STUDRES_EXERCISES, _why(e)))
        return False
    copied, kept, failed = [], 0, []
    newest_tests = None
    for week in weeks:
        week_src = os.path.join(STUDRES_EXERCISES, week)
        week_dst = os.path.join(MY_EXERCISES, week)
        try:
            plan, tests, problems = plan_week(week_src)
        except Exception as e:           # a whole week unreadable: skip just that week
            failed.append("%s/ (%s)" % (week, _why(e)))
            continue
        failed.extend(os.path.join(week, p) for p in problems)
        if tests:
            newest_tests = (week, tests)
            for _, srcdir in tests:   # the folder stacscheck looks for, even with no starter code
                d = os.path.join(week_dst, srcdir)
                if not os.path.isdir(d):
                    if dry_run:
                        copied.append(os.path.join(week, srcdir) + "/")
                        continue
                    try:
                        os.makedirs(d, exist_ok=True)
                        copied.append(os.path.join(week, srcdir) + "/")
                    except OSError as e:
                        failed.append("%s/ (%s)" % (os.path.join(week, srcdir), _why(e)))
        seen = set()
        for rel, kind, source in plan:
            if rel in seen:
                continue
            seen.add(rel)
            dest = os.path.join(week_dst, rel)
            if os.path.lexists(dest):
                kept += 1
                continue
            if dry_run:
                copied.append(os.path.join(week, rel))
                continue
            try:
                _copy_one(kind, source, dest)
                copied.append(os.path.join(week, rel))
            except KeyboardInterrupt:
                raise
            except FileExistsError:
                kept += 1
            except Exception as e:
                failed.append("%s (%s)" % (os.path.join(week, rel), _why(e)))

    # Shared stylesheet some sheets link to (../css/standard.css)
    css_src = os.path.join(STUDRES_EXERCISES, "css")
    try:
        css_names = sorted(os.listdir(css_src)) if os.path.isdir(css_src) else []
    except OSError as e:
        css_names = []
        failed.append("css/ (%s)" % _why(e))
    for name in css_names:
        dest = os.path.join(MY_EXERCISES, "css", name)
        if os.path.lexists(dest) or not os.path.isfile(os.path.join(css_src, name)):
            continue
        if dry_run:
            copied.append(os.path.join("css", name))
            continue
        try:
            _copy_one("file", os.path.join(css_src, name), dest)
            copied.append(os.path.join("css", name))
        except Exception as e:
            failed.append("css/%s (%s)" % (name, _why(e)))

    verb = "would copy" if dry_run else "copied"
    if copied:
        say("  %s %d new file(s) into %s:" % (verb, len(copied), MY_EXERCISES))
        for c in copied[:40]:
            say("    + " + c)
        if len(copied) > 40:
            say("    … and %d more" % (len(copied) - 40))
    else:
        say("  up to date (%s)" % MY_EXERCISES)
    say("  %d existing file(s) left untouched" % kept)
    if failed:
        say("  skipped %d thing(s) StudRes wouldn't let me read (everything else is copied):" % len(failed))
        for f in failed[:10]:
            say("    ! " + f)
        if len(failed) > 10:
            say("    … and %d more" % (len(failed) - 10))
    if newest_tests:
        week, tests = newest_tests
        LATEST["week"], LATEST["srcdirs"] = week, [s for _, s in tests]
        say("  test %s with:" % week)
        say("    cd %s" % os.path.join(MY_EXERCISES, week))
        for tdir, _ in tests:
            if os.path.basename(tdir) == "Tests" or len(tests) == 1:
                say("    stacscheck %s" % tdir)
    # Copying most of it is a success; skipped files are reported above.
    return bool(weeks) and (bool(copied) or kept > 0 or not failed)


# ================================================================== vscode
LATEST = {}   # newest exercise week, filled in by sync_exercises


def latest_week_dir():
    """~/Documents/CS1002/Exercises/WNN for the newest week (from this run, else on disk)."""
    if LATEST.get("week"):
        d = os.path.join(MY_EXERCISES, LATEST["week"])
        if os.path.isdir(d):
            return d, LATEST.get("srcdirs", [])
    try:
        weeks = sorted((w for w in os.listdir(MY_EXERCISES)
                        if WEEK_RE.match(w) and os.path.isdir(os.path.join(MY_EXERCISES, w))),
                       key=lambda w: int(w[1:]))
    except OSError:
        return None, []
    return (os.path.join(MY_EXERCISES, weeks[-1]), []) if weeks else (None, [])


def find_code():
    for name in ("code", "codium", "code-oss"):
        path = shutil.which(name)
        if path:
            return [path]
    for path in ("/usr/bin/code", "/usr/share/code/bin/code", "/opt/visual-studio-code/bin/code",
                 "/var/lib/flatpak/exports/bin/com.visualstudio.code"):
        if os.access(path, os.X_OK):
            return [path]
    if shutil.which("flatpak") and run(["flatpak", "info", "com.visualstudio.code"]).returncode == 0:
        return ["flatpak", "run", "com.visualstudio.code"]
    return None


def open_vscode():
    """Open VS Code on the newest week, with its main .java file in front.
    The week folder is the workspace, so VS Code's terminal starts where stacscheck wants."""
    head("VS Code")
    week_dir, srcdirs = latest_week_dir()
    if not week_dir:
        say("  no exercise week in %s yet, skipped" % MY_EXERCISES)
        return False
    code = find_code()
    if not code:
        say("  VS Code not found on this PC, skipped")
        return False
    files = []
    for sd in srcdirs or sorted(os.listdir(week_dir)):
        d = os.path.join(week_dir, sd)
        if not os.path.isdir(d):
            continue
        try:
            javas = sorted(f for f in os.listdir(d) if f.endswith(".java"))
        except OSError:
            continue
        main = [f for f in javas if f == sd + ".java"] or javas[:1]
        files += [os.path.join(d, f) for f in main]
    cmd = code + ["--new-window", week_dir] + files[:2]
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, cwd=week_dir)
    except OSError as e:
        say("  couldn't start VS Code: %s" % _why(e))
        return False
    say("  opened %s%s" % (week_dir, (" (" + ", ".join(os.path.basename(f) for f in files[:2]) + ")") if files else ""))
    return True


# ================================================================== browser
def load_env():
    """EMAIL/PASSWORD from .env; creates the template the first time."""
    if not os.path.exists(ENV_FILE):
        fd = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(ENV_TEMPLATE)
    mode = stat.S_IMODE(os.stat(ENV_FILE).st_mode)
    if mode & 0o077:
        os.chmod(ENV_FILE, 0o600)
    env = {}
    with open(ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            env[k.strip().upper()] = v
    return env.get("EMAIL", ""), env.get("PASSWORD", "")


def port_open(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
        return True
    except OSError:
        return False


def firefox_running():
    return run(["pgrep", "-u", str(os.getuid()), "-x", "firefox|firefox-bin|firefox-esr"]).returncode == 0


def launch_firefox():
    # In logs/ (inside ~/Documents) so it survives logout: if a tab crashes, the reason is in here.
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        log = open(os.path.join(LOG_DIR, time.strftime("firefox-%Y%m%d-%H%M%S.log")), "ab")
    except OSError:
        log = subprocess.DEVNULL
    subprocess.Popen(["firefox", "--marionette", "--remote-allow-system-access"]
                     if firefox_supports_system_access() else ["firefox", "--marionette"],
                     stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)


def firefox_supports_system_access():
    # Firefox 138+ needs --remote-allow-system-access for chrome-context scripts;
    # older ones reject unknown flags silently, so only add it when it exists.
    r = run(["firefox", "--help"])
    return "--remote-allow-system-access" in (r.stdout + r.stderr)


def open_tabs_plain(urls):
    for u in urls:
        subprocess.Popen(["firefox", "--new-tab", u], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        time.sleep(1.5)


DETECT_JS = r"""
// Microsoft keeps the inactive email/password box in the page "off screen"
// (class moveOffScreen, tabindex -1, opacity 0) for password managers.
const vis = e => {
  if (!e || e.offsetWidth === 0 || e.offsetHeight === 0 || e.closest('.moveOffScreen')) return false;
  const cs = getComputedStyle(e), r = e.getBoundingClientRect();
  return cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0' &&
    !(e.tagName === 'INPUT' && e.tabIndex < 0) && r.right > 0 && r.bottom > 0 &&
    r.left < innerWidth && r.top < innerHeight;
};
const q = s => [...document.querySelectorAll(s)].find(vis) || null;
const text = (document.body && document.body.innerText) || '';
const out = {url: location.href, ready: document.readyState, kind: 'wait',
             page: (document.title + ' | ' + text.slice(0, 600))};
const err = q('#usernameError, #passwordError, #errorText, [data-testid="error"], .alert-error, #idTD_Error');
if (err && err.innerText.trim()) { out.kind = 'error'; out.error = err.innerText.trim().slice(0, 200); return out; }
// The password page keeps the email box in the DOM, so look for the password first.
const pw = q('input[name="passwd"], input[type="password"]');
if (pw) { out.kind = 'password'; out.filled = !!pw.value; return out; }
if (q('input[name="loginfmt"]')) { out.kind = 'email'; out.filled = !!q('input[name="loginfmt"]').value; return out; }
let num = q('#idRichContext_DisplaySign, #displaySign, [data-testid="displaySign"]');
if (!num && /Authenticator|Approve sign.?in/i.test(text))
  num = [...document.querySelectorAll('div,span,p')].find(e => vis(e) && /^\s*\d{2,3}\s*$/.test(e.innerText || ''));
if (num) { out.kind = 'number'; out.number = num.innerText.trim(); return out; }
if (/Approve sign.?in request|Check your Authenticator|open your Authenticator/i.test(text)) { out.kind = 'approve'; return out; }
if (/We didn.t hear from you|request (was )?denied|denied the request|You.ve hit our limit/i.test(text)) {
  out.kind = 'error'; out.error = 'Authenticator: ' + (text.match(/We didn.t hear from you|request (was )?denied|denied the request|You.ve hit our limit[^.]*/i) || [''])[0]; return out; }
if (/Stay signed in\?/i.test(text)) { out.kind = 'kmsi'; return out; }
if (/Pick an account/i.test(text)) { out.kind = 'picker'; return out; }
if (/Verify your identity/i.test(text)) { out.kind = 'method'; return out; }
if (/Sign in/i.test(text) && q('#idSIButton9, input[type="submit"]') && /mms\./.test(location.host)) { out.kind = 'sitebutton'; }
return out;
"""

CLICK_TEXT_JS = r"""
const want = arguments[0].toLowerCase();
const vis = e => !!e && e.offsetWidth > 0 && e.offsetHeight > 0;
const els = [...document.querySelectorAll('[role="button"], [role="link"], button, a, div[data-value], div.table, small')];
const hit = els.filter(vis).find(e => (e.innerText || '').toLowerCase().includes(want));
if (hit) { hit.click(); return true; }
return false;
"""


class LoginFailed(Exception):
    pass


def submit(m):
    btn = m.find("#idSIButton9") or m.find('input[type="submit"]') or m.find('button[type="submit"]')
    if btn:
        try:
            m.click(btn)
        except MarionetteError:
            m.js("arguments[0].click()", btn)


def sign_in(m, url, email, password, state):
    """Drive whatever login page the current tab shows until the site in url is open."""
    target_hosts, signed_in_re = SIGNED_IN[url]
    target = url
    deadline = time.time() + LOGIN_TIMEOUT
    last = (None, 0.0)
    silent_since = None
    while time.time() < deadline:
        try:
            page = m.js(DETECT_JS)
            silent_since = None
        except MarionetteError:
            # page mid-navigation, or Firefox slow to answer; a tab that stays silent has died
            silent_since = silent_since or time.time()
            if time.time() - silent_since > 20:
                reload_crashed(m, target, state, "isn't answering")
                silent_since = None
            time.sleep(0.5)
            continue
        if tab_crashed(page):
            reload_crashed(m, target, state, "crashed")
            continue
        url = page.get("url", "")
        host = re.sub(r"^\w+://([^/]+).*$", r"\1", url)
        if (host in target_hosts and page.get("ready") == "complete"
                and re.search(signed_in_re, page.get("page", ""))):
            return True
        if host not in LOGIN_HOSTS and not host.endswith(".microsoftonline.com"):
            time.sleep(0.5)   # a redirect hop on the way
            continue
        kind = page.get("kind")
        key = (kind, page.get("number"))
        if key == last[0] and time.time() - last[1] < 6:
            time.sleep(0.5)   # same page, already acted on it
            continue
        last = (key, time.time())

        try:
            act(m, page, kind, email, password, state)
        except MarionetteError:
            pass   # the page changed under us; look again
        time.sleep(0.7)
    raise LoginFailed("timed out after %d s waiting for %s" % (LOGIN_TIMEOUT, target_hosts[0]))


def act(m, page, kind, email, password, state):
    """Do the one thing the current login page needs."""
    if kind == "error":
        raise LoginFailed(page.get("error", "sign-in error"))
    if kind == "email":
        if not email:
            raise LoginFailed("no EMAIL in %s" % ENV_FILE)
        box = m.find('input[name="loginfmt"]')
        if not page.get("filled"):
            m.clear(box)
            m.send_keys(box, email)
        submit(m)
        say("  email entered")
    elif kind == "password":
        if not password:
            raise LoginFailed("no PASSWORD in %s – fill it in and run ./start browser" % ENV_FILE)
        if state.get("password_tries", 0) >= 1:
            raise LoginFailed("the password page came back – check PASSWORD in .env "
                              "(stopped so your account doesn't get locked)")
        state["password_tries"] = state.get("password_tries", 0) + 1
        box = m.find('input[name="passwd"]') or m.find('input[type="password"]')
        m.clear(box)
        m.send_keys(box, password)
        submit(m)
        say("  password entered")
    elif kind == "number":
        if state.get("shown") != page["number"]:   # once per code, not every poll
            state["shown"] = page["number"]
            show_number(page["number"])
    elif kind == "approve":
        if state.get("shown") != "approve":
            state["shown"] = "approve"
            say("  approve the sign-in on your phone (Microsoft Authenticator)…")
            notify("Approve the sign-in in Microsoft Authenticator")
    elif kind == "kmsi":
        submit(m)   # "Stay signed in?" -> Yes (this PC forgets it on restart anyway)
        say("  'Stay signed in?' -> Yes")
    elif kind == "picker":
        if email and m.js(CLICK_TEXT_JS, email):
            say("  picked account " + email)
    elif kind == "method":
        for label in ("Approve a request on my Microsoft Authenticator",
                      "Microsoft Authenticator", "Authenticator app"):
            if m.js(CLICK_TEXT_JS, label):
                say("  chose Microsoft Authenticator")
                break


def tab_crashed(page):
    """Firefox's "Gah. Your tab just crashed." page (about:tabcrashed)."""
    return (page.get("url", "").startswith("about:tabcrashed")
            or re.search(r"tab just crashed|Your tab crashed|Tab crashed", page.get("page", ""), re.I))


def reload_crashed(m, url, state, why):
    """Load the site again in a tab that crashed; give up after 3 tries per run."""
    state["crashes"] = state.get("crashes", 0) + 1
    if state["crashes"] > 3:
        raise LoginFailed("the tab keeps crashing – Firefox's reason is in logs/firefox-*.log")
    say("  the tab %s – loading it again (%d/3)" % (why, state["crashes"]))
    try:
        m.navigate(url)
    except MarionetteError:
        try:                                  # the tab itself is gone: use a fresh one
            m.switch_to(m.new_tab())
            m.navigate(url)
        except MarionetteError:
            pass
    time.sleep(1)


def heal_tabs(m, handles, urls, state):
    """Last look at each of our tabs: any that crashed gets its site loaded again."""
    for h, url in zip(handles, urls):
        try:
            m.switch_to(h)
            page = m.js("return {url: location.href, page: document.title + ' | ' + "
                        "((document.body && document.body.innerText) || '').slice(0, 300)};")
        except MarionetteError:
            continue
        if tab_crashed(page):
            try:
                reload_crashed(m, url, state, "crashed")
            except LoginFailed as e:
                say("  " + str(e))


def show_number(number):
    say("")
    say("  ┌──────────────────────────────────────────┐")
    say("  │  Type  %-4s into Microsoft Authenticator  │" % number)
    say("  └──────────────────────────────────────────┘")
    say("")
    notify("Authenticator number: " + number)


def notify(text):
    if shutil.which("notify-send"):
        # normal urgency: GNOME never hides "critical" ones, so a used code would stay on screen
        run(["notify-send", "-u", "normal", "-t", "120000", "CS lab start", text])


def quiet_first_run(m):
    """Stop Firefox's first-run welcome/privacy tabs (needs chrome context)."""
    try:
        m.send("Marionette:SetContext", {"value": "chrome"})
        m.js("""
          const p = Services.prefs;
          p.setBoolPref('browser.aboutwelcome.enabled', false);
          p.setBoolPref('datareporting.policy.dataSubmissionPolicyBypassNotification', true);
          p.setBoolPref('browser.shell.checkDefaultBrowser', false);
          p.setCharPref('browser.startup.homepage_override.mstone', 'ignore');
          // Lab home folders are small: keep the web cache in memory, not on disk,
          // so a full quota can't make tabs crash.
          p.setBoolPref('browser.cache.disk.enable', false);
          p.setBoolPref('browser.cache.memory.enable', true);
        """)
    except MarionetteError:
        pass
    finally:
        try:
            m.send("Marionette:SetContext", {"value": "content"})
        except MarionetteError:
            pass


def setup_browser(login=True):
    head("Firefox")
    urls = [("StudRes CS1002", STUDRES_URL), ("Outlook", OUTLOOK_URL), ("MMS CS1002", MMS_URL)]
    email, password = load_env()
    if login and not password:
        say("  .env has no PASSWORD yet: fill in %s, then run ./start browser" % ENV_FILE)
        say("  (opening the tabs without signing in for now)")
        login = False

    if not port_open(MARIONETTE_PORT):
        if firefox_running():
            say("  Firefox is already open without remote control, so it can't sign in for you.")
            say("  Opening the tabs in it instead. For auto sign-in: close Firefox, run ./start browser")
            open_tabs_plain([u for _, u in urls])
            return False
        launch_firefox()
    m = Marionette(MARIONETTE_PORT)
    try:
        m.connect(timeout=90)
        m.new_session()
    except (MarionetteError, OSError) as e:
        say("  couldn't control Firefox (%s); opening the tabs plainly" % e)
        open_tabs_plain([u for _, u in urls])
        return False
    quiet_first_run(m)

    ok = True
    state = {}
    try:
        start_handles = m.handles()
        mine = []
        for i, (name, url) in enumerate(urls):
            handle = start_handles[0] if i == 0 else m.new_tab()
            m.switch_to(handle)
            mine.append(handle)
            say("  %s: %s" % (name, url))
            m.navigate(url)
            if login:
                try:
                    sign_in(m, url, email, password, state)
                    say("  %s: signed in" % name)
                except LoginFailed as e:
                    say("  %s: NOT signed in – %s" % (name, e))
                    ok = False
                    login = False   # don't hammer the login page from the other tabs
        heal_tabs(m, mine, [u for _, u in urls], state)
        # Close anything else (welcome page, privacy notice, old tabs).
        time.sleep(2)
        for h in m.handles():
            if h not in mine:
                m.switch_to(h)
                m.close_tab()
        m.switch_to(mine[0])
    except (MarionetteError, OSError) as e:
        say("  lost control of Firefox (closed?): %s" % e)
        ok = False
    finally:
        m.delete_session()   # ends remote control; Firefox stays open
        m.close()
    return ok


# ============================================================ close terminal
TERMINAL_APPS = ("gnome-terminal-", "gnome-terminal", "ptyxis", "ptyxis-agent", "kgx", "konsole",
                 "xterm", "xfce4-terminal", "tilix", "terminator", "mate-terminal", "alacritty",
                 "kitty", "foot", "ghostty", "wezterm-gui")
SHELLS = ("bash", "zsh", "sh", "fish", "dash", "ksh", "tcsh")


def proc_name(pid):
    try:
        with open("/proc/%d/comm" % pid) as f:
            return f.read().strip()
    except OSError:
        return ""


def proc_parent(pid):
    try:
        with open("/proc/%d/stat" % pid) as f:
            return int(f.read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


def close_my_terminal():
    """Close the terminal tab this was started from, so only Firefox is left.

    Only when it's plainly an interactive shell inside a terminal app; ./start
    run from a script, over ssh or inside another program is left alone."""
    shell = os.getppid()
    if proc_name(shell) not in SHELLS or not sys.stdin.isatty():
        return False
    term = proc_name(proc_parent(shell))
    if not term.startswith(TERMINAL_APPS):
        return False
    say("\n  all done – closing this terminal")
    sys.stdout.flush()
    time.sleep(2)
    os.kill(shell, signal.SIGHUP)   # the shell exits, so the terminal tab/window closes
    return True


# ===================================================================== main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("parts", nargs="*", metavar="part",
                    help="desktop, checkin, exercises, vscode, browser (default: all of them)")
    ap.add_argument("--no-login", action="store_true", help="open the tabs without signing in")
    ap.add_argument("--dry-run", action="store_true", help="exercises: only show what would be copied")
    ap.add_argument("--keep-terminal", action="store_true",
                    help="don't close this terminal at the end")
    ap.add_argument("--manual", action="store_true",
                    help="checkin: open the check-in for you to press the keys yourself")
    ap.add_argument("--wait", type=float, default=0, metavar="MIN",
                    help="checkin: keep retrying for MIN minutes if no session is open yet")
    args = ap.parse_args()
    known = ["desktop", "checkin", "exercises", "vscode", "browser"]
    bad = [p for p in args.parts if p not in known]
    if bad:
        ap.error("unknown part %s (choose from %s)" % (", ".join(bad), ", ".join(known)))
    parts = args.parts or known

    steps = {
        "desktop": setup_desktop,
        "checkin": lambda: lab_checkin(args.wait, manual=args.manual),
        "exercises": lambda: sync_exercises(args.dry_run),
        "vscode": open_vscode,
        "browser": lambda: setup_browser(login=not args.no_login),
    }
    results = {}
    try:
        for name in known:
            if name in parts:
                try:
                    results[name] = steps[name]()
                except KeyboardInterrupt:
                    raise
                except Exception as e:   # one broken part never stops the rest
                    say("  %s crashed: %s: %s" % (name, type(e).__name__, e))
                    results[name] = False
    except KeyboardInterrupt:
        say("\n  stopped (Ctrl-C)")
        return 130
    head("Done")
    for k, v in results.items():
        say("  %-10s %s" % (k, "ok" if v else "needs a look (see above)"))
    all_ok = all(results.values())
    # Full run that worked: leave only Firefox on screen. Anything wrong: keep
    # the terminal so the messages above can be read.
    if all_ok and not args.parts and not args.keep_terminal:
        close_my_terminal()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

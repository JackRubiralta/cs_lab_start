#!/usr/bin/env python3
"""cs_lab_start: set up a St Andrews CS lab PC the way Jack likes it, in one go.

  1. desktop    taskbar always shown with Firefox/VS Code/Terminal/Files pinned,
                mouse at half speed
  2. checkin    the exercise-class check-in (/cs/studres/ct/lab-checkin):
                selects the open session, presses y, then q
  3. exercises  copy every new CS1002 exercise week from /cs/studres into
                ~/Documents/CS1002/Exercises (never overwrites a file)
  4. browser    Firefox with StudRes CS1002, Outlook and MMS CS1002 open and
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

LOGIN_HOSTS = ("login.microsoftonline.com", "login.microsoft.com", "login.live.com",
               "login.st-andrews.ac.uk", "login.windows.net", "device.login.microsoftonline.com")


def say(msg=""):
    print(msg, flush=True)


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
ANSI_RE = re.compile(r"\x1b(\[[0-9;?<>=]*[ -/]*[@-~]|\][^\x07\x1b]*(\x07|\x1b\\)|[()][0-9A-Za-z]|[=>78DEHMNOZc])")


def screen_text(raw):
    """Terminal output -> plain text (escape codes and box lines removed)."""
    txt = ANSI_RE.sub(" ", raw.decode("utf-8", "replace"))
    txt = re.sub(r"[─│┌┐└┘├┤┬┴┼━┃╭╮╰╯═║]+", " ", txt)
    return re.sub(r"[ \t\r]+", " ", txt)


def lab_checkin(wait_minutes=0, timeout=60):
    """Run the School's check-in TUI in a hidden terminal and press the keys:
    Enter on the session list, y on "Check in as …?", q when done."""
    head("Lab check-in")
    if not os.access(LAB_CHECKIN, os.X_OK):
        say("  %s not found (not on a lab PC?), skipped" % LAB_CHECKIN)
        return False
    import pty, fcntl, termios, struct, select   # POSIX only
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = os.environ.get("TERM", "xterm-256color") or "xterm-256color"
        try:
            os.execv(LAB_CHECKIN, [LAB_CHECKIN])
        finally:
            os._exit(127)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))

    seen = b""            # everything since the last key we sent
    full = ""             # all plain text, for the summary
    sent = []
    outcome = None
    deadline = time.time() + timeout
    wait_until = time.time() + wait_minutes * 60
    last_retry = 0.0
    last_output = time.time()

    def press(key, why):
        nonlocal seen
        os.write(fd, key)
        sent.append(why)
        seen = b""

    try:
        while time.time() < deadline:
            r, _, _ = select.select([fd], [], [], 0.3)
            if r:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    break             # program exited
                if not chunk:
                    break
                seen += chunk
                full += screen_text(chunk)
                last_output = time.time()
                continue
            if time.time() - last_output < 0.4:
                continue              # let the screen finish drawing
            now = screen_text(seen)
            if re.search(r"CHECK-IN\s+RECORDED", now):
                outcome = "recorded"
                press(b"q", "q (close)")
            elif "NO ELIGIBLE SESSION" in now or "No attendance session" in now:
                if time.time() < wait_until:
                    if time.time() - last_retry > 30:
                        if not last_retry:
                            say("  no session open yet; trying again every 30 s (Ctrl-C to stop)")
                        last_retry = time.time()
                        deadline = time.time() + timeout
                        press(b"r", "r (try again)")
                    continue
                outcome = "none open"
                press(b"q", "q (quit)")
            elif "CHECK-IN FAILED" in now:
                outcome = "failed"
                press(b"q", "q (quit)")
            elif "Check in as" in now or "CONFIRM CHECK-IN" in now:
                press(b"y", "y (check in)")
            elif "ELIGIBLE SESSIONS" in now or "SELECTED SESSION" in now:
                press(b"\r", "Enter (select session)")
            elif outcome and time.time() - last_output > 2:
                break
    finally:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass
        os.close(fd)

    if outcome == "recorded":
        m = re.search(r"\b([A-Z]{2}\d{4})\b.*?(on time|\d+m \d+s after start|early|late)", full)
        say("  CHECKED IN" + (" – %s, %s" % (m.group(1), m.group(2)) if m else ""))
        return True
    if outcome == "none open":
        say("  no attendance session open right now (it opens 10 minutes before the class)")
        say("  run ./start checkin again closer to the start, or ./start checkin --wait 15")
        return False
    if outcome == "failed":
        msg = re.search(r"CHECK-IN FAILED\s*(.{0,160}?)\s*(Retrying|r retry|q quit|$)", full)
        say("  check-in FAILED: %s" % (msg.group(1).strip() if msg else "see lab-checkin"))
        return False
    say("  check-in didn't finish (keys sent: %s); run %s by hand" % (", ".join(sent) or "none", LAB_CHECKIN))
    tail = [l.strip() for l in full.replace("\r", "\n").split("\n") if l.strip()][-6:]
    for line in tail:
        say("    | " + line[:150])
    return False


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

    plan = []
    for root, dirs, files in os.walk(week_src):
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
                except zipfile.BadZipFile:
                    pass
                continue
            dest = place(rel_root_parts + [name], srcdirs, beside.get(root), ext in DOC_EXT)
            plan.append((os.path.join(*dest), "file", path))
    # A loose StudRes file beats the same file inside a zip (W02's zip has an empty copy).
    plan.sort(key=lambda p: p[1] != "file")
    return plan, tests


def sync_exercises(dry_run=False):
    head("CS1002 exercises")
    if not os.path.isdir(STUDRES_EXERCISES):
        say("  %s not found (not on a lab PC?), skipped" % STUDRES_EXERCISES)
        return False
    weeks = sorted((w for w in os.listdir(STUDRES_EXERCISES) if WEEK_RE.match(w)),
                   key=lambda w: int(w[1:]))
    copied, kept = [], 0
    newest_tests = None
    for week in weeks:
        week_src = os.path.join(STUDRES_EXERCISES, week)
        week_dst = os.path.join(MY_EXERCISES, week)
        plan, tests = plan_week(week_src)
        if tests:
            newest_tests = (week, tests)
            for _, srcdir in tests:   # the folder stacscheck looks for, even with no starter code
                d = os.path.join(week_dst, srcdir)
                if not os.path.isdir(d):
                    copied.append(os.path.join(week, srcdir) + "/")
                    if not dry_run:
                        os.makedirs(d, exist_ok=True)
        seen = set()
        for rel, kind, source in plan:
            if rel in seen:
                continue
            seen.add(rel)
            dest = os.path.join(week_dst, rel)
            if os.path.lexists(dest):
                kept += 1
                continue
            copied.append(os.path.join(week, rel))
            if dry_run:
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if kind == "file":
                shutil.copy2(source, dest)
            else:
                zpath, member = source
                with zipfile.ZipFile(zpath) as z, z.open(member) as src, open(dest, "xb") as out:
                    shutil.copyfileobj(src, out)
            os.chmod(dest, os.stat(dest).st_mode | stat.S_IWUSR)

    # Shared stylesheet some sheets link to (../css/standard.css)
    css_src = os.path.join(STUDRES_EXERCISES, "css")
    if os.path.isdir(css_src):
        for name in sorted(os.listdir(css_src)):
            dest = os.path.join(MY_EXERCISES, "css", name)
            if not os.path.lexists(dest):
                copied.append(os.path.join("css", name))
                if not dry_run:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copy2(os.path.join(css_src, name), dest)

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
    if newest_tests:
        week, tests = newest_tests
        say("  test %s with:" % week)
        say("    cd %s" % os.path.join(MY_EXERCISES, week))
        for tdir, _ in tests:
            if os.path.basename(tdir) == "Tests" or len(tests) == 1:
                say("    stacscheck %s" % tdir)
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
    log = open(os.path.join(os.path.expanduser("~"), ".cs_lab_start-firefox.log"), "ab")
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
const vis = e => !!e && e.offsetWidth > 0 && e.offsetHeight > 0 &&
  getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none';
const q = s => [...document.querySelectorAll(s)].find(vis) || null;
const text = (document.body && document.body.innerText) || '';
const out = {url: location.href, ready: document.readyState, kind: 'wait'};
const err = q('#usernameError, #passwordError, #errorText, [data-testid="error"], .alert-error, #idTD_Error');
if (err && err.innerText.trim()) { out.kind = 'error'; out.error = err.innerText.trim().slice(0, 200); return out; }
if (q('input[name="loginfmt"]')) { out.kind = 'email'; out.filled = !!q('input[name="loginfmt"]').value; return out; }
if (q('input[name="passwd"], input[type="password"]')) { out.kind = 'password'; return out; }
let num = q('#idRichContext_DisplaySign, #displaySign, [data-testid="displaySign"]');
if (!num && /Authenticator|Approve sign.?in/i.test(text))
  num = [...document.querySelectorAll('div,span,p')].find(e => vis(e) && /^\s*\d{2,3}\s*$/.test(e.innerText || ''));
if (num) { out.kind = 'number'; out.number = num.innerText.trim(); return out; }
if (/Approve sign.?in request|Check your Authenticator|open your Authenticator/i.test(text)) { out.kind = 'approve'; return out; }
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


def sign_in(m, target_host, email, password, state):
    """Drive whatever login page the current tab shows until it reaches target_host."""
    deadline = time.time() + LOGIN_TIMEOUT
    last = (None, 0.0)
    while time.time() < deadline:
        try:
            page = m.js(DETECT_JS)
        except MarionetteError:
            time.sleep(0.5)   # page mid-navigation
            continue
        url = page.get("url", "")
        host = re.sub(r"^\w+://([^/]+).*$", r"\1", url)
        if host == target_host and page.get("ready") != "loading":
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
            show_number(page["number"])
        elif kind == "approve":
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
        time.sleep(0.7)
    raise LoginFailed("timed out after %d s waiting for %s" % (LOGIN_TIMEOUT, target_host))


def show_number(number):
    say("")
    say("  ┌──────────────────────────────────────────┐")
    say("  │  Type  %-4s into Microsoft Authenticator  │" % number)
    say("  └──────────────────────────────────────────┘")
    say("")
    notify("Authenticator number: " + number)


def notify(text):
    if shutil.which("notify-send"):
        run(["notify-send", "-u", "critical", "CS lab start", text])


def quiet_first_run(m):
    """Stop Firefox's first-run welcome/privacy tabs (needs chrome context)."""
    try:
        m.send("Marionette:SetContext", {"value": "chrome"})
        m.js("""
          const p = Services.prefs;
          p.setBoolPref('browser.aboutwelcome.enabled', false);
          p.setBoolPref('datareporting.policy.dataSubmissionPolicyBypassNotification', true);
          p.setBoolPref('browser.shell.checkDefaultBrowser', false);
          p.setBoolPref('browser.startup.homepage_override.mstone', false) ;
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
                target = re.sub(r"^\w+://([^/]+).*$", r"\1", url)
                try:
                    sign_in(m, target, email, password, state)
                    say("  %s: signed in" % name)
                except LoginFailed as e:
                    say("  %s: NOT signed in – %s" % (name, e))
                    ok = False
                    login = False   # don't hammer the login page from the other tabs
        # Close anything else (welcome page, privacy notice, old tabs).
        time.sleep(2)
        for h in m.handles():
            if h not in mine:
                m.switch_to(h)
                m.close_tab()
        m.switch_to(mine[0])
    finally:
        m.delete_session()   # ends remote control; Firefox stays open
        m.close()
    return ok


# ===================================================================== main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("parts", nargs="*", metavar="part",
                    help="desktop, checkin, exercises, browser (default: all of them)")
    ap.add_argument("--no-login", action="store_true", help="open the tabs without signing in")
    ap.add_argument("--dry-run", action="store_true", help="exercises: only show what would be copied")
    ap.add_argument("--wait", type=float, default=0, metavar="MIN",
                    help="checkin: keep retrying for MIN minutes if no session is open yet")
    args = ap.parse_args()
    known = ["desktop", "checkin", "exercises", "browser"]
    bad = [p for p in args.parts if p not in known]
    if bad:
        ap.error("unknown part %s (choose from %s)" % (", ".join(bad), ", ".join(known)))
    parts = args.parts or known

    results = {}
    if "desktop" in parts:
        results["desktop"] = setup_desktop()
    if "checkin" in parts:
        results["checkin"] = lab_checkin(args.wait)
    if "exercises" in parts:
        results["exercises"] = sync_exercises(args.dry_run)
    if "browser" in parts:
        results["browser"] = setup_browser(login=not args.no_login)
    head("Done")
    for k, v in results.items():
        say("  %-10s %s" % (k, "ok" if v else "needs a look (see above)"))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

# cs_lab_start

One command that sets up a St Andrews CS lab PC (AlmaLinux, GNOME) for an
exercise class:

| Step | What it does |
|---|---|
| **desktop** | Keeps the taskbar always shown, pins Firefox, VS Code, Terminal and Files, and sets the mouse to half speed |
| **checkin** | Runs the attendance check-in `/cs/studres/ct/lab-checkin`. It selects the open session, presses `y`, then `q`. If it can't finish by itself, it opens the check-in right in the terminal for you to press Enter, `y`, `q`, so it never just sits there |
| **exercises** | Copies every CS1002 exercise week from `/cs/studres/CS1002/Exercises` into `~/Documents/CS1002/Exercises`. **Never replaces a file that's already there**, so your answers are safe and only new weeks or missing files are added. A file, zip or folder StudRes won't let you read is listed and skipped, never a crash |
| **vscode** | Opens VS Code in the newest exercise's code folder (`~/Documents/CS1002/Exercises/W08/W08Exercises`) with its main `.java` file in front, and prints the test command. VS Code's terminal starts there, and `stacscheck /cs/studres/CS1002/Exercises/W08/Tests` works from it |
| **browser** | Opens Firefox with exactly three tabs (StudRes CS1002, Outlook, MMS CS1002) and signs in with your University account. You only type the Authenticator number on your phone |

No sudo and no installs: it uses only Python's standard library and the
Firefox that's already on the PC. Lab PCs wipe everything outside
`~/Documents` when they restart, so it lives in `~/Documents` and you run it
again after each login.

## First time

```bash
cd ~/Documents
git clone https://github.com/JackRubiralta/cs_lab_start
cd cs_lab_start
./start            # creates .env the first time
gedit .env         # put your password after PASSWORD=, save
./start browser
```

No `git` on the PC? Download it instead:

```bash
cd ~/Documents
curl -sL https://github.com/JackRubiralta/cs_lab_start/archive/refs/heads/main.tar.gz | tar xz
mv cs_lab_start-main cs_lab_start
```

`.env` is only readable by you (`chmod 600`, re-checked on every run) and is
never committed (`.gitignore`). Nothing ever prints or logs the password.

## Every class

```bash
~/Documents/cs_lab_start/start
```

When Microsoft asks for the Authenticator code, the number appears in the
terminal (and as a notification). Type it into the app on your phone.

When everything worked, the terminal closes itself, so **only Firefox and
VS Code are left open**. If anything needs a look (e.g. no check-in session open yet), the
terminal stays so you can read why. `--keep-terminal` always keeps it.

| Command | |
|---|---|
| `./start` | everything, then closes the terminal if it all worked |
| `./start checkin` | just the check-in. `--wait 15` keeps retrying for 15 minutes if you're early (check-in opens 10 minutes before the class). `--manual` opens it for you to press the keys |
| `./start exercises` | just the new exercise files. `--dry-run` shows what it would copy |
| `./start vscode` | just VS Code on the newest week |
| `./start browser` | just Firefox. `--no-login` opens the tabs without signing in |
| `./start desktop` | just the taskbar and mouse |

## Updates

`./start` gets the newest version from GitHub first, with git if the folder
is a clone, otherwise by downloading it (15 s at most; offline it just runs
the copy it has). `.env` and `logs/` are never touched. `./start --no-update`
skips it. A copy older than 5 Nov 2026 can't update itself yet; once:

```bash
cd ~/Documents && curl -sL https://github.com/JackRubiralta/cs_lab_start/archive/refs/heads/main.tar.gz | tar xz && cp -r cs_lab_start-main/. cs_lab_start/ && rm -rf cs_lab_start-main
```

## Where the exercise files go

The code goes into the folder `stacscheck` expects, directly under the week,
with the sheet next to it:

```
~/Documents/CS1002/Exercises/W07/
    W07Exercises.html          the sheet (opens with its css)
    W07Exercises/
        W07Exercises.java      starter code: write your answers here
```

Test from the week folder. `./start` prints the newest week's command:

```bash
cd ~/Documents/CS1002/Exercises/W07
stacscheck /cs/studres/CS1002/Exercises/W07/Tests
```

Starter zips (W01, W02) are unpacked the same way. Weeks with no starter
code (W03) get an empty `W03Exercises/` folder to put your files in. The
`Tests` folders are not copied; `stacscheck` reads them straight from
`/cs/studres`.

## How the check-in works

`lab-checkin` is a full-screen terminal program (Rust, ratatui). It redraws
only the characters that change and keeps animating a spinner and a clock,
so its raw output never contains whole words like `CHECK-IN RECORDED`. That
is why the first version got stuck. `vtscreen.py` (stdlib, ~200 lines)
rebuilds the screen cell by cell, the way a terminal would, and answers the
terminal questions the program may ask. The driver then reads the screen
title and presses what a person would:

| Screen | Key |
|---|---|
| ELIGIBLE SESSIONS | Enter |
| CONFIRM CHECK-IN (“Check in as jrk25?”) | `y` |
| CHECK-IN RECORDED | `q` |
| NO ELIGIBLE SESSION | `q` (or `r` every 30 s with `--wait`) |
| CHECK-IN FAILED | `r` twice if it's a temporary error, then `q` |

A key that doesn't land is pressed again (up to 3 times). An unknown screen,
keys that never land, or a run over the time limit → it opens the real
check-in in your terminal instead. Each run saves what the screen showed to
`logs/checkin-<date>-<time>.out` (last 30 kept). If something goes wrong in
a class, email yourself that file.

## How the sign-in works

Firefox is started with `--marionette`, its built-in remote control. That's
why the address bar shows a robot icon and stripes. `marionette.py` (about
150 lines) talks to it over a local socket. StudRes and MMS go through
`login.st-andrews.ac.uk`, which hands over to Microsoft's sign-in page.
After the first sign-in, Outlook and MMS reuse the same session. The script
handles the email, password, the Authenticator number, "Pick an account",
the sign-in method choice and "Stay signed in?". If the password page comes
back a second time, it stops instead of retrying, so a wrong `.env` can't
lock your account.

If Firefox is already open without remote control, it opens the three tabs
in it without signing in. Close Firefox and run `./start browser` for the
automatic sign-in.

If a page check takes more than 20 seconds (or Firefox's first start takes
more than 2 minutes), that try counts as a miss and the script moves on, so it
can never hang. Each site gets 5 minutes to sign in. An Authenticator request
you ignore or deny is reported as such.

## Tests

```bash
cd tests && python3 -m unittest test_exercises test_checkin test_signin   # 28 tests, ~3 min
tests/vm_scenarios.sh /path/to/copy/of/CS1002/Exercises   # 21 situation checks, GNOME desktop
```

- `test_exercises`: layout, zips, never overwriting, unreadable files, name clashes.
- `test_checkin`: `tests/fake_lab_checkin.py` behaves like the real check-in
  (checked against the real binary): same screens, only changed cells
  redrawn, a spinner and a ticking clock. Modes `one`, `list`, `none`,
  `fail`, `slow`, `hang`, `crash`, `deaf` (loses keys) and `unknown`.
  `tests/real_checkin_failed.out` is a recording of the real binary's own
  screen, replayed through `vtscreen.py`. The real check-in itself only
  works on a lab PC with your Kerberos login.
- `test_signin`: a fake Firefox that never answers, answers slowly, or sits
  on an ignored Authenticator request. The sign-in must always give up in time.
- `vm_scenarios.sh`: Firefox already open, fresh profile, a second run, Firefox
  closed mid sign-in, Ctrl-C, `.env` permissions, a run from a real desktop
  terminal, and the terminal closing (or staying) at the end.

Tested on AlmaLinux 9.8 (GNOME 40, gnome-terminal, window list) and 10.2
(GNOME 49, Ptyxis, Dash to Dock), including real sign-ins with Microsoft
Authenticator.

Settings are at the top of `lab_start.py`: the URLs (MMS includes the
semester, `2026_7/S1`), the pinned apps and the mouse speed (`-0.5`, where
GNOME's range is -1 to 1 and 0 is the default).

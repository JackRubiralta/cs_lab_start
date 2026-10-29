# cs_lab_start

One command that sets up a St Andrews CS lab PC (AlmaLinux, GNOME) for an
exercise class:

| Step | What it does |
|---|---|
| **desktop** | Keeps the taskbar always shown, pins Firefox, VS Code, Terminal and Files, and sets the mouse to half speed |
| **checkin** | Runs the attendance check-in `/cs/studres/ct/lab-checkin`. It selects the open session, presses `y`, then `q`, so no terminal is left open |
| **exercises** | Copies every CS1002 exercise week from `/cs/studres/CS1002/Exercises` into `~/Documents/CS1002/Exercises`. **Never replaces a file that's already there**, so your answers are safe and only new weeks or missing files are added |
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

`.env` is only readable by you (`chmod 600`, re-checked on every run) and is
never committed (`.gitignore`). Nothing ever prints or logs the password.

## Every class

```bash
~/Documents/cs_lab_start/start
```

When Microsoft asks for the Authenticator code, the number appears in the
terminal (and as a notification). Type it into the app on your phone.

| Command | |
|---|---|
| `./start` | everything |
| `./start checkin` | just the check-in. `--wait 15` keeps retrying for 15 minutes if you're early (check-in opens 10 minutes before the class) |
| `./start exercises` | just the new exercise files. `--dry-run` shows what it would copy |
| `./start browser` | just Firefox. `--no-login` opens the tabs without signing in |
| `./start desktop` | just the taskbar and mouse |

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

## Tests

```bash
python3 -m unittest discover tests          # exercise copier
FAKE_CHECKIN_MODE=list CS_LAB_CHECKIN=$PWD/tests/fake_lab_checkin.py ./start checkin
```

`tests/fake_lab_checkin.py` draws the same screens as the real check-in
(text taken from the binary). It's used for testing off-site, because the
real one only works on a lab PC with your Kerberos login. The modes are
`one`, `list`, `none` and `fail`.

Settings are at the top of `lab_start.py`: the URLs (MMS includes the
semester, `2026_7/S1`), the pinned apps and the mouse speed (`-0.5`, where
GNOME's range is -1 to 1 and 0 is the default).

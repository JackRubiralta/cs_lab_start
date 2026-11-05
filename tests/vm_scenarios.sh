#!/bin/bash
# Situation tests for a GNOME test machine (run inside the desktop session, not on a lab PC):
#   tests/vm_scenarios.sh /path/to/a/copy/of/CS1002/Exercises
# None of them signs in: the browser checks use --no-login or a made-up email.
cd "$(dirname "$0")/.." || exit 1
STUDRES=${1:?give a copy of CS1002/Exercises}
FAKE=$PWD/tests/fake_lab_checkin.py
pass=0 fail=0
check() { if eval "$2"; then echo "PASS  $1"; pass=$((pass+1)); else echo "FAIL  $1"; fail=$((fail+1)); fi; }
ff_pids() { pgrep -u "$(id -u)" -x 'firefox|firefox-bin' ; }
stop_ff() { pkill -u "$(id -u)" -x firefox; for _ in $(seq 20); do ff_pids >/dev/null || return 0; sleep 0.5; done; pkill -9 -u "$(id -u)" -x firefox; sleep 1; }

echo "== unit tests ($(python3 --version))"
(cd tests && python3 -m unittest -q test_exercises test_checkin >/tmp/unit.log 2>&1)
check "unit tests" "tail -1 /tmp/unit.log | grep -q OK"

echo "== .env permissions get fixed"
cp .env /tmp/env.keep 2>/dev/null
chmod 644 .env 2>/dev/null || { printf 'EMAIL=x\nPASSWORD=\n' > .env; chmod 644 .env; }
python3 -c 'import lab_start; lab_start.load_env()'
check ".env back to 600" '[ "$(stat -c %a .env)" = 600 ]'

echo "== Firefox already open without remote control"
stop_ff
setsid -f firefox about:blank >/dev/null 2>&1; sleep 6
out=$(./start browser --no-login 2>&1)
check "falls back to opening tabs" 'grep -q "already open without remote control" <<<"$out"'
sleep 4
check "Firefox still running" 'ff_pids >/dev/null'

echo "== fresh Firefox, tabs only"
stop_ff; rm -rf ~/.mozilla
out=$(./start browser --no-login 2>&1)
check "browser ok" 'grep -qE "browser +ok" <<<"$out"'
check "Firefox survives the script" 'sleep 3; ff_pids >/dev/null'

echo "== second run reuses the same Firefox"
n1=$(ff_pids | wc -l)
out=$(./start browser --no-login 2>&1)
check "second run ok" 'grep -qE "browser +ok" <<<"$out"'
check "no second Firefox" '[ "$(ff_pids | wc -l)" = "$n1" ]'

echo "== Firefox closed while signing in"
stop_ff
printf 'EMAIL=nobody@example.invalid\nPASSWORD=x\n' > .env; chmod 600 .env
( sleep 9; pkill -u "$(id -u)" -x firefox ) &
out=$(timeout 120 ./start browser 2>&1)
check "reported, no traceback" '! grep -q Traceback <<<"$out" && grep -qE "browser +needs a look" <<<"$out"'
[ -f /tmp/env.keep ] && cp /tmp/env.keep .env && chmod 600 .env

echo "== Ctrl-C during the check-in"
out=$(CS_LAB_CHECKIN=$FAKE FAKE_CHECKIN_MODE=hang timeout --preserve-status -s INT 5 ./start checkin 2>&1); code=$?
check "stops cleanly (exit 130)" '[ $code = 130 ] && grep -q "stopped (Ctrl-C)" <<<"$out"'
check "no check-in left running" '! pgrep -f fake_lab_checkin >/dev/null'

echo "== whole run, twice (second must change nothing)"
rm -rf /tmp/scen-ex
export CS_LAB_STUDRES=$STUDRES CS_LAB_EXERCISES=/tmp/scen-ex CS_LAB_CHECKIN=$FAKE FAKE_CHECKIN_MODE=one
out=$(./start desktop checkin exercises 2>&1)
check "all parts ok" '! grep -q "needs a look" <<<"$out"'
before=$(find /tmp/scen-ex -type f -exec md5sum {} + | sort)
echo "my answers" >> /tmp/scen-ex/W07/W07Exercises/W07Exercises.java
out=$(./start exercises 2>&1)
check "second run copies nothing" 'grep -q "up to date" <<<"$out"'
check "my edit kept" 'tail -1 /tmp/scen-ex/W07/W07Exercises/W07Exercises.java | grep -q "my answers"'
check "mouse at half" '[ "$(gsettings get org.gnome.desktop.peripherals.mouse speed)" = "-0.5" ]'

echo "== run from a real desktop terminal, then close it"
stop_ff
TERMAPP=$(command -v gnome-terminal || command -v ptyxis || command -v kgx)
rm -f /tmp/term-run.log
if [ -n "$TERMAPP" ]; then
  case $TERMAPP in
    *gnome-terminal) "$TERMAPP" --title=labstart -- bash -c "./start desktop browser --no-login > /tmp/term-run.log 2>&1" ;;
    *ptyxis) "$TERMAPP" --new-window -- bash -c "./start desktop browser --no-login > /tmp/term-run.log 2>&1" ;;
    *) "$TERMAPP" -- bash -c "./start desktop browser --no-login > /tmp/term-run.log 2>&1" ;;
  esac
  for _ in $(seq 90); do grep -q "== Done" /tmp/term-run.log 2>/dev/null && break; sleep 1; done
  check "terminal run finished ok" '! grep -q "needs a look" /tmp/term-run.log && grep -q "== Done" /tmp/term-run.log'
  sleep 3
  check "Firefox stays after the terminal closed" 'ff_pids >/dev/null'
else
  echo "SKIP  no terminal app found"
fi

echo "== the terminal closes itself after a full run that worked, stays open if not"
term_run() {   # $1 = token, $2 = extra env; runs a full ./start in a new terminal window
  local cmd="cd $PWD && $2 ./start --no-login; echo $1-still-open; exec bash"
  case $TERMAPP in
    *gnome-terminal) "$TERMAPP" -- bash -c "$cmd" ;;
    *ptyxis) "$TERMAPP" --new-window -- bash -c "$cmd" ;;
    *) "$TERMAPP" -- bash -c "$cmd" ;;
  esac
}
if [ -n "$TERMAPP" ]; then
  envs="CS_LAB_STUDRES=$STUDRES CS_LAB_EXERCISES=/tmp/scen-ex CS_LAB_CHECKIN=$FAKE"
  term_run TOKOK "$envs FAKE_CHECKIN_MODE=one"
  sleep 4; for _ in $(seq 60); do pgrep -f "./start --no-login" >/dev/null || break; sleep 1; done; sleep 4
  check "worked: terminal closed" '! pgrep -f "TOKOK-still-open" >/dev/null'
  term_run TOKFAIL "$envs FAKE_CHECKIN_MODE=none"
  sleep 4; for _ in $(seq 60); do pgrep -f "./start --no-login" >/dev/null || break; sleep 1; done; sleep 4
  check "check-in not open: terminal kept" 'pgrep -f "TOKFAIL-still-open" >/dev/null'
  pkill -f "TOKFAIL-still-open"
  check "Firefox still open" 'ff_pids >/dev/null'
fi

echo
echo "$pass passed, $fail failed"
[ $fail = 0 ]

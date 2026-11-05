"""A tiny terminal screen (stdlib only) for reading full-screen TUIs.

The School's check-in (a Rust ratatui/crossterm app) redraws only the cells
that changed, so its output stream never contains whole words like
"CHECK-IN RECORDED" once the screen has been drawn. Feeding the bytes into
this grid gives back the screen as a person would see it.

Handles what ratatui/crossterm emit: cursor moves (CSI H/f/A/B/C/D/G/d),
clears (CSI J/K/X), SGR colours (ignored), alternate screen, CR/LF/BS/TAB,
UTF-8 text. It also answers the terminal queries an app may wait on
(cursor position, device attributes, kitty keyboard flags) so nothing blocks.
"""
import re

_CSI = re.compile(rb"\x1b\[([0-9;:?<>=]*)([ -/]*)([@-~])")
_OSC = re.compile(rb"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_ESC2 = re.compile(rb"\x1b[()*+#][0-9A-Za-z]|\x1b[=>78DEHMNOZc\\]")


class Screen:
    def __init__(self, rows=40, cols=120):
        self.rows, self.cols = rows, cols
        self.grid = [[" "] * cols for _ in range(rows)]
        self.r = self.c = 0
        self.saved = (0, 0)
        self.pending = b""          # an escape sequence or UTF-8 char split across reads
        self.replies = []           # bytes to write back to the app (query answers)

    # ------------------------------------------------------------ public
    def feed(self, data):
        data = self.pending + data
        self.pending = b""
        i, n = 0, len(data)
        while i < n:
            b = data[i]
            if b == 0x1b:
                if i + 1 >= n:
                    self.pending = data[i:]
                    return
                nxt = data[i + 1]
                if nxt == 0x5b:                         # CSI
                    m = _CSI.match(data, i)
                    if not m:
                        if n - i < 64:
                            self.pending = data[i:]
                            return
                        i += 2
                        continue
                    self._csi(m.group(1).decode(), m.group(3).decode())
                    i = m.end()
                    continue
                if nxt == 0x5d:                         # OSC
                    m = _OSC.match(data, i)
                    if not m:
                        if n - i < 512:
                            self.pending = data[i:]
                            return
                        i += 2
                        continue
                    i = m.end()
                    continue
                m = _ESC2.match(data, i)
                if m:
                    s = m.group(0)
                    if s == b"\x1b7":
                        self.saved = (self.r, self.c)
                    elif s == b"\x1b8":
                        self.r, self.c = self.saved
                    elif s == b"\x1bc":
                        self.clear()
                    i = m.end()
                    continue
                if n - i < 3:
                    self.pending = data[i:]
                    return
                i += 2
                continue
            if b == 0x0d:
                self.c = 0
            elif b in (0x0a, 0x0b, 0x0c):
                self.r = min(self.rows - 1, self.r + 1)
            elif b == 0x08:
                self.c = max(0, self.c - 1)
            elif b == 0x09:
                self.c = min(self.cols - 1, (self.c // 8 + 1) * 8)
            elif b < 0x20 or b == 0x7f:
                pass
            else:
                # one UTF-8 character
                ln = 1 if b < 0x80 else 2 if b >> 5 == 0b110 else 3 if b >> 4 == 0b1110 else 4
                if i + ln > n:
                    self.pending = data[i:]
                    return
                ch = data[i:i + ln].decode("utf-8", "replace")
                self._put(ch)
                i += ln
                continue
            i += 1

    def text(self):
        """The whole screen, one line per row, trailing spaces removed."""
        return "\n".join("".join(row).rstrip() for row in self.grid)

    def flat(self):
        """The screen as one line, box drawing removed and spaces squeezed (for matching)."""
        t = re.sub(r"[─-╿▀-▟⠀-⣿]", " ", self.text())
        return re.sub(r"\s+", " ", t)

    def take_replies(self):
        out, self.replies = b"".join(self.replies), []
        return out

    def clear(self):
        self.grid = [[" "] * self.cols for _ in range(self.rows)]

    # ----------------------------------------------------------- private
    def _put(self, ch):
        if self.c >= self.cols:
            self.c = 0
            self.r = min(self.rows - 1, self.r + 1)
        self.grid[self.r][self.c] = ch
        self.c += 1

    def _csi(self, params, final):
        priv = params[:1] if params[:1] in ("?", "<", ">", "=") else ""
        nums = [int(x) if x.isdigit() else 0 for x in re.split(r"[;:]", params.lstrip("?<>="))] if params.lstrip("?<>=") else []

        def p(k, default):
            return nums[k] if len(nums) > k and nums[k] else default

        if priv == "?":
            if final == "u":                    # kitty keyboard query: "not supported" = no reply
                return
            if final in "hl" and p(0, 0) in (1049, 47, 1047):
                self.clear()
                self.r = self.c = 0
            return
        if priv == ">" and final == "c":        # secondary device attributes
            self.replies.append(b"\x1b[>1;10;0c")
            return
        if priv:
            return
        if final in "Hf":
            self.r = min(self.rows - 1, p(0, 1) - 1)
            self.c = min(self.cols - 1, p(1, 1) - 1)
        elif final == "A":
            self.r = max(0, self.r - p(0, 1))
        elif final in "Be":
            self.r = min(self.rows - 1, self.r + p(0, 1))
        elif final in "Ca":
            self.c = min(self.cols - 1, self.c + p(0, 1))
        elif final == "D":
            self.c = max(0, self.c - p(0, 1))
        elif final == "E":
            self.r = min(self.rows - 1, self.r + p(0, 1)); self.c = 0
        elif final == "F":
            self.r = max(0, self.r - p(0, 1)); self.c = 0
        elif final in "G`":
            self.c = min(self.cols - 1, p(0, 1) - 1)
        elif final == "d":
            self.r = min(self.rows - 1, p(0, 1) - 1)
        elif final == "J":
            mode = p(0, 0) if nums else 0
            if mode in (2, 3):
                self.clear()
            elif mode == 0:
                self.grid[self.r][self.c:] = [" "] * (self.cols - self.c)
                for r in range(self.r + 1, self.rows):
                    self.grid[r] = [" "] * self.cols
            elif mode == 1:
                for r in range(self.r):
                    self.grid[r] = [" "] * self.cols
                self.grid[self.r][:self.c + 1] = [" "] * (self.c + 1)
        elif final == "K":
            mode = p(0, 0) if nums else 0
            row = self.grid[self.r]
            if mode == 0:
                row[self.c:] = [" "] * (self.cols - self.c)
            elif mode == 1:
                row[:self.c + 1] = [" "] * (self.c + 1)
            else:
                self.grid[self.r] = [" "] * self.cols
        elif final == "X":
            k = p(0, 1)
            row = self.grid[self.r]
            row[self.c:self.c + k] = [" "] * len(row[self.c:self.c + k])
        elif final == "n" and p(0, 0) == 6:     # cursor position report
            self.replies.append(b"\x1b[%d;%dR" % (self.r + 1, self.c + 1))
        elif final == "n" and p(0, 0) == 5:     # status report: OK
            self.replies.append(b"\x1b[0n")
        elif final == "c":                      # primary device attributes
            self.replies.append(b"\x1b[?62;22c")
        elif final == "s":
            self.saved = (self.r, self.c)
        elif final == "u":
            self.r, self.c = self.saved
        # m (SGR), r (scroll region), t, q ... ignored

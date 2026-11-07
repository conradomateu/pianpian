"""Problem reports: what went wrong in plain words, a short code, and details that are safe to share.

A failed job's log is matched against the failures we know (explain), and the page shows the hint.
Report opens GitHub's bug form (.github/ISSUE_TEMPLATE/bug.yml), sending the prefilled details to
GitHub when the link opens; publishing the issue requires Submit. Before building the link, redact()
takes out the home folder, the user name, the library's folder names, e-mail addresses, the path and
query of every link (they can carry a session or say what you watch) and the transcript lines
(the video's words). Standard library only.
"""
import getpass
import platform
import re
import subprocess
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import engine  # standard library only too: WINDOWS, the one platform check on the app side

REPO = "conradomateu/pianpian"                          # where reports go, and where releases come from
# (code, pattern in the log, what to do): the first match from the end of the log wins
KNOWN = [
    # 412 is Bilibili's anti-bot check: it comes and goes per connection (yt-dlp issues #14830, #16962, #17605)
    ("DL-BLOCKED", r"HTTP Error 412|Precondition Failed|-412|request was banned|HTTP Error 429|Too Many Requests",
     "The site refused the request. Bilibili does this at random to connections it finds suspicious, and Pianpian already tried three times. "
     "Wait a few minutes and try again; picking the browser you use for Bilibili, under options, often helps."),
    ("DL-LOGIN", r"login required|Sign in to confirm|requires? (a )?log ?in|members[- ]only|大会员",
     "The site wants a login. Under options, pick the browser you are logged in with, then try again."),
    ("DL-REGION", r"geo.?restrict|not available in your (country|region)|only available (for|in)\b|所在地区|仅限",
     "This video is limited to some countries (many Bilibili shows are only for mainland China). Pianpian can't change that."),
    ("DL-NOFORMATS", r"No video formats found|Requested format is not available",
     "No video could be found to download. Often it is a members-only or region-limited episode: picking your browser under options, "
     "if you are logged in there, sometimes fixes it."),
    ("DL-COOKIES", r"could not find .* cookies database|Failed to decrypt|cookies from browser",
     "Couldn't read that browser's login. Quit the browser and try again, or pick another one."),
    ("DL-UNSUPPORTED", r"Unsupported URL", "That link isn't a video page Pianpian can download."),
    ("DL-UNAVAILABLE", r"Video unavailable|This video is private|has been removed|HTTP Error 404",
     "The video isn't available (private, removed, or blocked where you are)."),
    ("DL-SITE-CHANGED", r"Unable to extract|nsig extraction failed|please report this issue on .*yt-dlp",
     "The site changed and the downloader needs an update. Update it, then try again."),
    ("NET", r"Temporary failure in name resolution|nodename nor servname|Network is unreachable|timed? ?out|"
            r"Connection (reset|refused)|URLError|SSL: ",
     "A network problem. Check the connection and try again: downloads carry on where they stopped."),
    ("DISK-FULL", r"No space left on device", "The disk is full. Free some space and try again."),
    # before MODEL-DOWNLOAD: its "checksum does not match" would otherwise claim a failed runtime .zip
    ("RUNTIME-DOWNLOAD", r"could not download the GPU runtime|no source served \S*\.zip|\S*\.zip: .*checksum does not match",
     "The GPU runtime (whisper.cpp / llama.cpp) didn't download completely. Try again: it carries on where it stopped."),
    ("MODEL-DOWNLOAD", r"could not download .*it resumes|checksum does not match",
     "A model didn't download completely. Try again: it carries on where it stopped."),
    ("MEMORY", r"Killed: 9|MemoryError|\[METAL\].*(failed|out of memory)|Insufficient Memory|out of memory",
     "The computer ran out of memory. Close other apps and try again."),
    ("TOOL-MISSING", r"No such file or directory: '(ffmpeg|ffprobe|swift|uv)'|could not find (ffmpeg|ffprobe)|"
                     r"FileNotFoundError:.*(ffmpeg|ffprobe|uv|whisper-cli|llama-server)",
     "A tool the pipeline needs is missing. Run the setup again; if it keeps happening, please report it."),
    ("ENGINE", r"ModuleNotFoundError|No module named|engine (is )?not installed",
     "The engine is missing a part. Run the setup again from the status menu."),
    ("VIDEO-FILE", r"moov atom not found|Invalid data found when processing input|Error opening input",
     "The video file couldn't be read: it may be damaged, or in a format ffmpeg can't open."),
]
# MLX ([00:01.840 --> …] text) and whisper.cpp ([00:00:01.840 --> …] text) print a cue per line; the same without the
# bracket, or an SRT timing (00:00:01,840 --> …), is never an error line either
TRANSCRIPT = re.compile(r"^\s*\[?(?:\d+:)?\d\d:\d\d[.:,]\d\d\d? --> ")
SRT_TIMING = re.compile(r"^\s*\d\d:\d\d:\d\d[,.]\d{3} --> \d\d:\d\d:\d\d[,.]\d{3}\s*$")   # an echoed .srt: text on the next lines
# what ends such a cue's text early: a log line (ERROR: …, RuntimeError: …, a traceback, [tool] …, $ command).
# shortcut: an English subtitle shaped like one ("Note: …") stays in the report; nothing echoes a .srt today
LOG_LINE = re.compile(r"^\s*(?:\[|\$ |Traceback|File \")|^\S+: |(?:Error|Exception|Warning)\b")
URL = re.compile(r"https?://[^\s'\"<>]+")
# first path words that only say what kind of page it is (never a person or a title)
KIND = {"video", "bangumi", "watch", "shorts", "live", "play", "embed", "playlist", "list", "cheese", "medialist", "s", "e"}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _shape(m) -> str:
    """A link as its kind only: https://www.bilibili.com/bangumi/…?spm_id_from=…&p=…  (the site, the kind of page and
    the names of the parameters, never the video or the values). That is enough to see which link shapes fail."""
    u = urlsplit(m[0])
    segs = [s for s in u.path.split("/") if s]
    path = (f"/{segs[0]}/…" if len(segs) > 1 and segs[0] in KIND else "/…") if segs else ""
    names = [q.split("=")[0] for q in u.query.split("&") if q][:8]
    return f"{u.scheme}://{u.netloc}{path}" + ("?" + "&".join(f"{n}=…" for n in names) if names else "")


def explain(lines: list[str]) -> dict | None:
    """{code, hint} for the last known failure in a log, else None."""
    for line in reversed(lines[-120:]):
        for code, pattern, hint in KNOWN:
            if re.search(pattern, line, re.I):
                return {"code": code, "hint": hint}
    return None


def _forms(path) -> list[str]:
    """The ways a log writes one folder: escaped backslashes (exceptions, command lists, JSON in them), as given, with forward
    slashes (as_posix, repr of a WindowsPath, ffmpeg) and inside a file:/// link. Longest first."""
    s = str(path)
    posix = s.replace("\\", "/")
    return list(dict.fromkeys([s.replace("\\", "\\" * 4), s.replace("\\", "\\\\"), s, posix, quote(posix, safe="/:"), posix.replace(" ", "%20")]))


def _short(name: str) -> str | None:
    """The 8.3 short form Windows may write for a long folder name (Wang Wei -> WANGWE~1), ASCII names only.
    shortcut: the pattern is the usual one, not read from the disk (GetShortPathNameW); non-ASCII names get
    hashed short names it misses. Not tested on Windows."""
    base = re.sub(r"[ .]", "", name)
    return base[:6] if base.isascii() and (len(name) > 8 or " " in name) else None


def _entries(library) -> list[str]:
    """The names a log can use for the library's videos: folder and file names, file names without the extension,
    and the titles in title.txt. Longest first, so a name inside a longer one doesn't leave the rest behind."""
    names = set()
    try:
        for p in Path(library).iterdir() if library else ():
            names |= {p.name, p.stem if p.is_file() else p.name.removesuffix("_study")}
            try:
                names.add((p / "title.txt").read_text(encoding="utf-8").strip())
            except OSError:
                pass
    except OSError:                                           # no library (yet), or one we can't read
        pass
    return sorted((n for n in names if len(n) >= 2 and not n.startswith(".")), key=len, reverse=True)


def redact(text: str, library: Path | None = None) -> str:
    home, user = str(Path.home()), getpass.getuser()
    flags = re.I if engine.WINDOWS else 0                     # Windows paths ignore case: C:\Users = c:\users
    if engine.WINDOWS and len(user) > 2 and (short := _short(user)):
        text = re.sub(rf"\b{re.escape(short)}~\d+", user.replace("\\", "\\\\"), text, flags=re.I)   # then the long forms below match
    lines, cue = [], 0
    for ln in text.splitlines():
        if TRANSCRIPT.match(ln):
            cue = 3 if SRT_TIMING.match(ln) else 0            # a study track has at most 3 lines (zh, pinyin, en)
        elif cue and not re.fullmatch(r"\s*\d+\s*", ln) and not LOG_LINE.search(ln):   # up to the next cue or log line
            cue -= 1
        else:
            cue = 0
            lines.append(ln)
    text = "\n".join(ln for ln in lines if not re.search(r"cookie|SESSDATA|Authorization", ln, re.I) or "cookies from browser" in ln)
    if library:
        # Spaces/quotes make the path's end ambiguous: hide the rest of its line, including later diagnostics.
        for prefix in _forms(library):
            text = re.sub(re.escape(prefix) + r"(?:[\\/]|%5C|%2F)+[^\r\n]*", "<library>/<video>", text, flags=flags)
            text = re.sub(re.escape(prefix), "<library>", text, flags=flags)
    for form in _forms(home):
        text = re.sub(re.escape(form), "~", text, flags=flags)
    if len(user) > 2:
        for form in dict.fromkeys([user, quote(user), re.sub(r"[ ._-]", "", user)]):   # Wang Wei, Wang%20Wei, WangWei
            text = re.sub(rf"\b{re.escape(form)}\b", "<user>", text, flags=flags)
    text = URL.sub(_shape, text)                              # first: a folder named by its video id would break the shape
    if names := _entries(library):                            # a video named on its own, without the library in front
        text = re.sub(r"(?<!<)(?:" + "|".join(map(re.escape, names)) + r")(?!>)", "<video>", text, flags=flags)
    return EMAIL.sub("<email>", text)


def system() -> str:
    """Machine, chip and OS version: enough to reproduce, nothing personal."""
    if engine.WINDOWS:
        return " · ".join(x for x in (platform.platform(), platform.machine(),
                                      platform.processor() or platform.uname().processor) if x)
    def sysctl(key):
        try:
            return subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=5).stdout.strip()
        except OSError:
            return ""
    mem = sysctl("hw.memsize")
    return " · ".join(x for x in (sysctl("hw.model"), sysctl("machdep.cpu.brand_string"),
                                  f"{int(mem) // 2**30} GB" if mem.isdigit() else "",
                                  f"macOS {platform.mac_ver()[0]}" if platform.mac_ver()[0] else platform.platform()) if x)


def issue_url(repo: str, title: str, code: str, details: str, system_line: str, limit: int = 7000) -> str:
    """GitHub's new-issue page with the bug form filled in. Long details lose their oldest lines to fit the URL."""
    lines = details.splitlines()
    while True:
        query = urlencode({"template": "bug.yml", "title": title, "code": code, "details": "\n".join(lines), "system": system_line})
        if len(query) <= limit or len(lines) <= 5:
            return f"https://github.com/{repo}/issues/new?{query}"
        lines = lines[:4] + ["…"] + lines[6:]                # keep the summary at the top, drop the oldest log lines

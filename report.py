"""Problem reports: what went wrong in plain words, a short code, and details that are safe to share.

A failed job's log is matched against the failures we know (explain), and the page shows the hint.
Report opens GitHub's bug form (.github/ISSUE_TEMPLATE/bug.yml) filled in with the details below;
nothing is sent until the person reads it there and presses Submit. Before that, redact() takes
out the home folder, the user name, the library's folder names, e-mail addresses, the path and
query of every link (they can carry a session or say what you watch) and the transcript lines
(the video's words). Standard library only.
"""
import getpass
import platform
import re
import subprocess
from pathlib import Path
from urllib.parse import urlencode, urlsplit

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
    ("MODEL-DOWNLOAD", r"could not download .*it resumes|checksum does not match",
     "A model didn't download completely. Try again: it carries on where it stopped."),
    ("MEMORY", r"Killed: 9|MemoryError|\[METAL\].*(failed|out of memory)|Insufficient Memory|out of memory",
     "The computer ran out of memory. Close other apps and try again."),
    ("TOOL-MISSING", r"No such file or directory: '(ffmpeg|ffprobe|swift|uv)'",
     "A tool the pipeline needs is missing. Run the setup again; if it keeps happening, please report it."),
    ("ENGINE", r"ModuleNotFoundError|No module named|engine (is )?not installed",
     "The engine is missing a part. Run the setup again from the status menu."),
    ("VIDEO-FILE", r"moov atom not found|Invalid data found when processing input|Error opening input",
     "The video file couldn't be read: it may be damaged, or in a format ffmpeg can't open."),
]
TRANSCRIPT = re.compile(r"^\s*\[\d\d:\d\d[.:]\d\d\d? --> ")                 # Whisper prints what it hears
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


def redact(text: str, library: Path | None = None) -> str:
    home, user = str(Path.home()), getpass.getuser()
    lines = [ln for ln in text.splitlines() if not TRANSCRIPT.match(ln)]
    text = "\n".join(ln for ln in lines if not re.search(r"cookie|SESSDATA|Authorization", ln, re.I) or "cookies from browser" in ln)
    if library:
        text = re.sub(re.escape(str(library)) + r"[\\/][^\\/\s'\"]+", "<library>/<video>", text)
        text = text.replace(str(library), "<library>")
    text = text.replace(home, "~")
    text = re.sub(rf"\b{re.escape(user)}\b", "<user>", text) if len(user) > 2 else text
    text = URL.sub(_shape, text)
    return EMAIL.sub("<email>", text)


def system() -> str:
    """Machine, chip and OS version: enough to reproduce, nothing personal."""
    if platform.system() == "Windows":
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

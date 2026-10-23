"""Links people paste, made ready for yt-dlp. Standard library only.

    extract_url("【标题-哔哩哔哩】 https://b23.tv/AbCdEfG 复制链接")    -> "https://b23.tv/AbCdEfG"
    clean_url("https://www.bilibili.com/video/BV1xx/?p=2&spm_id_from=333.337&vd_source=ab")
                                                                       -> "https://www.bilibili.com/video/BV1xx/?p=2"
    normalize(text, resolve=True)    # all of it, and short links followed one hop at a time

What real links look like (checked against yt-dlp 2026.10.21's own URL patterns, 23 Oct 2026):
- Sharing from a site's button gives text with the link inside ("【title】 https://…"), not a bare link.
- The address bar and the share button add tracking parameters (spm_id_from, vd_source, share_source,
  si, utm_…). yt-dlp ignores them when it recognises the link, but its Bilibili episode extractor sends
  the whole link to Bilibili's web server.
- Parameters that choose the video must stay: ?p=4 (a part of a multi-part video), ?t= (time), v= and
  list= on YouTube, favlist?fid= and ?sid= on Bilibili. So this removes only parameters it knows are
  tracking, never "everything after the ?".
- m.bilibili.com (phones) is not recognised by yt-dlp; www.bilibili.com is.
- b23.tv and friends are short links to the real page. yt-dlp does not follow them for Bilibili.
- Douyin links carry the video id as /share/video/<id> (where its short links lead) or ?modal_id=<id>
  (a profile page with a video open); yt-dlp only matches /video/<id>. Xiaohongshu links NEED their
  xsec_token parameter, so unknown parameters are always left alone.
"""
import re
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit, urlunsplit

# a link ends at whitespace, quotes, brackets or any CJK/full-width character (never part of a real link)
URL = re.compile(r"https?://[^\s　-〿＀-￯一-鿿<>\"'`]+", re.I)
ENDING = ".,;:!?)]}>'\""
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"

# short links that redirect to the real page
SHORT_HOSTS = {"b23.tv", "bili2233.cn", "bili22.cn", "bili33.cn", "v.douyin.com", "xhslink.com", "t.cn"}
# phone sites that yt-dlp's extractors don't match, and their desktop twin
DESKTOP = {"m.bilibili.com": "www.bilibili.com"}

# parameters that only say where you clicked or shared from
GENERIC_TRACKING = re.compile(r"(?i)^(utm_[a-z_]+|fbclid|gclid|dclid|igshid|mc_cid|mc_eid|_hsenc|_hsmi|ref_src|ref_url)$")
SITE_TRACKING = {
    "bilibili": {"spm_id_from", "from_spmid", "vd_source", "spm", "share_source", "share_medium", "share_plat", "share_session_id",
                 "share_tag", "share_from", "timestamp", "unique_k", "bbid", "buvid", "msource", "bsource", "seid", "plat_id",
                 "is_story_h5", "launch_id", "trackid", "from_source"},
    "youtube": {"si", "feature", "pp", "ab_channel", "app"},
}


# Douyin's video id appears in three places; yt-dlp only matches douyin.com/video/<id>
DOUYIN_HOSTS = {"douyin.com", "www.douyin.com", "iesdouyin.com", "www.iesdouyin.com"}
DOUYIN_ID = re.compile(r"/(?:share/)?video/(\d+)|(?:^|&)modal_id=(\d+)")


def site_of(host: str) -> str:
    if host == "bilibili.com" or host.endswith(".bilibili.com") or host in ("b23.tv", "bili2233.cn", "bili22.cn", "bili33.cn"):
        return "bilibili"
    if host in ("youtu.be", "youtube.com") or host.endswith(".youtube.com"):
        return "youtube"
    return ""


def extract_url(text: str) -> str | None:
    """The first link in pasted text (a bare link, or the text a Share button copies)."""
    m = URL.search(text or "")
    return m[0].rstrip(ENDING) if m else None


def clean_url(url: str) -> str:
    """The link without tracking parameters, and the phone site swapped for the desktop one."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port else ""
    host = DESKTOP.get(host, host)
    if host in DOUYIN_HOSTS and (m := DOUYIN_ID.search(parts.path) or DOUYIN_ID.search(parts.query)):
        return f"https://www.douyin.com/video/{m[1] or m[2]}"          # same video, the form yt-dlp recognises
    site = SITE_TRACKING.get(site_of(host), set())
    kept = [seg for seg in parts.query.split("&") if seg and not (seg.split("=", 1)[0] in site or GENERIC_TRACKING.match(seg.split("=", 1)[0]))]
    return urlunsplit((parts.scheme.lower(), host + port, parts.path, "&".join(kept), parts.fragment))


class _DontFollow(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None                                           # the redirect surfaces as an HTTPError we can read


def resolve_short(url: str, timeout: float = 8.0, hops: int = 4) -> str:
    """Follow a short link (b23.tv/…) to the page it points to, one redirect at a time. If anything goes
    wrong (offline, blocked, no redirect) the link is returned as it was: yt-dlp then tries it itself."""
    opener = urllib.request.build_opener(_DontFollow)
    for _ in range(hops):
        if (urlsplit(url).hostname or "").lower() not in SHORT_HOSTS:
            return url
        try:
            with opener.open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout):
                return url                                    # 200: it is the page itself
        except urllib.error.HTTPError as e:
            where = e.headers.get("Location") if e.code in (301, 302, 303, 307, 308) else None
            if not where:
                return url
            url = urljoin(url, where)
        except (OSError, ValueError):
            return url
    return url


def normalize(text: str, resolve: bool = False) -> str:
    """Pasted text -> a link yt-dlp can use. Raises ValueError when there is no link in it.
    resolve=True also follows short links (a network call: for the pipeline, not for the request handler)."""
    url = extract_url(text)
    if not url:
        raise ValueError("no link found")
    if resolve:
        url = resolve_short(url)
    return clean_url(url)

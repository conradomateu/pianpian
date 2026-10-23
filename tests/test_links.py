"""Pasted links: the shapes real people paste, and what must never be removed."""
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "pipeline")]
import links  # noqa: E402

BV = "https://www.bilibili.com/video/BV1bK411W797"


def test_tracking_goes_but_what_picks_the_video_stays():
    n = links.normalize
    assert n("https://www.bilibili.com/bangumi/play/ep2008926?spm_id_from=333.1007.partition_recommend.content.click") \
        == "https://www.bilibili.com/bangumi/play/ep2008926"
    assert n(BV + "?p=4&spm_id_from=333.337&vd_source=0a1b") == BV + "?p=4"              # part 4 of a multi-part video
    assert n("https://space.bilibili.com/84912/favlist?fid=1103407912&ftype=create&spm_id_from=333.1387") \
        == "https://space.bilibili.com/84912/favlist?fid=1103407912&ftype=create"        # these pages ARE the query
    assert n("https://youtu.be/dQw4w9WgXcQ?si=AbC&t=43") == "https://youtu.be/dQw4w9WgXcQ?t=43"
    assert n("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLx&pp=ygU&feature=shared&utm_source=a") \
        == "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLx"
    assert n("https://example.com/a?id=7&utm_medium=x&fbclid=y") == "https://example.com/a?id=7"   # generic trackers only
    assert n("https://example.com/a?spm_id_from=1") == "https://example.com/a?spm_id_from=1"        # site lists stay per site


def test_share_text_and_phone_links():
    n = links.normalize
    assert n("【克洛伊的生日聚会-哔哩哔哩】 https://www.bilibili.com/bangumi/play/ep2008926?spm_id_from=1") \
        == "https://www.bilibili.com/bangumi/play/ep2008926"
    assert n("【某视频】https://b23.tv/AbCdEfG复制此链接，打开B站") == "https://b23.tv/AbCdEfG"   # CJK text right after the link
    assert n("看这个 (https://www.bilibili.com/video/BV13x41117TL/)，很好") == "https://www.bilibili.com/video/BV13x41117TL/"
    assert n("https://m.bilibili.com/video/BV13x41117TL?share_source=copy_web") == "https://www.bilibili.com/video/BV13x41117TL"
    assert n("  https://www.bilibili.com/video/BV13x41117TL  ") == "https://www.bilibili.com/video/BV13x41117TL"


def test_no_link_is_an_error():
    for text in ("", "hello", "bilibili.com/video/BV1xx", "ftp://x"):
        try:
            links.normalize(text)
            raise AssertionError(f"{text!r} was accepted")
        except ValueError:
            pass


def test_short_links_are_followed_one_hop_at_a_time(monkeypatch):
    seen = []

    class Opener:
        def open(self, req, timeout):
            seen.append(req.full_url)
            hop = {"https://b23.tv/AbC": "https://b23.tv/xyz", "https://b23.tv/xyz": "https://m.bilibili.com/video/BV1?share_source=copy_web"}
            if req.full_url in hop:
                raise urllib.error.HTTPError(req.full_url, 302, "Found", {"Location": hop[req.full_url]}, None)
            raise AssertionError("must stop at a page that is not a short link")
    monkeypatch.setattr(links.urllib.request, "build_opener", lambda *a: Opener())
    assert links.normalize("https://b23.tv/AbC", resolve=True) == "https://www.bilibili.com/video/BV1"
    assert seen == ["https://b23.tv/AbC", "https://b23.tv/xyz"]


def test_a_short_link_that_cannot_be_followed_is_left_alone(monkeypatch):
    class Opener:
        def open(self, req, timeout):
            raise OSError("offline")
    monkeypatch.setattr(links.urllib.request, "build_opener", lambda *a: Opener())
    assert links.resolve_short("https://b23.tv/AbC") == "https://b23.tv/AbC"
    assert links.resolve_short("https://example.com/AbC") == "https://example.com/AbC"        # not a short-link host: no request


def test_douyin_ids_in_other_places_and_parameters_a_site_needs():
    n = links.normalize
    assert n("https://www.douyin.com/video/7123456789012345678") == "https://www.douyin.com/video/7123456789012345678"
    assert n("https://www.iesdouyin.com/share/video/7123456789012345678/?region=CN&mid=1&utm_source=copy") \
        == "https://www.douyin.com/video/7123456789012345678"
    assert n("https://www.douyin.com/user/MS4wLjAB?modal_id=7123456789012345678&from_tab_name=main") \
        == "https://www.douyin.com/video/7123456789012345678"
    assert n("https://www.douyin.com/user/MS4wLjAB") == "https://www.douyin.com/user/MS4wLjAB"       # no video id: left alone
    xhs = "https://www.xiaohongshu.com/explore/64a1b2c3d4e5f6a7b8c9d0e1?xsec_token=ABC&xsec_source=pc_feed"
    assert n(xhs) == xhs                                                                              # Xiaohongshu needs these

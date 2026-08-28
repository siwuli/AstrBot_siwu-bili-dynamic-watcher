"""bili_dynamic_watcher v2.0 核心模块单元测试（无需 AstrBot 环境）。

运行：
    python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PLUGIN_DIR)

import policy  # noqa: E402
import rss_feed  # noqa: E402
import wbi  # noqa: E402
import rules  # noqa: E402

# bili_api.py 内部使用相对导入（from . import wbi），测试时把它作为一个包导入
import types  # noqa: E402

_PKG = types.ModuleType("siwu_bili_plugin")
_PKG.__path__ = [_PLUGIN_DIR]
sys.modules["siwu_bili_plugin"] = _PKG

try:
    from siwu_bili_plugin.bili_api import (  # noqa: E402
        BiliAPIError,
        BiliDynamicClient,
        build_cookie_header,
    )
except ImportError as exc:
    BiliAPIError = None
    BiliDynamicClient = None
    build_cookie_header = None
    _SKIP_REASON = str(exc)
else:
    _SKIP_REASON = ""

RSS2_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>动态</title>
<item>
  <title><![CDATA[今天发布了新视频！]]></title>
  <link>https://t.bilibili.com/123456789</link>
  <guid>https://t.bilibili.com/123456789</guid>
  <pubDate>Tue, 28 Aug 2026 10:00:00 +0800</pubDate>
  <description><![CDATA[视频《测试》来了]]></description>
  <author><![CDATA[测试UP主]]></author>
</item>
<item>
  <title>第二条</title>
  <link>https://t.bilibili.com/987654321</link>
  <guid>https://t.bilibili.com/987654321</guid>
  <pubDate>Wed, 29 Aug 2026 12:30:00 +0800</pubDate>
  <description>第二条内容</description>
</item>
</channel></rss>"""

ATOM_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>微博</title>
  <entry>
    <id>https://weibo.com/1234567890/abc</id>
    <title>今天天气不错</title>
    <link href="https://weibo.com/1234567890/abc"/>
    <updated>2026-08-28T10:00:00+08:00</updated>
    <author><name>微博用户</name></author>
    <summary>今天天气不错，拍了一张照片</summary>
  </entry>
</feed>"""


class TestWbi(unittest.TestCase):
    def test_extract_key(self):
        self.assertEqual(
            wbi.extract_key(
                "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png"
            ),
            "7cd084941338484aae1ad9425b84077c",
        )
        self.assertEqual(wbi.extract_key(""), "")

    def test_mixin_key(self):
        mk = wbi.mixin_key("a" * 32, "b" * 32)
        self.assertEqual(len(mk), 32)
        self.assertTrue(mk.startswith("a" * 32))

    def test_sign_params_deterministic(self):
        p1 = wbi.sign_params({"foo": "114", "bar": "514"}, "k1" * 16, "k2" * 16, ts=1000)
        p2 = wbi.sign_params({"foo": "114", "bar": "514"}, "k1" * 16, "k2" * 16, ts=1000)
        self.assertEqual(p1, p2)
        self.assertEqual(p1["wts"], 1000)
        self.assertEqual(len(p1["w_rid"]), 32)

    def test_sign_params_filters(self):
        p = wbi.sign_params({"x": "a!'()*b", "y": ""}, "k1" * 16, "k2" * 16, ts=1)
        self.assertNotIn("y", p)
        self.assertTrue(all(ch not in "!'()*" for ch in p["x"]))

    def test_parse_nav_img_keys(self):
        data = {
            "code": 0,
            "data": {
                "wbi_img": {
                    "img_url": "https://i0.hdslb.com/bfs/wbi/aaa111.png",
                    "sub_url": "https://i0.hdslb.com/bfs/wbi/bbb222.png",
                }
            },
        }
        self.assertEqual(wbi.parse_nav_img_keys(data), ("aaa111", "bbb222"))
        self.assertEqual(wbi.parse_nav_img_keys({"data": {}}), (None, None))


class TestRssFeed(unittest.TestCase):
    def test_parse_rss2(self):
        entries = rss_feed.parse_feed(RSS2_XML)
        self.assertEqual(len(entries), 2)
        e = entries[0]
        self.assertEqual(e["guid"], "https://t.bilibili.com/123456789")
        self.assertEqual(e["title"], "今天发布了新视频！")
        self.assertEqual(e["author"], "测试UP主")
        self.assertGreater(e["pub_ts"], 0)

    def test_parse_atom(self):
        entries = rss_feed.parse_feed(ATOM_XML)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["link"], "https://weibo.com/1234567890/abc")
        self.assertEqual(e["author"], "微博用户")
        self.assertGreater(e["pub_ts"], 0)

    def test_parse_invalid(self):
        self.assertEqual(rss_feed.parse_feed("<not xml"), [])
        self.assertEqual(rss_feed.parse_feed(""), [])

    def test_pseudo_item(self):
        entries = rss_feed.parse_feed(RSS2_XML)
        item = rss_feed.pseudo_item(entries[0], "161775300")
        self.assertEqual(item["kind"], "rss")
        self.assertEqual(item["type"], "DYNAMIC_TYPE_RSS")
        self.assertEqual(item["modules"]["module_author"]["mid"], "161775300")
        self.assertEqual(len(item["id_str"]), 32)
        self.assertEqual(rss_feed.rss_seen_key(entries[0]["guid"]), "rss:" + item["id_str"])


class TestPolicy(unittest.TestCase):
    def test_effective_interval(self):
        self.assertEqual(policy.effective_interval(120, 0), 120)
        self.assertEqual(policy.effective_interval(120, 1), 240)
        self.assertEqual(policy.effective_interval(120, 10, cap=3600), 3600)

    def test_jittered_interval(self):
        for _ in range(50):
            iv = policy.jittered_interval(120, 1, 3600)
            self.assertGreaterEqual(iv, 240)
            self.assertLessEqual(iv, 240 + 240 * 0.2 + 1)

    def test_backoff_level(self):
        self.assertEqual(policy.next_backoff_level(0), 1)
        self.assertEqual(policy.next_backoff_level(7), 7)
        self.assertEqual(policy.reset_backoff_level(), 0)


@unittest.skipIf(build_cookie_header is None, "aiohttp 不可用: " + _SKIP_REASON)
class TestBiliApi(unittest.TestCase):
    def test_build_cookie_header(self):
        self.assertEqual(
            build_cookie_header("abc", "111", "222"),
            "SESSDATA=abc; buvid3=111; buvid4=222",
        )
        self.assertEqual(build_cookie_header("abc", ""), "SESSDATA=abc")

    def test_risk_error(self):
        err = BiliAPIError("风控", code=-352, risk=True)
        self.assertTrue(err.risk)
        err2 = BiliAPIError("过期", code=-101, risk=False)
        self.assertFalse(err2.risk)



DRAW_ITEM = {
    "id_str": "a1",
    "type": "DYNAMIC_TYPE_DRAW",
    "modules": {
        "module_dynamic": {
            "desc": {"text": "新图"},
            "major": {
                "draw": {
                    "items": [
                        {"src": "https://i0.hdslb.com/1.jpg"},
                        {"src": "https://i0.hdslb.com/2.jpg"},
                    ]
                }
            },
        }
    },
}

FORWARD_ITEM = {
    "id_str": "a2",
    "type": "DYNAMIC_TYPE_FORWARD",
    "orig": {
        "modules": {
            "module_dynamic": {
                "desc": {"text": "原动态内容"},
                "major": {"draw": {"items": [{"src": "https://i0.hdslb.com/orig.jpg"}]}},
            }
        }
    },
}

LOTTERY_ITEM = {
    "id_str": "a3",
    "type": "DYNAMIC_TYPE_WORD",
    "modules": {"module_dynamic": {"desc": {"text": "转发本条动态参与抽奖送周边！"}}},
}


class TestRules(unittest.TestCase):
    def test_item_images_draw(self):
        imgs = rules.item_images(DRAW_ITEM)
        self.assertEqual(imgs, ["https://i0.hdslb.com/1.jpg", "https://i0.hdslb.com/2.jpg"])

    def test_item_images_forward_orig(self):
        imgs = rules.item_images(FORWARD_ITEM)
        self.assertIn("https://i0.hdslb.com/orig.jpg", imgs)

    def test_item_images_rss(self):
        item = {
            "kind": "rss",
            "_rss": {
                "images": ["https://i0.hdslb.com/r1.jpg", "https://i0.hdslb.com/r2.jpg"]
            },
        }
        self.assertEqual(
            rules.item_images(item),
            ["https://i0.hdslb.com/r1.jpg", "https://i0.hdslb.com/r2.jpg"],
        )

    def test_forward_filter_default(self):
        ok, reason = rules.should_push(FORWARD_ITEM, {})
        self.assertFalse(ok)
        self.assertIn("转发", reason)
        # 配置关闭忽略后放行
        ok2, _ = rules.should_push(FORWARD_ITEM, {"bdw_ignore_forward": False})
        self.assertTrue(ok2)

    def test_lottery_filter_default(self):
        ok, reason = rules.should_push(LOTTERY_ITEM, {})
        self.assertFalse(ok)
        self.assertIn("抽奖", reason)
        ok2, _ = rules.should_push(LOTTERY_ITEM, {"bdw_ignore_lottery": False})
        self.assertTrue(ok2)

    def test_normal_word_push(self):
        item = {
            "id_str": "a4",
            "type": "DYNAMIC_TYPE_WORD",
            "modules": {"module_dynamic": {"desc": {"text": "普通动态"}}},
        }
        ok, reason = rules.should_push(item, {})
        self.assertTrue(ok)
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)

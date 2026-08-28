"""RSS 订阅源解析（纯标准库，可独立测试）。

用途：官方 B 站接口被风控（412 / -352）时的兜底，或直接作为 RSS 模式的数据源。

支持的源：
- RSSHub 哔哩哔哩动态：{base}/bilibili/user/dynamic/{uid}
- RSSHub 微博用户：{base}/weibo/user/{uid}（公共实例常需 cookie，建议自建）
- RSSWorker（Cloudflare Worker）、其他标准 RSS 2.0 / Atom 输出

模式约定：每个 UID 单独订阅一个 feed，feed 内全部条目都属于该账号，无需按
作者过滤；条目去重键取 guid/link 的 SHA-256 前 32 位并加 rss: 前缀。
"""

import email.utils
import hashlib
import re
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

ATOM_NS = "{http://www.w3.org/2005/Atom}"
_XML_DECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>", re.I)
_IMG_RE = re.compile(r"<img\s+[^>]*?src=[\"'][^\"']+[\"']", re.I)


def extract_html_images(html):
    """从 HTML 片段中提取 <img src> 列表。"""
    out = []
    for m in _IMG_RE.findall(html or ""):
        src = m.split('src=', 1)[-1].strip().strip('"').strip("'")
        if src and src not in out:
            out.append(src)
    return out


def rss_seen_key(guid):
    """RSS 条目的去重键（rss:<sha256 前 32 位>）。"""
    h = hashlib.sha256((guid or "").encode("utf-8")).hexdigest()[:32]
    return "rss:" + h


def _strip_cdata(text):
    return (text or "").strip()


def _parse_date(value):
    """把 RSS pubDate / Atom updated 解析为 unix 秒；失败返回 0。"""
    value = _strip_cdata(value)
    if not value:
        return 0
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _find(node, *names):
    """按多个候选标签名取文本。"""
    for name in names:
        el = node.find(name)
        if el is not None and (el.text or "").strip():
            return (el.text or "").strip()
    return ""


def _find_children(node):
    """返回 item（RSS 2.0 的 rss>channel>item）或 entry（Atom）子节点。"""
    # RSS 2.0：item 在 channel 下
    ch = None
    for c in list(node):
        if c.tag.rsplit("}", 1)[-1] == "channel":
            ch = c
            break
    if ch is not None:
        node = ch
    items = [c for c in list(node) if c.tag in ("item", ATOM_NS + "entry")]
    if items:
        return items
    # 兼容带命名空间前缀的 item
    for c in list(node):
        tag = c.tag.rsplit("}", 1)[-1]
        if tag == "item":
            items.append(c)
    return items


def parse_feed(xml_text):
    """解析 RSS 2.0 / Atom，返回条目列表：
    [{guid, link, title, description, author, pub_ts}, ...]
    """
    xml_text = _XML_DECL_RE.sub("", xml_text or "", count=1)
    if not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    return [_parse_entry(entry, root) for entry in _find_children(root)]


def _parse_entry(entry, root):
    is_atom = entry.tag == ATOM_NS + "entry"
    title = ""
    link = ""
    guid = ""
    desc = ""
    author = ""
    pub_ts = 0
    if is_atom:
        title = _find(entry, ATOM_NS + "title")
        link = _find(entry, ATOM_NS + "id")
        for ln in entry.findall(ATOM_NS + "link"):
            href = ln.get("href") or ""
            if href:
                link = href
                break
        guid = _find(entry, ATOM_NS + "id")
        desc = _find(entry, ATOM_NS + "summary", ATOM_NS + "content")
        au = entry.find(ATOM_NS + "author")
        if au is not None:
            author = _find(au, ATOM_NS + "name")
        pub = _find(entry, ATOM_NS + "published", ATOM_NS + "updated")
        pub_ts = _parse_date(pub) if pub else 0
    enclosure = ""
    if not is_atom:
        title = _find(entry, "title")
        link = _find(entry, "link")
        guid = _find(entry, "guid") or link
        desc = _find(entry, "description")
        author = _find(entry, "author", "{http://purl.org/dc/elements/1.1/}creator")
        pub_ts = _parse_date(_find(entry, "pubDate", "dc:date"))
        enc = entry.find("enclosure")
        if enc is not None:
            enclosure = str(enc.get("url") or "").strip()
    return {
        "guid": guid or link or title,
        "link": link,
        "title": title,
        "description": desc,
        "author": author,
        "pub_ts": pub_ts,
        "enclosure": enclosure,
        "images": extract_html_images(desc),
    }


def pseudo_item(entry, uid):
    """把 RSS 条目转换成与官方动态接口兼容的伪 item，供统一格式化/去重。

    关键字段：kind=rss、id_str=条目去重 id（哈希后的 guid/link）、
    modules.module_author.mid=uid 保证按 UID 过滤可用。
    """
    guid = str(entry.get("guid") or "")
    body = str(entry.get("description") or entry.get("title") or "").strip()
    return {
        "kind": "rss",
        "id_str": hashlib.sha256(guid.encode("utf-8")).hexdigest()[:32],
        "rss_guid": guid,
        "type": "DYNAMIC_TYPE_RSS",
        "modules": {
            "module_author": {
                "name": str(entry.get("author") or "").strip() or "动态",
                "mid": str(uid).strip(),
                "pub_ts": int(entry.get("pub_ts") or 0),
            },
            "module_dynamic": {"desc": {"text": body[:800]}, "major": {}},
        },
        "_rss": {
            "link": str(entry.get("link") or ""),
            "title": str(entry.get("title") or ""),
            "images": _rss_images(entry),
        },
    }


def _rss_images(entry):
    """条目的图片列表：enclosure 优先，其次 description 中的 <img>。"""
    imgs = []
    enc = str(entry.get("enclosure") or "").strip()
    if enc:
        imgs.append(enc)
    for u in (entry.get("images") or []):
        if u not in imgs:
            imgs.append(u)
    return imgs[:9]
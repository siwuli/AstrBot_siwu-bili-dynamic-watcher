"""推送规则与图片提取（纯标准库，可独立测试）。

- 图片：图文动态 major.draw.items[].src、视频封面、转发原动态图片、RSS 条目图片；
- 过滤：转发动态默认忽略；正文/原动态含抽奖关键词默认忽略，
  均可通过配置开关（bdw_ignore_forward / bdw_ignore_lottery / bdw_ignore_keywords）。
"""

DEFAULT_IGNORE_KEYWORDS = ["抽奖", "中奖", "开奖", "锦鲤", "转发抽奖"]

MAX_IMAGES = 9


def item_text(item):
    """汇总动态正文（含转发原动态正文/标题），用于关键词过滤。"""
    parts = []

    def collect(node):
        if not isinstance(node, dict):
            return
        modules = node.get("modules") or {}
        dyn = modules.get("module_dynamic") or {}
        desc = str((dyn.get("desc") or {}).get("text") or "").strip()
        if desc:
            parts.append(desc)
        major = dyn.get("major") or {}
        arch = major.get("archive") or {}
        if isinstance(arch, dict):
            title = str(arch.get("title") or "").strip()
            if title:
                parts.append(title)
        art = major.get("article") or {}
        if isinstance(art, dict):
            title = str(art.get("title") or "").strip()
            if title:
                parts.append(title)
        orig = node.get("orig")
        if isinstance(orig, dict):
            collect(orig)

    collect(item)
    # 去重保序
    return "\n".join(dict.fromkeys(parts))


def item_images(item, limit=MAX_IMAGES):
    """提取可随推送附带的图片 URL（图文/封面/转发原图/RSS 图），最多 limit 张。"""
    imgs = []

    def add(url):
        url = str(url or "").strip()
        if url and url not in imgs:
            imgs.append(url)

    if str(item.get("kind") or "") == "rss":
        for u in (item.get("_rss") or {}).get("images") or []:
            add(u)
        return imgs[:limit]

    def walk(node, depth=0):
        if not isinstance(node, dict) or depth > 2:
            return
        modules = node.get("modules") or {}
        dyn = modules.get("module_dynamic") or {}
        major = dyn.get("major") or {}
        draw = major.get("draw") or {}
        for it in draw.get("items") or []:
            if isinstance(it, dict):
                add(it.get("src"))
        arch = major.get("archive") or {}
        if isinstance(arch, dict):
            add(arch.get("pic"))
        orig = node.get("orig")
        if isinstance(orig, dict):
            walk(orig, depth + 1)

    walk(item)
    return imgs[:limit]


def should_push(item, config) -> tuple[bool, str]:
    """判断是否推送。返回 (是否推送, 原因)；不推送时 reason 非空。"""
    dtype = str(item.get("type") or "")
    if dtype == "DYNAMIC_TYPE_FORWARD" and bool(
        config.get("bdw_ignore_forward", True)
    ):
        return False, "转发动态（bdw_ignore_forward）"
    if bool(config.get("bdw_ignore_lottery", True)):
        text = item_text(item)
        keywords = config.get("bdw_ignore_keywords") or DEFAULT_IGNORE_KEYWORDS
        if isinstance(keywords, str):
            keywords = (
                str(keywords).replace(",", "\n").replace("，", "\n").split("\n")
            )
        for kw in keywords:
            kw = str(kw or "").strip()
            if kw and kw in text:
                return False, f"命中抽奖关键词「{kw}」（bdw_ignore_lottery）"
    return True, ""

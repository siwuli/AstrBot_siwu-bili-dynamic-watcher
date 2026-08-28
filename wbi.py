"""B 站 WBI 签名（纯标准库，可独立测试）。

实现参考 bilibili-API-collect（https://github.com/SocialSisterYi/bilibili-API-collect）：

- 从 /x/web-interface/nav 接口返回的 wbi_img.img_url / sub_url 取文件名作为
  img_key / sub_key（密钥会定期轮换，缓存建议 <=24h）；
- mixin_key = (img_key + sub_key)[:32]；
- 参数过滤空值与 w_rid/wts 后按 key 排序，值中的 !'()* 字符剔除，urlencode
  拼接查询串，再与 mixin_key 拼接做 MD5 得到 w_rid；
- 请求需携带 wts（unix 秒）与 w_rid。

还提供一组旧版公开的兜底密钥：nav 接口被风控/不可达时，如果接口仍接受旧密钥
则请求可继续（大部分接口会因密钥轮换拒绝，此时应等待密钥恢复）。
"""

import hashlib
import time
from urllib.parse import urlencode

# 密钥缓存 TTL：B 站会轮换密钥，24 小时刷新一次足够
KEY_TTL = 24 * 3600

# 公开文档中曾出现的默认密钥（兜底用；以 nav 返回为准）
FALLBACK_IMG_KEY = "7cd084941338484aae1ad9425b84077c"
FALLBACK_SUB_KEY = "4932caff0ff746eab6f01bf08b70ac45"

# 签名时值中需要剔除的字符（bilibili-API-collect 约定）
_FILTER_CHARS = "!'()*"


def extract_key(url):
    """从 wbi_img 的 URL（如 .../wbi/7cd08494....png）取文件名（不含扩展名）。"""
    name = (url or "").rsplit("/", 1)[-1]
    return name.split(".")[0].strip()


def mixin_key(img_key, sub_key):
    """取 img_key + sub_key 的前 32 位作为 mixin_key。"""
    return (img_key + sub_key)[:32]


def _clean_params(params):
    """过滤空值与签名相关字段，剔除值中的 !'()* 字符。"""
    out = {}
    for k, v in params.items():
        if k in ("w_rid", "wts"):
            continue
        if v is None or v == "":
            continue
        out[k] = "".join(ch for ch in str(v) if ch not in _FILTER_CHARS)
    return out


def build_query(params):
    """按 key 排序构建查询串（urlencode，遵循 B 站签名约定）。"""
    return urlencode({k: params[k] for k in sorted(params)})


def sign_params(params, img_key, sub_key, ts=None):
    """给参数附加 wts 与 w_rid 签名，返回新 dict（不改动入参）。"""
    signed = _clean_params(dict(params))
    signed["wts"] = int(ts if ts is not None else time.time())
    query = build_query(signed)
    w_rid = hashlib.md5(
        (query + mixin_key(img_key, sub_key)).encode("utf-8")
    ).hexdigest()
    signed["w_rid"] = w_rid
    return signed


def parse_nav_img_keys(data):
    """从 nav 接口 JSON 提取 (img_key, sub_key)；缺失时返回 (None, None)。"""
    try:
        img = data["data"]["wbi_img"]["img_url"]
        sub = data["data"]["wbi_img"]["sub_url"]
        return extract_key(img), extract_key(sub)
    except (KeyError, TypeError, IndexError):
        return None, None

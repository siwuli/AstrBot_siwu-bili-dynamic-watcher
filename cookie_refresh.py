"""B 站 Web 端 Cookie 自动刷新（纯标准库，可独立测试）。

协议参考 bilibili-API-collect docs/login/cookie_refresh.md：

1. GET  /x/passport-login/web/cookie/info      → data.refresh / data.timestamp
2. RSA-OAEP(SHA-256) 加密 "refresh_<timestamp>"，转小写 hex 得到 CorrespondPath
3. GET  https://www.bilibili.com/correspond/1/<CorrespondPath>
   → HTML 中 <div id="1-name"> 内的 refresh_csrf
4. POST /x/passport-login/web/cookie/refresh   → 新 Cookie + 新 refresh_token
5. POST /x/passport-login/web/confirm/refresh  → 用「旧的」refresh_token 让旧登录态失效

前提与限制：
- 必须额外持久化 Cookie 里的 bili_jct（csrf）和浏览器 localStorage 的
  ac_time_value（即 refresh_token），仅有 SESSDATA 无法刷新；
- 账号被强制下线 / 触发风控时，refresh_token 会一起失效，刷新同样失败。
"""

import base64
import hashlib
import os
import re

# --------------------------------------------------------------------------
# RSA 公钥（1024 bit, e=65537），来源：
# https://s1.hdslb.com/bfs/static/jinkela/long/wasm/wasm_ras_umd.js
# --------------------------------------------------------------------------
PUBLIC_KEY_JWK_N = (
    "y4HdjgJHBlbaBN04VERG4qNBIFHP6a3GozCl75AihQloSWCXC5HDNgyinEnhaQ_4-gaMud"
    "_GF50elYXLlCToR9se9Z8z433U3KjM-3Yx7ptKkmQNAMggQwAVKgq3zYAoidNEWuxpkY_mAi"
    "tTSRLnsJW-NCTa0bqBFF6Wm1MxgfE"
)
PUBLIC_KEY_E = 65537

PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDLgd2OAkcGVtoE3ThUREbio0Eg
Uc/prcajMKXvkCKFCWhJYJcLkcM2DKKcSeFpD/j6Boy538YXnR6VhcuUJOhH2x71
nzPjfdTcqMz7djHum0qSZA0AyCBDABUqCrfNgCiJ00Ra7GmRj+YCK1NJEuewlb40
JNrRuoEUXpabUzGB8QIDAQAB
-----END PUBLIC KEY-----"""

# 接口地址
COOKIE_INFO_URL = "https://passport.bilibili.com/x/passport-login/web/cookie/info"
COOKIE_REFRESH_URL = "https://passport.bilibili.com/x/passport-login/web/cookie/refresh"
COOKIE_CONFIRM_URL = "https://passport.bilibili.com/x/passport-login/web/confirm/refresh"
CORRESPOND_BASE = "https://www.bilibili.com/correspond/1/"

# OAEP 参数（与官方 wasm / pycryptodome 示例一致：SHA-256 + MGF1-SHA256）
_HASH_NAME = "sha256"
_H_LEN = 32

_REFRESH_CSRF_RE = re.compile(r'id="1-name"[^>]*>\s*([^<\s]+)\s*<')


def _b64url_to_int(value: str) -> int:
    """把 JWK 的 base64url 字段转成整数。"""
    text = (value or "").strip()
    pad = "=" * (-len(text) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(text + pad), "big")


MODULUS_N = _b64url_to_int(PUBLIC_KEY_JWK_N)


def mgf1(seed: bytes, length: int, hash_name: str = _HASH_NAME) -> bytes:
    """RFC 3447 MGF1 掩码生成函数。"""
    if length < 0:
        raise ValueError("mask length must be non-negative")
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hashlib.new(hash_name, seed + counter.to_bytes(4, "big")).digest()
        counter += 1
    return bytes(out[:length])


def rsa_oaep_encrypt(
    message: bytes,
    n: int = MODULUS_N,
    e: int = PUBLIC_KEY_E,
    seed: bytes | None = None,
) -> bytes:
    """RSA-OAEP(SHA-256) 加密，返回定长密文字节。

    seed 仅用于测试注入固定随机数；生产环境留空（os.urandom）。
    """
    key_len = (int(n).bit_length() + 7) // 8
    h_len = _H_LEN
    if len(message) > key_len - 2 * h_len - 2:
        raise ValueError("message too long for RSA-OAEP")
    l_hash = hashlib.new(_HASH_NAME, b"").digest()
    ps = b"\x00" * (key_len - len(message) - 2 * h_len - 2)
    db = l_hash + ps + b"\x01" + message
    if seed is None:
        seed = os.urandom(h_len)
    if len(seed) != h_len:
        raise ValueError(f"seed must be {h_len} bytes")
    db_mask = mgf1(seed, key_len - h_len - 1)
    masked_db = bytes(a ^ b for a, b in zip(db, db_mask))
    seed_mask = mgf1(masked_db, h_len)
    masked_seed = bytes(a ^ b for a, b in zip(seed, seed_mask))
    em = b"\x00" + masked_seed + masked_db
    cipher = pow(int.from_bytes(em, "big"), int(e), int(n))
    return cipher.to_bytes(key_len, "big")


def get_correspond_path(timestamp_ms: int, seed: bytes | None = None) -> str:
    """生成 CorrespondPath：RSA-OAEP 加密 refresh_<毫秒时间戳>，小写 hex。"""
    message = f"refresh_{int(timestamp_ms)}".encode()
    return rsa_oaep_encrypt(message, seed=seed).hex()


def parse_refresh_csrf(html: str) -> str:
    """从 correspond 页面 HTML 中提取 refresh_csrf（div#1-name）。"""
    match = _REFRESH_CSRF_RE.search(html or "")
    return match.group(1).strip() if match else ""

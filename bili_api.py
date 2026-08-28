"""B 站动态接口客户端（bili_dynamic_watcher v2.0）。

- 官方接口（关注流 feed/all、用户空间 feed/space）：自动 WBI 签名
  （wts + w_rid，密钥从 nav 接口轮换获取并缓存 24h）；
- 自动获取浏览器指纹 Cookie（buvid3/buvid4，spi 接口），配置了 bdw_buvid3
  时优先使用配置值；
- 风控识别：HTTP 412 / code -352 / -412 标记 risk=True，插件层据此退避；
  风控或签名失败时自动强制刷新 WBI 密钥并重试一次；
- fetch_text() 用于拉取 RSS 订阅源（RSSHub / RSSWorker），配合 rss_feed.py
  解析，作为官方接口被风控时的兜底。

所有接口错误统一抛 BiliAPIError，由插件层处理。
"""

import logging
import time

import aiohttp

from . import wbi

logger = logging.getLogger("astrbot")

# 关注动态流接口（拉取关注账号的最新动态，需登录态）
FEED_FOLLOW_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all"
# 用户空间动态接口（按 UID 拉取某个账号的动态，免登录）
FEED_SPACE_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
# WBI 密钥来源（登录态信息 + wbi_img）
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
# 浏览器指纹 Cookie 获取
SPI_URL = "https://api.bilibili.com/x/frontend/finger/spi"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 风控相关错误码
RISK_CODES = {-352, -412}


class BiliAPIError(Exception):
    """B 站接口错误（网络失败 / 风控 / 登录态失效等）。"""

    def __init__(self, message, code=None, http_status=None, risk=False):
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.risk = bool(risk)


def build_cookie_header(sessdata, buvid3, buvid4="") -> str:
    """拼接 B 站 Cookie 请求头；空值自动跳过。"""
    parts = []
    if sessdata:
        parts.append(f"SESSDATA={sessdata}")
    if buvid3:
        parts.append(f"buvid3={buvid3}")
    if buvid4:
        parts.append(f"buvid4={buvid4}")
    return "; ".join(parts)


class BiliDynamicClient:
    """B 站动态接口客户端，复用 aiohttp 会话。"""

    def __init__(
        self,
        sessdata: str = "",
        buvid3: str = "",
        buvid4: str = "",
        timeout: float = 15.0,
        proxy: str = "",
        wbi_enabled: bool = True,
    ):
        self._sessdata = (sessdata or "").strip()
        self._buvid3 = (buvid3 or "").strip()
        self._buvid4 = (buvid4 or "").strip()
        self._proxy = (proxy or "").strip() or None
        self._wbi_enabled = bool(wbi_enabled)
        self._buvid_tried = False
        self._wbi_keys = None
        self._wbi_fetched_at = 0.0
        self._wbi_error = ""
        self._signed = False
        self._risk_count = 0
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=max(5.0, float(timeout or 15))),
            headers={
                "User-Agent": USER_AGENT,
                "Referer": "https://www.bilibili.com/",
            },
        )

    @property
    def has_sessdata(self) -> bool:
        return bool(self._sessdata)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # 登录态 / 指纹 / 密钥
    # ------------------------------------------------------------------
    async def _ensure_buvid(self) -> None:
        """没有配置 buvid3 时，通过 spi 接口自动获取 buvid3/buvid4。"""
        if self._buvid3 or self._buvid_tried:
            return
        self._buvid_tried = True
        try:
            data = await self._get_json(SPI_URL, {}, require_wbi=False)
            info = data.get("data") or {}
            b3 = str(info.get("b_3") or "").strip()
            b4 = str(info.get("b_4") or "").strip()
            if b3:
                self._buvid3 = b3
                self._buvid4 = self._buvid4 or b4
                logger.info("已通过 spi 接口自动获取 buvid3/buvid4")
            else:
                logger.debug("spi 接口未返回 buvid3")
        except Exception as e:  # noqa: BLE001
            logger.debug("自动获取 buvid 失败: %s", e)

    async def _fetch_nav_json(self) -> dict:
        """获取 nav 接口 JSON。

        未登录（无 SESSDATA）时 code=-101，但通常仍返回 wbi_img 密钥；
        所以这里不做 code 校验，只保证 HTTP 成功与 JSON 解析。
        """
        headers = {
            "Cookie": build_cookie_header(self._sessdata, self._buvid3, self._buvid4)
        }
        async with self._session.get(
            NAV_URL, headers=headers, proxy=self._proxy
        ) as resp:
            if resp.status != 200:
                raise BiliAPIError(
                    f"nav 接口 HTTP {resp.status}", http_status=resp.status
                )
            return await resp.json(content_type=None)

    async def _ensure_wbi_keys(self, force: bool = False):
        """获取 WBI 签名密钥（nav 接口，缓存 24h）；失败时兜底旧公开密钥。"""
        if not self._wbi_enabled:
            return None
        now = time.time()
        if (
            self._wbi_keys
            and not force
            and (now - self._wbi_fetched_at) < wbi.KEY_TTL
        ):
            return self._wbi_keys
        try:
            data = await self._fetch_nav_json()
            img_key, sub_key = wbi.parse_nav_img_keys(data)
            if img_key and sub_key:
                self._wbi_keys = (img_key, sub_key)
                self._wbi_fetched_at = now
                self._wbi_error = ""
                logger.info("WBI 签名密钥已%s刷新", "强制" if force else "")
                return self._wbi_keys
        except Exception as e:  # noqa: BLE001
            self._wbi_error = str(e)[:120]
            logger.debug("获取 WBI 密钥失败: %s", e)
        if self._wbi_keys is None:
            self._wbi_keys = (wbi.FALLBACK_IMG_KEY, wbi.FALLBACK_SUB_KEY)
        return self._wbi_keys

    def wbi_status(self) -> dict:
        """供 bd状态 展示的 WBI 状态。"""
        age = int(time.time() - self._wbi_fetched_at) if self._wbi_fetched_at else None
        return {
            "enabled": bool(self._wbi_enabled),
            "signed": bool(self._signed),
            "key_age": age,
            "error": self._wbi_error,
            "risk_count": self._risk_count,
        }

    # ------------------------------------------------------------------
    # 动态接口
    # ------------------------------------------------------------------
    async def fetch_follow_feed(self, page: int = 1) -> dict:
        """拉取关注动态流（全部类型），需要登录态。"""
        if not self._sessdata:
            raise BiliAPIError(
                "关注流模式需要配置 bdw_sessdata（B站登录 Cookie）",
                risk=False,
            )
        params = {"type": "all", "page": page, "timezone_offset": -480}
        return await self._get_json(FEED_FOLLOW_URL, params, require_wbi=True)

    async def fetch_space_feed(self, uid: str, offset: str = "") -> dict:
        """拉取指定 UID 的用户空间动态（免登录）。"""
        params = {"host_mid": str(uid), "offset": offset, "timezone_offset": -480}
        return await self._get_json(FEED_SPACE_URL, params, require_wbi=True)

    async def fetch_text(self, url: str) -> str:
        """拉取任意文本（RSS 订阅源），带正常浏览器头。"""
        headers = {
            "Cookie": build_cookie_header(self._sessdata, self._buvid3, self._buvid4)
        }
        try:
            async with self._session.get(url, headers=headers, proxy=self._proxy) as resp:
                if resp.status != 200:
                    raise BiliAPIError(
                        f"RSS 源 HTTP {resp.status}", http_status=resp.status
                    )
                return await resp.text()
        except aiohttp.ClientError as e:
            raise BiliAPIError(f"请求 RSS 源失败：{e}") from e

    # ------------------------------------------------------------------
    # 核心请求
    # ------------------------------------------------------------------
    async def _get_json(
        self, url: str, params: dict, require_wbi: bool = True
    ) -> dict:
        """GET 一个 B 站 JSON 接口；风控/签名失败时自动刷新密钥重试一次。"""
        await self._ensure_buvid()
        headers = {
            "Cookie": build_cookie_header(self._sessdata, self._buvid3, self._buvid4)
        }
        retried = False
        while True:
            req_params = dict(params)
            if require_wbi:
                keys = await self._ensure_wbi_keys(force=retried)
                if keys:
                    req_params = wbi.sign_params(req_params, *keys)
                    self._signed = True
            try:
                async with self._session.get(
                    url, params=req_params, headers=headers, proxy=self._proxy
                ) as resp:
                    if resp.status == 412:
                        if not retried and self._wbi_enabled:
                            retried = True
                            await self._ensure_wbi_keys(force=True)
                            continue
                        self._risk_count += 1
                        raise BiliAPIError(
                            "B站风控拦截（HTTP 412）：已自动退避并刷新密钥，"
                            "请保持请求间隔并核对 SESSDATA 是否有效",
                            http_status=412,
                            risk=True,
                        )
                    if resp.status != 200:
                        raise BiliAPIError(
                            f"B站接口 HTTP {resp.status}", http_status=resp.status
                        )
                    data = await resp.json(content_type=None)
            except aiohttp.ClientError as e:
                raise BiliAPIError(f"请求 B站接口失败：{e}") from e

            code = data.get("code")
            if code == 0:
                return data
            risk = int(code or -1) in RISK_CODES
            if risk and not retried and self._wbi_enabled:
                retried = True
                await self._ensure_wbi_keys(force=True)
                continue
            msg = str(data.get("message") or data.get("msg") or "未知错误")
            hint = ""
            if code == -101:
                hint = "（SESSDATA 无效或已过期，请重新获取并更新 bdw_sessdata）"
            elif code == -352:
                hint = "（触发风控，已自动退避；请补充 bdw_buvid3 或降低轮询频率）"
            elif code == -404:
                hint = "（UID 不存在或接口路径变化）"
            if risk:
                self._risk_count += 1
            raise BiliAPIError(
                f"B站接口返回 code={code} {msg}{hint}", code=code, risk=risk
            )
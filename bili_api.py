"""B 站动态接口客户端（bili_dynamic_watcher 插件）。

封装访问 B 站 polymer web-dynamic v1 接口：
- 关注动态流：/x/polymer/web-dynamic/v1/feed/all（需 SESSDATA 登录态）
- 用户空间动态：/x/polymer/web-dynamic/v1/feed/space（免登录，可带 buvid3）

所有接口错误统一抛 BiliAPIError，由插件层处理。
"""

import logging

import aiohttp

logger = logging.getLogger("astrbot")

# 关注动态流接口（拉取关注账号的最新动态，需登录态）
FEED_FOLLOW_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all"
# 用户空间动态接口（按 UID 拉取某个账号的动态，免登录）
FEED_SPACE_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class BiliAPIError(Exception):
    """B 站接口错误（网络失败 / 风控 / 登录态失效等）。"""

    def __init__(self, message: str, code=None, http_status=None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def build_cookie_header(sessdata: str, buvid3: str) -> str:
    """拼接 B 站 Cookie 请求头；空值自动跳过。"""
    parts = []
    if sessdata:
        parts.append(f"SESSDATA={sessdata}")
    if buvid3:
        parts.append(f"buvid3={buvid3}")
    return "; ".join(parts)


class BiliDynamicClient:
    """B 站动态接口客户端，复用 aiohttp 会话。"""

    def __init__(
        self,
        sessdata: str = "",
        buvid3: str = "",
        timeout: float = 15.0,
        proxy: str = "",
    ):
        self._sessdata = (sessdata or "").strip()
        self._buvid3 = (buvid3 or "").strip()
        self._proxy = (proxy or "").strip() or None
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=max(5.0, float(timeout or 15))),
            headers={
                "User-Agent": USER_AGENT,
                "Referer": "https://www.bilibili.com/",
            },
        )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_follow_feed(self, page: int = 1) -> dict:
        """拉取关注动态流（全部类型），需要登录态。"""
        if not self._sessdata:
            raise BiliAPIError("关注流模式需要配置 bdw_sessdata（B站登录 Cookie）")
        params = {"type": "all", "page": page, "timezone_offset": -480}
        return await self._get_json(FEED_FOLLOW_URL, params)

    async def fetch_space_feed(self, uid: str, offset: str = "") -> dict:
        """拉取指定 UID 的用户空间动态。"""
        params = {"host_mid": str(uid), "offset": offset, "timezone_offset": -480}
        return await self._get_json(FEED_SPACE_URL, params)

    async def _get_json(self, url: str, params: dict) -> dict:
        headers = {"Cookie": build_cookie_header(self._sessdata, self._buvid3)}
        try:
            async with self._session.get(
                url, params=params, headers=headers, proxy=self._proxy
            ) as resp:
                if resp.status == 412:
                    raise BiliAPIError(
                        "B站风控拦截（HTTP 412）：请增大 bdw_poll_interval、配置 "
                        "bdw_buvid3，或改用关注流模式（follow）",
                        http_status=412,
                    )
                if resp.status != 200:
                    raise BiliAPIError(
                        f"B站接口 HTTP {resp.status}", http_status=resp.status
                    )
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as e:
            raise BiliAPIError(f"请求 B站接口失败：{e}") from e

        code = data.get("code")
        if code != 0:
            msg = str(data.get("message") or data.get("msg") or "未知错误")
            hint = ""
            if code == -101:
                hint = "（SESSDATA 无效或已过期，请重新获取并更新 bdw_sessdata）"
            elif code == -352:
                hint = "（触发风控，请补充 bdw_buvid3 或降低轮询频率）"
            elif code == -404:
                hint = "（UID 不存在或接口路径变化）"
            raise BiliAPIError(f"B站接口返回 code={code} {msg}{hint}", code=code)
        return data

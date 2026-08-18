"""B站动态监听插件（bili_dynamic_watcher）。

监听指定 B 站账号（UP主）的最新动态，新动态自动推送到配置的 QQ 群。

两种拉取模式：
- follow（推荐）：使用一个已关注目标账号的 B 站账号（SESSDATA 登录态）拉取
  「关注动态流」接口，再从结果中过滤出监听账号的动态。相比逐个主页轮询，
  单接口低频请求更不容易触发 B 站风控。
- space：直接按 UID 轮询用户空间动态接口（免登录，但高频访问易被风控，
  仅建议少量账号 + 较大轮询间隔时使用）。

纯后台轮询 + 主动推送，不依赖 LLM。
"""

import asyncio
import json
import logging
import os
import random
from datetime import datetime

from astrbot.api import star
from astrbot.api.all import AstrBotConfig, AstrMessageEvent, MessageChain
from astrbot.api.event import filter
from astrbot.core.platform.message_type import MessageType
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .bili_api import BiliAPIError, BiliDynamicClient

logger = logging.getLogger("astrbot")

DATA_DIR = os.path.join(get_astrbot_data_path(), "bili_dynamic_watcher")
SEEN_FILE = os.path.join(DATA_DIR, "seen_dynamics.json")
WATCH_FILE = os.path.join(DATA_DIR, "watched_uids.json")

DEFAULT_POLL_INTERVAL = 60
MIN_POLL_INTERVAL = 10
MAX_SEEN_KEEP = 3000
MAX_DYNAMIC_TEXT_LEN = 120
MAX_PUSH_PER_CYCLE = 10

DYNAMIC_TYPE_NAMES = {
    "DYNAMIC_TYPE_WORD": "文字动态",
    "DYNAMIC_TYPE_DRAW": "图文动态",
    "DYNAMIC_TYPE_AV": "视频投稿",
    "DYNAMIC_TYPE_FORWARD": "转发动态",
    "DYNAMIC_TYPE_ARTICLE": "专栏文章",
    "DYNAMIC_TYPE_MUSIC": "音频动态",
    "DYNAMIC_TYPE_LIVE_RCMD": "直播开播",
    "DYNAMIC_TYPE_LIVE": "直播",
    "DYNAMIC_TYPE_PGC": "剧集动态",
    "DYNAMIC_TYPE_MATCH": "赛事动态",
    "DYNAMIC_TYPE_COMMON": "普通动态",
}


def _norm_list(value) -> list[str]:
    """把配置项归一化为字符串列表（兼容 list 与换行/逗号分隔的字符串）。"""
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = str(value).replace(",", "\n").replace("，", "\n").split("\n")
    return [str(x).strip() for x in items if str(x).strip()]


def _truncate(text: str, limit: int = MAX_DYNAMIC_TEXT_LEN) -> str:
    text = (text or "").strip()
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _extract_dynamic_text(dyn: dict, dtype: str) -> str:
    """从动态的 module_dynamic 中提取可读文本摘要。"""
    desc = str(((dyn or {}).get("desc") or {}).get("text") or "").strip()
    major = (dyn or {}).get("major") or {}
    if dtype == "DYNAMIC_TYPE_AV" and major.get("archive"):
        title = str(major["archive"].get("title") or "").strip()
        if title:
            desc = f"视频《{title}》" if not desc else f"{desc}｜视频《{title}》"
    elif dtype == "DYNAMIC_TYPE_ARTICLE" and major.get("article"):
        title = str(major["article"].get("title") or "").strip()
        if title:
            desc = f"专栏《{title}》" if not desc else desc
    elif dtype == "DYNAMIC_TYPE_DRAW":
        draw = major.get("draw") or {}
        count = len(draw.get("items") or [])
        if count:
            suffix = f"（共 {count} 张图）"
            desc = f"{desc}{suffix}" if desc else suffix
    elif dtype == "DYNAMIC_TYPE_FORWARD":
        if desc:
            desc = f"转发：{desc}"
    elif dtype == "DYNAMIC_TYPE_LIVE_RCMD" and major.get("live_rcmd"):
        content = str(major["live_rcmd"].get("content") or "").strip()
        if content:
            desc = content if not desc else f"{desc}｜{content}"
    return _truncate(desc)


def format_dynamic(item: dict) -> str:
    """把一条 B 站动态（polymer web-dynamic v1 的 item）格式化为推送文本。"""
    modules = item.get("modules") or {}
    author = modules.get("module_author") or {}
    dyn = modules.get("module_dynamic") or {}
    dtype = str(item.get("type") or "DYNAMIC_TYPE_WORD")
    type_name = DYNAMIC_TYPE_NAMES.get(dtype, "新动态")
    name = str(author.get("name") or "").strip() or "未知UP主"
    text = _extract_dynamic_text(dyn, dtype)
    pub_ts = int(author.get("pub_ts") or 0)
    time_str = (
        datetime.fromtimestamp(pub_ts).astimezone().strftime("%m-%d %H:%M")
        if pub_ts
        else ""
    )
    did = str(item.get("id_str") or "")
    link = f"https://t.bilibili.com/{did}" if did else ""

    lines = [f"【B站新动态】{name} 发布了{type_name}"]
    if text:
        lines.append(text)
    major = dyn.get("major") or {}
    if dtype == "DYNAMIC_TYPE_AV" and major.get("archive"):
        bvid = str(major["archive"].get("bvid") or "").strip()
        if bvid:
            lines.append(f"视频链接：https://www.bilibili.com/video/{bvid}")
    elif dtype == "DYNAMIC_TYPE_ARTICLE" and major.get("article"):
        cvid = major["article"].get("id")
        if cvid:
            lines.append(f"专栏链接：https://www.bilibili.com/read/cv{cvid}")
    if time_str:
        lines.append(f"时间：{time_str}")
    if link:
        lines.append(f"链接：{link}")
    return "\n".join(lines)


class BiliDynamicWatcherPlugin(star.Star):
    """B站动态监听插件。"""

    def __init__(self, context, config: AstrBotConfig = None):
        super().__init__(context, config)
        self.config = config or {}
        self._task: asyncio.Task | None = None
        self._http: BiliDynamicClient | None = None
        self._lock: asyncio.Lock | None = None
        self._seen: set[str] = set()
        self._watching: dict[str, str] = {}  # uid -> 备注
        self._last_poll: dict = {"time": 0, "new": 0, "error": ""}

    # ------------------------------------------------------------------
    # 生命周期：插件加载时启动轮询，卸载时停止
    # ------------------------------------------------------------------
    async def initialize(self) -> None:
        self._lock = asyncio.Lock()
        self._load_watch_list()
        self._load_seen()
        self._http = BiliDynamicClient(
            sessdata=str(self.config.get("bdw_sessdata", "") or ""),
            buvid3=str(self.config.get("bdw_buvid3", "") or ""),
            timeout=float(self.config.get("bdw_timeout", 15) or 15),
            proxy=str(self.config.get("bdw_proxy", "") or ""),
        )
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._poll_loop())
            logger.info(
                "B站动态监听已启动：模式=%s，监听 %d 个账号",
                str(self.config.get("bdw_mode", "follow") or "follow"),
                len(self._watching),
            )

    async def terminate(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception) as e:  # noqa: BLE001
                logger.debug("轮询任务已随插件停止: %s", e)
            self._task = None
        if self._http:
            await self._http.close()
            self._http = None

    # ------------------------------------------------------------------
    # 轮询
    # ------------------------------------------------------------------
    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.error("B站动态轮询异常: %s", e)
                self._last_poll["error"] = str(e)[:200]
            await asyncio.sleep(self._current_interval())

    def _current_interval(self) -> float:
        interval = float(
            self.config.get("bdw_poll_interval", DEFAULT_POLL_INTERVAL)
            or DEFAULT_POLL_INTERVAL
        )
        interval = max(MIN_POLL_INTERVAL, interval)
        # 加一点随机抖动，避免固定节奏被风控
        return interval + random.uniform(0, max(1.0, interval * 0.2))

    async def _poll_once(self) -> None:
        if not bool(self.config.get("bdw_enabled", True)):
            return
        watched = self._current_watch_list()
        if not watched:
            return
        mode = str(self.config.get("bdw_mode", "follow") or "follow").strip().lower()
        try:
            items = await self._fetch_latest_items(mode)
        except BiliAPIError as e:
            logger.error("拉取B站动态失败: %s", e)
            self._last_poll["error"] = str(e)[:200]
            return

        new_items = self._select_new_items(items, watched)
        if not new_items:
            self._last_poll.update(time=time_now(), new=0, error="")
            return

        # 按发布时间倒序，取最新的 N 条推送
        new_items.sort(
            key=lambda it: int(
                (it.get("modules") or {}).get("module_author", {}).get("pub_ts") or 0
            ),
            reverse=True,
        )
        limit = max(
            1,
            int(
                self.config.get("bdw_max_per_cycle", MAX_PUSH_PER_CYCLE)
                or MAX_PUSH_PER_CYCLE
            ),
        )
        to_push = new_items[:limit]
        for item in to_push:
            try:
                await self._push_to_groups(format_dynamic(item))
            except Exception as e:  # noqa: BLE001
                logger.error("推送B站动态失败: %s", e)

        # 本轮所有新动态都记为已见（包括超出推送上限的），避免下轮重复
        self._record_seen([str(it.get("id_str")) for it in new_items])
        self._last_poll.update(
            time=time_now(),
            new=len(new_items),
            error="",
        )
        logger.info(
            "B站动态轮询：发现 %d 条新动态，推送 %d 条", len(new_items), len(to_push)
        )

    async def _fetch_latest_items(self, mode: str) -> list[dict]:
        """按模式拉取最新动态列表（未过滤）。"""
        if mode == "space":
            items: list[dict] = []
            for uid in self._current_watch_list():
                try:
                    data = await self._http.fetch_space_feed(uid)
                    items.extend((data.get("data") or {}).get("items") or [])
                except BiliAPIError as e:
                    logger.error("拉取空间动态失败 uid=%s: %s", uid, e)
                await asyncio.sleep(random.uniform(1.0, 3.0))
            return items
        data = await self._http.fetch_follow_feed()
        return (data.get("data") or {}).get("items") or []

    def _select_new_items(
        self, items: list[dict], watched: dict[str, str]
    ) -> list[dict]:
        """过滤出监听账号的、且未推送过的动态。"""
        out = []
        for item in items or []:
            modules = item.get("modules") or {}
            author = modules.get("module_author") or {}
            uid = str(author.get("mid") or "").strip()
            did = str(item.get("id_str") or "").strip()
            if not uid or not did:
                continue
            if uid not in watched:
                continue
            if did in self._seen:
                continue
            out.append(item)
        return out

    # ------------------------------------------------------------------
    # 推送
    # ------------------------------------------------------------------
    async def _push_to_groups(self, text: str) -> None:
        groups = _norm_list(self.config.get("bdw_groups"))
        if not groups:
            logger.warning("未配置推送目标群（bdw_groups），动态未发送：%s", text[:60])
            return
        platform_id = str(
            self.config.get("bdw_platform_id", "aiocqhttp") or "aiocqhttp"
        ).strip()
        chain = MessageChain().message(text)
        for gid in groups:
            if not gid.isdigit():
                logger.warning("跳过非数字群号: %s", gid)
                continue
            session = f"{platform_id}:{MessageType.GROUP_MESSAGE.value}:{gid}"
            try:
                ok = await self.context.send_message(session, chain)
                if not ok:
                    logger.warning(
                        "推送群 %s 失败：找不到平台 %s（检查 bdw_platform_id）",
                        gid,
                        platform_id,
                    )
            except Exception as e:  # noqa: BLE001
                logger.error("推送群 %s 失败: %s", gid, e)

    # ------------------------------------------------------------------
    # 指令（免 LLM）
    # ------------------------------------------------------------------
    @filter.command("bd列表")
    async def bd_list(self, event: AstrMessageEvent):
        """列出当前监听的 B 站账号。"""
        watched = self._current_watch_list()
        if not watched:
            event.stop_event()
            yield event.make_result().message(
                "当前没有监听任何 B 站账号。\n"
                "使用「bd添加 <UID> [备注]」添加，或在插件配置 bdw_uid_list 中填写初始列表。"
            )
            return
        lines = [f"当前共监听 {len(watched)} 个账号："]
        for uid, remark in sorted(watched.items()):
            lines.append(f"- {uid}（{remark or '无备注'}）")
        event.stop_event()
        yield event.make_result().message("\n".join(lines))

    @filter.command("bd添加")
    async def bd_add(self, event: AstrMessageEvent):
        """添加监听账号：bd添加 <UID> [备注]。"""
        denied = self._check_manage_permission(event)
        if denied:
            event.stop_event()
            yield event.make_result().message(denied)
            return
        parts = (event.get_message_str() or "").split()
        if len(parts) < 2:
            event.stop_event()
            yield event.make_result().message(
                "用法：bd添加 <B站UID> [备注]\n例如：bd添加 208259 兔兔官方"
            )
            return
        uid = parts[1].strip()
        if not uid.isdigit() or not (1 <= len(uid) <= 15):
            event.stop_event()
            yield event.make_result().message(
                "UID 无效，请输入纯数字的 B 站 UID（mid）。"
            )
            return
        remark = " ".join(parts[2:]).strip()
        async with self._lock:
            existed = uid in self._watching
            self._watching[uid] = remark
            self._save_watch_list()
        tip = "已更新备注" if existed else "已添加监听"
        event.stop_event()
        yield event.make_result().message(
            f"{tip}：UID {uid}（{remark or '无备注'}）\n"
            "关注流模式下请确认关注号已在 B 站关注该账号。"
        )

    @filter.command("bd删除")
    async def bd_remove(self, event: AstrMessageEvent):
        """删除监听账号：bd删除 <UID>。"""
        denied = self._check_manage_permission(event)
        if denied:
            event.stop_event()
            yield event.make_result().message(denied)
            return
        parts = (event.get_message_str() or "").split()
        if len(parts) < 2:
            event.stop_event()
            yield event.make_result().message("用法：bd删除 <B站UID>")
            return
        uid = parts[1].strip()
        async with self._lock:
            if uid not in self._watching:
                event.stop_event()
                yield event.make_result().message(f"UID {uid} 不在监听列表中。")
                return
            del self._watching[uid]
            self._save_watch_list()
        event.stop_event()
        yield event.make_result().message(f"已停止监听 UID {uid}。")

    @filter.command("bd状态")
    async def bd_status(self, event: AstrMessageEvent):
        """查看插件运行状态。"""
        watched = self._current_watch_list()
        sessdata = str(self.config.get("bdw_sessdata", "") or "").strip()
        sess_masked = f"{sessdata[:4]}****" if sessdata else "（未配置）"
        groups = _norm_list(self.config.get("bdw_groups"))
        last = self._last_poll
        last_text = (
            "尚未轮询"
            if not last.get("time")
            else (
                f"{last['time']} 发现 {last['new']} 条新动态"
                + (f"（错误：{last['error']}）" if last.get("error") else "")
            )
        )
        lines = [
            "B站动态监听状态：",
            f"- 总开关：{'开启' if bool(self.config.get('bdw_enabled', True)) else '关闭'}",
            f"- 模式：{self.config.get('bdw_mode', 'follow') or 'follow'}",
            f"- SESSDATA：{sess_masked}",
            f"- 轮询间隔：{self.config.get('bdw_poll_interval', 60)} 秒",
            f"- 监听账号：{len(watched)} 个",
            f"- 推送群：{len(groups)} 个（{', '.join(groups) or '未配置'}）",
            f"- 推送平台：{self.config.get('bdw_platform_id', 'aiocqhttp') or 'aiocqhttp'}",
            f"- 已记录动态：{len(self._seen)} 条",
            f"- 最近轮询：{last_text}",
        ]
        event.stop_event()
        yield event.make_result().message("\n".join(lines))

    @filter.command("bd测试")
    async def bd_test(self, event: AstrMessageEvent):
        """拉取一次最新动态并报告结果（不推送、不记已见），用于排查配置。"""
        denied = self._check_manage_permission(event)
        if denied:
            event.stop_event()
            yield event.make_result().message(denied)
            return
        watched = self._current_watch_list()
        if not watched:
            event.stop_event()
            yield event.make_result().message("请先添加监听账号（bd添加 <UID>）。")
            return
        mode = str(self.config.get("bdw_mode", "follow") or "follow").strip().lower()
        try:
            items = await self._fetch_latest_items(mode)
        except BiliAPIError as e:
            event.stop_event()
            yield event.make_result().message(f"拉取失败：{e}")
            return
        matched = self._select_new_items(items, watched)
        event.stop_event()
        if not matched:
            yield event.make_result().message(
                f"拉取成功（模式 {mode}），接口返回 {len(items)} 条动态，"
                "其中没有监听账号的未推送新动态。\n"
                "可能原因：关注号未关注目标账号 / SESSDATA 过期 / 该账号近期无新动态。"
            )
            return
        lines = [f"拉取成功（模式 {mode}），发现 {len(matched)} 条未推送新动态："]
        for item in matched[:10]:
            modules = item.get("modules") or {}
            author = modules.get("module_author") or {}
            dtype = str(item.get("type") or "")
            lines.append(
                f"- {author.get('name')}（{author.get('mid')}）"
                f" {DYNAMIC_TYPE_NAMES.get(dtype, dtype)} id={item.get('id_str')}"
            )
        yield event.make_result().message("\n".join(lines))

    # ------------------------------------------------------------------
    # 权限
    # ------------------------------------------------------------------
    def _check_manage_permission(self, event: AstrMessageEvent) -> str | None:
        """管理指令权限校验。返回 None 表示放行，否则返回拒绝提示。"""
        if not bool(self.config.get("bdw_permission_enabled", True)):
            return None
        sender_id = str(event.get_sender_id() or "").strip()
        admin_ids = _norm_list(self.config.get("bdw_admin_ids"))
        if sender_id and sender_id in admin_ids:
            return None
        sender = getattr(event, "message_obj", None) and getattr(
            event.message_obj, "sender", None
        )
        role = str(getattr(sender, "role", "") or "").lower()
        admin_roles = [
            x.lower()
            for x in _norm_list(
                self.config.get("bdw_admin_role", ["owner", "admin"])
            )
        ]
        if role and role in admin_roles:
            return None
        return (
            "该操作需要管理权限。请联系管理员在插件配置"
            "（bdw_admin_ids / bdw_admin_role）中添加你的权限。"
        )

    # ------------------------------------------------------------------
    # 存储
    # ------------------------------------------------------------------
    def _current_watch_list(self) -> dict[str, str]:
        return dict(self._watching)

    def _load_watch_list(self) -> None:
        try:
            if os.path.exists(WATCH_FILE):
                with open(WATCH_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                self._watching = {str(k): str(v or "") for k, v in (data or {}).items()}
        except Exception as e:  # noqa: BLE001
            logger.error("读取监听列表失败: %s", e)
        # 首次运行（文件不存在）时，用配置中的初始 UID 列表填充
        if not self._watching:
            for uid in _norm_list(self.config.get("bdw_uid_list")):
                self._watching[uid] = ""
            if self._watching:
                self._save_watch_list()

    def _save_watch_list(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = WATCH_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._watching, f, ensure_ascii=False, indent=2)
        os.replace(tmp, WATCH_FILE)

    def _load_seen(self) -> None:
        try:
            if os.path.exists(SEEN_FILE):
                with open(SEEN_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                self._seen = {str(x) for x in (data or [])}
        except Exception as e:  # noqa: BLE001
            logger.error("读取已见动态列表失败: %s", e)

    def _record_seen(self, ids: list[str]) -> None:
        for i in ids:
            if i:
                self._seen.add(i)
        if len(self._seen) > MAX_SEEN_KEEP:
            self._seen = set(list(self._seen)[-MAX_SEEN_KEEP:])
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = SEEN_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(list(self._seen), f, ensure_ascii=False)
        os.replace(tmp, SEEN_FILE)


def time_now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")

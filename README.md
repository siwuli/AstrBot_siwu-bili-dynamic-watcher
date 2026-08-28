# 兔兔 - AstrBot 动态监听插件（B站 / 微博 / 任意 RSS）

监听指定账号（B 站 UP 主、微博博主等）的最新动态，**新动态自动推送到配置的 QQ 群**。
纯后台轮询 + 主动推送，**不依赖 LLM**，对话不会被打扰。

> 插件 id：`bili_dynamic_watcher`　当前版本：`2.0.0`

## 为什么会有 v2.0（强壮化）

之前直接轮询 B 站官方接口的插件，**1~2 天就被风控**（HTTP 412 / code=-352）。原因是：

1. 请求没有 **WBI 签名**（wts + w_rid），缺少浏览器指纹 Cookie（buvid3/buvid4），
   接口很容易判定为脚本请求；
2. 固定频率轮询，无抖动、无退避，被风控后仍按原频率硬闯。

v2.0 的应对（三层）：

| 层 | 手段 |
| --- | --- |
| 请求层 | 自动 WBI 签名（密钥从 nav 接口轮换缓存 24h）+ 自动获取 buvid3/buvid4 指纹；未登录也能取密钥 |
| 频率层 | 随机抖动（±20%）+ **自适应退避**：触发风控/连续失败时间隔自动 ×2，最长 1 小时（可配），恢复后自动归零 |
| 兜底层 | **RSS 订阅源**（RSSHub / RSSWorker / 自建）：官方接口被风控时自动切换（auto 模式），或直接指定 rss 模式；**微博等平台同样可盯** |

## 工作原理

### 拉取模式（bdw_mode）

| 模式 | 说明 | 适用 |
| --- | --- | --- |
| `auto`（默认） | 优先 follow（有 SESSDATA 时），官方接口风控/失败自动切 RSS 兜底 | 一般用户 |
| `follow` | 只用关注流官方接口（WBI 签名） | 不想依赖 RSS |
| `space` | 按 UID 轮询用户空间接口（免登录） | 少量账号 + 大间隔 |
| `rss` | 只走 RSS 订阅源，完全绕开官方接口风控 | 追求绝对稳定 |

### 官方接口模式（follow / space）

- 关注流：用关注号（SESSDATA 登录态）低频拉取「关注动态流」接口，过滤出监听账号的动态；
- 空间流：按 UID 轮询用户空间接口；
- 两种模式都带 WBI 签名 + buvid 指纹 + 抖动 + 退避。

### RSS 模式（rss / auto 兜底）

- 每个监听 UID 对应一个订阅源：`{bdw_rss_base}/{bdw_rss_route}`；
- 默认路由 `bilibili/user/dynamic/{uid}`（RSSHub 哔哩哔哩动态）；
- 微博：把 `bdw_rss_route` 改为 `weibo/user/{uid}`（文本/图片动态，公共实例常需 cookie，建议自建 RSSHub 配 `WEIBO_COOKIES`）；
- 也兼容 RSSWorker（Cloudflare Worker）等标准 RSS 输出；
- RSS 条目用 guid/link 哈希去重（`rss:` 前缀），与官方接口的 `api:` 前缀互不冲突。

## 前置准备

1. **（follow 需要）获取关注号的 SESSDATA（Cookie）**
   - 用浏览器登录 `bilibili.com`（建议用小号）
   - F12 → Application → Cookies → `https://www.bilibili.com` → 复制 `SESSDATA`
   - **请选择 Domain 为 `.bilibili.com` 的那条**（.biligame.com 那条无效）
   - 有效期约半年，失效报 code=-101
2. **（可选）buvid3**：同位置复制；不填则自动通过 spi 接口获取
3. **关注目标账号**：follow 模式要求关注号在 B 站关注目标 UP 主
4. **UID**：B 站个人空间地址 `https://space.bilibili.com/<UID>` 中的数字；微博为博主主页的纯数字 uid
5. **QQ 群号**：配置 `bdw_groups`

## 配置项

| 配置项 | 说明 | 默认 |
| --- | --- | --- |
| `bdw_enabled` | 总开关 | `true` |
| `bdw_mode` | `auto`（默认）/ `follow` / `space` / `rss` | `auto` |
| `bdw_sessdata` | 关注号 SESSDATA（follow 需要） | 空 |
| `bdw_buvid3` | 浏览器 buvid3（可选，自动获取兜底） | 空 |
| `bdw_uid_list` | 初始监听 UID 列表（仅首次加载写入） | `[]` |
| `bdw_warmup` | 首次启动预热：历史动态只记录不推送 | `true` |
| `bdw_groups` | 推送目标 QQ 群号（每行一个） | `[]` |
| `bdw_platform_id` | 推送平台适配器 ID（**留空自动探测**） | 空 |
| `bdw_poll_interval` | 基础轮询间隔（秒） | `120` |
| `bdw_backoff_max` | 风控退避上限（秒），触发后间隔 ×2 直到该值 | `3600` |
| `bdw_rss_base` | RSS 源地址（如 `https://rsshub.app` 或自建）| 空 |
| `bdw_rss_route` | RSS 路由模板（须含 `{uid}` 占位符） | `bilibili/user/dynamic/{uid}` |
| `bdw_max_per_cycle` | 每轮最多推送条数 | `10` |
| `bdw_timeout` | 单请求超时（秒） | `15` |
| `bdw_proxy` | HTTP 代理（可选） | 空 |
| `bdw_permission_enabled` | 管理指令权限校验 | `true` |
| `bdw_admin_ids` | 管理指令用户白名单 | `[]` |
| `bdw_admin_role` | 群内管理角色 | `["owner", "admin"]` |

> `bdw_uid_list` 仅首次加载时初始化本地监听列表；之后用 `bd添加 / bd删除` 管理
> （数据在 `data/bili_dynamic_watcher/watched_uids.json`）。

## 指令（免 LLM，需 @ 机器人或唤醒词）

| 指令 | 说明 | 权限 |
| --- | --- | --- |
| `bd列表` | 查看监听账号 | 所有人 |
| `bd添加 <UID> [备注]` | 添加监听（如 `bd添加 208259 兔兔`） | 管理员 |
| `bd删除 <UID>` | 停止监听 | 管理员 |
| `bd状态` | 运行状态（模式/数据源/退避级别/WBI签名/RSS 地址等） | 所有人 |
| `bd测试` | 立即拉取一次并报告（**不推送、不记已见**） | 管理员 |

## 数据存储

- `data/bili_dynamic_watcher/watched_uids.json`：监听列表（UID → 备注）
- `data/bili_dynamic_watcher/seen_dynamics.json`：已推送动态去重（最多保留 3000 条）

> v2.0 起去重键带 `api:` / `rss:` 前缀，老数据首次启动自动迁移，
> **升级后不会重复推送历史动态**。

## 打包

```bash
python plugins/astrbot/siwu-bili-dynamic-watcher-1_0/build.py
```

产物：`plugins/astrbot/dist/siwu-bili-dynamic-watcher-2.0.0.zip`

## 常见问题

**为什么之前 1~2 天就被限制？**
- 老版本无 WBI 签名 / 无 buvid 指纹 / 固定频率，且被风控后退避不足。v2.0 已三层加固：
  WBI 签名 + 指纹 + 抖动退避 + RSS 兜底。仍在被限时优先自查：
  1. `bd状态` 看「WBI 签名」是否「已启用（签名生效）」；
  2. 关注号 SESSDATA 是否过期（code=-101）；
  3. 服务器 IP 是否被 B 站整体风控（HTTP 412 且 RSS 正常时，切 `rss` 模式）。

**报错 412 / code=-352（风控）？**
- 插件会自动退避（间隔 ×2 直至 `bdw_backoff_max`）并尝试刷新密钥重试；
- auto 模式下会自动切 RSS 兜底，不影响推送；
- 长期稳定建议自建 RSSHub（或 RSSWorker 部署到 Cloudflare Worker），
  把 `bdw_rss_base` 指向自建地址。

**怎么盯微博？**
- `bdw_mode=rss`，`bdw_rss_base` 指向（自建）RSSHub，
  `bdw_rss_route=weibo/user/{uid}`；
- 公共 RSSHub 实例的微博路由常要求登录 cookie，建议自建并配置 `WEIBO_COOKIES`；
- 推送文案会显示为「【动态】xxx 发布了新动态」。

**RSS 兜底没生效？**
- 检查 `bdw_rss_base` 是否可访问（服务器 curl `https://rsshub.app/bilibili/user/dynamic/208259`）；
- 公共实例可能限流，建议自建。

**换了平台（Telegram 等）？**
- `bdw_platform_id` 填对应适配器 ID，`bdw_groups` 填平台群会话 ID；
- 注意 QQ 官方接口不支持主动推送，请使用 OneBot v11 系（NapCat / Lagrange 等）。

**SESSDATA 安全提示**
- SESSDATA 是关注号登录凭证，明文存在服务器配置中，**建议使用小号**；不要粘贴到第三方环境。

## 依赖

- `aiohttp`（AstrBot 环境自带，见 `requirements.txt`）
- WBI 签名 / RSS 解析均为标准库实现（hashlib / urllib / xml.etree），无额外依赖

## Git

插件使用独立 git 仓库（master 分支），`.gitignore` 排除 `__pycache__` / `.ruff_cache` / `dist/`；
每次修改后提交，提交信息用 `v版本号: 改动说明` 风格。

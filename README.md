# 兔兔 - AstrBot B站动态监听插件

监听指定 B 站账号（UP主）的最新动态，**新动态自动推送到配置的 QQ 群**。纯后台轮询 + 主动推送，**不依赖 LLM**，对话不会被打扰。

> 插件 id：`bili_dynamic_watcher`　当前版本：`1.0.0`

## 工作原理

### 推荐：关注流模式（follow）

针对「频繁访问主页会被风控」的问题，本插件默认使用**关注流模式**：

1. 用一个**关注号**（普通 B 站账号即可）在 B 站关注所有要监听的 UP 主；
2. 插件用该账号的登录态（`SESSDATA` Cookie）低频拉取「关注动态流」接口；
3. 从返回结果中过滤出监听账号的动态，发现新的就推送到 QQ 群。

相比逐个轮询用户主页，**单接口低频请求**（默认 60 秒一次）更接近正常用户行为，大幅降低被风控（412）的概率。

### 备选：空间轮询模式（space）

免登录，直接按 UID 轮询用户空间动态接口。**不推荐大量账号使用**——高频访问主页接口容易被 B 站风控。仅适合少量账号 + 较大轮询间隔（≥120 秒）。

## 前置准备

1. **获取关注号的 SESSDATA（Cookie）**
   - 用浏览器登录 `bilibili.com`（建议用小号，不要用主号）
   - 按 `F12` → `Application` → `Cookies` → `https://www.bilibili.com`
   - 复制 `SESSDATA` 的值，填到插件配置 `bdw_sessdata`
   - `SESSDATA` 有效期约半年，失效后需重新获取（收到 code=-101 提示时即过期）
   - 注意：Cookie 列表里可能出现两条 `SESSDATA`（`.bilibili.com` 和 `.biligame.com` 域各一条），**请选择 Domain 为 `.bilibili.com` 的那条**（动态接口属于 bilibili.com 域；`.biligame.com` 那条是 B 站游戏站的，填了无效）
2. **（可选）获取 `buvid3`**：同样位置复制，填到 `bdw_buvid3`，可辅助降低风控概率
3. **关注目标账号**：用关注号在 B 站关注所有要监听的 UP 主
4. **获取目标 UID**：UP 主个人空间地址 `https://space.bilibili.com/<UID>` 中的数字
5. **填 QQ 群号**：插件配置 `bdw_groups` 中填入要推送的群号（每行一个）

## 安装

1. 打包（见下文）或直接使用仓库 `dist/` 下的 zip
2. AstrBot 管理面板 → 插件管理 → 安装插件 → 上传 zip
3. 在插件配置中填写：`bdw_sessdata`、`bdw_groups`、`bdw_uid_list`（或安装后用指令添加）
4. 插件加载后自动开始轮询；修改配置后建议在插件管理中点「重载插件」确保生效

## 配置项

| 配置项 | 说明 | 默认 |
| --- | --- | --- |
| `bdw_enabled` | 插件总开关 | `true` |
| `bdw_mode` | 拉取模式：`follow` 关注流（推荐）/ `space` 空间轮询 | `follow` |
| `bdw_sessdata` | 关注号登录 Cookie（SESSDATA），follow 模式必填 | 空 |
| `bdw_buvid3` | 浏览器 Cookie buvid3（可选，辅助防风控） | 空 |
| `bdw_uid_list` | 初始监听 UID 列表（每行一个；仅首次加载时写入） | `[]` |
| `bdw_groups` | 推送目标 QQ 群号（每行一个） | `[]` |
| `bdw_platform_id` | 推送平台适配器 ID（默认 `aiocqhttp`，即 OneBot v11） | `aiocqhttp` |
| `bdw_poll_interval` | 轮询间隔（秒），follow 默认 60，space 建议 ≥120 | `60` |
| `bdw_max_per_cycle` | 每轮最多推送条数（防刷屏） | `10` |
| `bdw_timeout` | 接口请求超时（秒） | `15` |
| `bdw_proxy` | HTTP 代理（如 `http://127.0.0.1:7890`），留空直连 | 空 |
| `bdw_permission_enabled` | 管理指令权限校验开关 | `true` |
| `bdw_admin_ids` | 可执行管理指令的用户 ID 白名单（每行一个） | `[]` |
| `bdw_admin_role` | 群内可执行管理指令的角色 | `["owner", "admin"]` |

> `bdw_uid_list` 只在首次加载时用于初始化本地监听列表；之后推荐用指令 `bd添加 / bd删除` 管理（数据保存在 `data/bili_dynamic_watcher/watched_uids.json`），这样不用每次改配置。

## 指令（免 LLM，需 @ 机器人或唤醒词）

| 指令 | 说明 | 权限 |
| --- | --- | --- |
| `bd列表` | 查看当前监听的账号 | 所有人 |
| `bd添加 <UID> [备注]` | 添加监听账号（如 `bd添加 208259 兔兔`） | 管理员 |
| `bd删除 <UID>` | 停止监听某账号 | 管理员 |
| `bd状态` | 查看运行状态（模式/登录态/间隔/推送群/最近轮询） | 所有人 |
| `bd测试` | 立即拉取一次并报告结果（**不推送、不记为已见**），用于排查配置 | 管理员 |

## 数据存储

运行数据保存在 AstrBot 数据目录（`get_astrbot_data_path()`）下：

- `data/bili_dynamic_watcher/watched_uids.json`：监听账号列表（UID → 备注）
- `data/bili_dynamic_watcher/seen_dynamics.json`：已推送过的动态 ID（防重复，最多保留 3000 条）

插件更新/重装不会覆盖这些数据。

## 打包

```bash
python plugins/astrbot/siwu-bili-dynamic-watcher-1_0/build.py
```

产物：`plugins/astrbot/dist/siwu-bili-dynamic-watcher-<version>.zip`（zip 内文件直接放根目录）。

## 常见问题

**收不到动态？**
1. `bd状态` 看总开关、监听账号、推送群是否正常；
2. `bd测试` 看能否拉取成功、是否命中未推送动态；
3. follow 模式下确认关注号**已在 B 站关注目标账号**，且 `SESSDATA` 未过期（过期会报 code=-101）；
4. 确认机器人已加入 `bdw_groups` 中的群，且 `bdw_platform_id` 与你的平台适配器一致。

**报错 412 / code=-352（风控）？**
- 增大 `bdw_poll_interval`；
- 补充 `bdw_buvid3`；
- 优先使用 follow 关注流模式（`bdw_mode=follow`）。

**换了平台（Telegram 等）？**
- 把 `bdw_platform_id` 改为对应适配器 ID（如 `telegram`），`bdw_groups` 填平台群会话 ID。
- 注意：QQ 官方接口平台不支持主动推送（AstrBot 限制），请使用 OneBot v11（go-cqhttp / NapCat / Lagrange 等）或支持主动消息的平台。

**Cookie 里有两条 SESSDATA，填哪条？**
- 选 **Domain 为 `.bilibili.com`** 的那条（通常 Cookie 列表里靠后的那条）；`.biligame.com` 的是游戏站登录态，动态接口不认。两条值很相似但中间段不同，不要填错。

**在 space/message/www 等多个子域下都看到 SESSDATA？**
- 若这些行的 **Domain 列都是 `.bilibili.com`（带点）**：它们是同一条域级 Cookie 在不同来源下的重复展示，值相同，任选一条填即可。
- 若 Domain 列是 `space.bilibili.com` / `message.bilibili.com` 这类**不带点**的主机级 Cookie：子域专属，**不会**被发送到 `api.bilibili.com`，填了无效。
- 最稳做法：F12 → Network → 刷新页面，点开任意 `api.bilibili.com` 请求 → Request Headers → Cookie 中找 `SESSDATA=xxx`，该值就是接口实际携带的登录态。

**SESSDATA 安全提示**
- `SESSDATA` 等于关注号的登录凭证，明文保存在 AstrBot 配置文件中，请妥善保管服务器权限，**建议使用小号**，不要把主账号凭证填入；也不要把它粘贴到聊天/论坛等第三方环境，测试完可去 B 站「设置 → 安全中心」清除登录态使其失效。

## 依赖

- `aiohttp`（AstrBot 环境自带，见 `requirements.txt`，安装插件时自动安装）

## Git

插件使用独立 git 仓库（master 分支），`.gitignore` 排除 `__pycache__` / `.ruff_cache` / `dist/`；每次修改后提交，提交信息用 `v版本号: 改动说明` 风格。

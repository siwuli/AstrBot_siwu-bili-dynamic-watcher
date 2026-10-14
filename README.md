# B站动态监听（bili_dynamic_watcher）

监听 B 站 UP 主与 RSS 源（含微博）的新动态，把动态与图片推送到群。

## 功能
- 监听多个 B 站 UP 主，新动态自动推送
- 推送可附带动态图片，最多 9 张
- 转发与抽奖类动态默认不推送
- 官方接口带 WBI 签名与风控自适应退避
- 支持 RSS 源兜底，可监听微博等平台
- 支持 Cookie 自动刷新（B站 Web 端刷新机制），登录态到期自动续期
- 免 LLM，纯后台轮询与主动推送

## 指令
| 指令（需 @ 或唤醒词） | 说明 | 权限 |
| --- | --- | --- |
| `bd列表` | 查看监听账号 | 所有人 |
| `bd本群` | 获取当前群的平台限定标识 | 所有人 |
| `bd添加 <UID> [备注]` | 添加监听 | 管理员 |
| `bd删除 <UID>` | 停止监听 | 管理员 |
| `bd状态` | 查看模式、数据源与退避状态 | 所有人 |
| `bd测试` | 立即拉取一次，不推送不记已见 | 管理员 |
| `bd刷新` | 立即刷新 B 站 Cookie 登录态 | 管理员 |

## 配置
| 配置项 | 默认 | 说明 |
| --- | --- | --- |
| `bdw_enabled` | true | 总开关 |
| `bdw_mode` | auto | 拉取模式，默认 auto |
| `bdw_sessdata` | 空 | 关注号 SESSDATA 凭证 |
| `bdw_buvid3` | 空 | 浏览器 buvid3，可自动获取 |
| `bdw_bili_jct` | 空 | Cookie 中的 bili_jct，自动刷新必需 |
| `bdw_refresh_token` | 空 | localStorage 的 ac_time_value，自动刷新必需 |
| `bdw_cookie_refresh` | true | 自动刷新 B 站 Cookie |
| `bdw_cookie_check_interval` | 3600 | 刷新检查间隔（秒，最小 300） |
| `bdw_uid_list` | [] | 初始监听 UID 列表，仅首次写入 |
| `bdw_warmup` | true | 首次启动只记录不推送历史 |
| `bdw_groups` | [] | 推送目标群号，每行一个 |
| `bdw_platform_id` | 空 | 推送平台适配器 ID |
| `bdw_poll_interval` | 120 | 基础轮询间隔（秒） |
| `bdw_backoff_max` | 3600 | 风控退避上限（秒） |
| `bdw_rss_base` | 空 | RSS 源地址 |
| `bdw_rss_route` | bilibili/user/dynamic/{uid} | RSS 路由模板 |
| `bdw_push_images` | true | 推送时附带动态图片 |
| `bdw_ignore_forward` | true | 忽略转发动态 |
| `bdw_ignore_lottery` | true | 忽略抽奖/中奖类动态 |
| `bdw_ignore_keywords` | 抽奖/中奖等 | 抽奖类忽略关键词 |
| `bdw_max_per_cycle` | 10 | 每轮最多推送条数 |
| `bdw_max_text_len` | 0 | 正文最大长度，0 为不截断 |
| `bdw_timeout` | 15 | 单请求超时（秒） |
| `bdw_proxy` | 空 | HTTP 代理（可选） |
| `bdw_permission_enabled` | true | 管理指令权限校验 |
| `bdw_admin_ids` | [] | 管理指令用户白名单 |
| `bdw_admin_role` | ["owner","admin"] | 群内管理指令角色 |

## Cookie 自动刷新（v2.3）
B 站 Web 端 Cookie 会因访问敏感接口逐步失效；本插件实现官方刷新流程：
定时检查 `cookie/info`，需要时用 `CorrespondPath`（RSA-OAEP）换取 `refresh_csrf`，
再调用 `cookie/refresh` 换取新 SESSDATA，并持久化到
`data/bili_dynamic_watcher/cookies.json`；轮询遇到 `-101` 也会立即刷新并重试。

需要额外填写两个值（与 `bdw_sessdata` 同一次登录）：
1. `bdw_bili_jct`：F12 → Application → Cookies → `.bilibili.com` → 复制 `bili_jct`；
2. `bdw_refresh_token`：F12 → Application → Local Storage → `https://www.bilibili.com` → 复制 `ac_time_value`。

每次刷新成功后 B 站会返回**新的** `refresh_token`，插件自动保存，无需手动更新。
注意：账号被强制下线或触发风控时 `refresh_token` 会一并失效，此时需重新登录并更新
`bdw_sessdata`（`bdw_bili_jct` / `bdw_refresh_token` 也需一并更新）。

## 安装
1. 上传插件 zip 安装，或解压到 `data/plugins/` 后重启 AstrBot。
2. 依赖：`aiohttp`（AstrBot 环境自带，见 `requirements.txt`）。
3. 用 `bd添加 <UID>` 添加监听账号，并配置 `bdw_groups` 指定推送群。

## 版本记录
| 版本 | 说明 |
| --- | --- |
| 2.3.0 | 新增 B 站 Cookie 自动刷新（bili_jct + ac_time_value） |
| 2.2.2 | 精简文档 |
| 2.2.1 | bd本群 优先推荐纯群号写法 |
| 2.2.0 | 群配置支持平台限定写法 |
| 2.1.4 | 正文默认完整推送，新增长度配置 |
| 2.1.0 | 推送附带图片，过滤转发与抽奖 |

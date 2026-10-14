# B站动态监听（bili_dynamic_watcher）

监听 B 站 UP 主与 RSS 源（含微博）的新动态，把动态与图片推送到群。

## 功能
- 监听多个 B 站 UP 主，新动态自动推送
- 推送可附带动态图片，最多 9 张
- 转发与抽奖类动态默认不推送
- 官方接口带 WBI 签名与风控自适应退避
- 支持 RSS 源兜底，可监听微博等平台
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

## 配置
| 配置项 | 默认 | 说明 |
| --- | --- | --- |
| `bdw_enabled` | true | 总开关 |
| `bdw_mode` | auto | 拉取模式，默认 auto |
| `bdw_sessdata` | 空 | 关注号 SESSDATA 凭证 |
| `bdw_buvid3` | 空 | 浏览器 buvid3，可自动获取 |
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

## 安装
1. 上传插件 zip 安装，或解压到 `data/plugins/` 后重启 AstrBot。
2. 依赖：`aiohttp`（AstrBot 环境自带，见 `requirements.txt`）。
3. 用 `bd添加 <UID>` 添加监听账号，并配置 `bdw_groups` 指定推送群。

## 版本记录
| 版本 | 说明 |
| --- | --- |
| 2.2.2 | 精简文档 |
| 2.2.1 | bd本群 优先推荐纯群号写法 |
| 2.2.0 | 群配置支持平台限定写法 |
| 2.1.4 | 正文默认完整推送，新增长度配置 |
| 2.1.0 | 推送附带图片，过滤转发与抽奖 |

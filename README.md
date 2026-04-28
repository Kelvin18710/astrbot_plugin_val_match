# astrbot_plugin_val_match

![插件图标占位](assets/icon.png)

AstrBot 的无畏契约赛程插件，默认使用 `VLR` 获取数据，开箱即用，默认按北京时间展示。

支持这些能力：

- 查询今天、明天、指定日期赛程
- 默认只看 `S` 级赛事
- 自定义“关注赛事”，按赛事名单精准过滤
- 生成多日赛程图片 `/val s`
- 显示已结束比分、进行中状态、未开始时间
- 每日定时推送
- 手动推送测试

上面的图标文件当前只是占位图，你后续可以直接替换 `assets/icon.png`。

## 安装

1. 将插件目录放入 AstrBot 的 `plugins` 目录。
2. 安装依赖：

```bash
pip install -r requirements.txt
```

3. 重启 AstrBot。
4. 到 WebUI 打开插件配置。

## 开箱即用推荐配置

大多数用户保持默认值就能直接用：

| 配置项 | 推荐值 |
| --- | --- |
| `default_levels` | `S` |
| `display_timezone` | `Asia/Shanghai` |
| `include_completed` | `true` |
| `fetch_bo_from_details` | `true` |
| `image_day_offsets` | `-1,0,1` |
| `enable_daily_push` | `false` |

配置完成后，先直接测试：

```text
/val today
/val s
/val debug
```

## 首次使用步骤

### 1. 先确认基础查询正常

依次测试：

```text
/val today
/val tomorrow
/val debug
```

如果 `/val today` 有返回，就说明主链路已经可用。

### 2. 配置你关注的赛事

如果你不想只按 `S` 级赛事过滤，而是想只看自己关心的联赛，推荐这样做：

1. 先执行：

```text
/val sync_events
```

2. 执行完成后，重载插件，或者至少刷新一次插件配置页。
3. 回到 WebUI，在 `关注赛事 preferred_tournaments` 中多选你关心的赛事。
4. 保存配置并再次重载插件。

常见选择例如：

- `VCT 2026: Americas Stage 1`
- `VCT 2026: China Stage 1`
- `VCT 2026: EMEA Stage 1`
- `VCT 2026: Pacific Stage 1`

配置完成后：

- `/val today` 会优先按关注赛事过滤
- `/val s` 也会优先按关注赛事渲染图片

### 3. 配置图片展示天数

`image_day_offsets` 控制 `/val s` 展示哪些日期。

示例：

- `0`：只看今天
- `-1,0,1`：昨天、今天、明天
- `0,1,2`：今天、明天、后天
- `-2,-1,0,1,2`：前后共 5 天

注意：

- 最多保留前 7 个偏移值
- 没有比赛的日期也会显示占位块，不会直接消失

### 4. 如果需要每日推送

打开：

- `enable_daily_push = true`

并配置：

| 配置项 | 说明 |
| --- | --- |
| `push_targets` | 每行一个目标 |
| `push_time` | 推送时间，格式 `HH:MM` |

示例：

```text
enable_daily_push = true
push_time = 09:00
push_targets =
aiocqhttp:123456789
```

`push_targets` 支持两种写法：

- 完整的 `unified_msg_origin`
- 简写 `platform_id:group_id`

配置完以后，可以先执行：

```text
/val push_test
```

这样不用等到定时点，也能先验证推送目标和消息发送是否正常。
当前 `push_test` 和每日定时推送，发送的都是和 `/val s` 同一套赛程图片。

## 指令说明

### `/val today`

查询今天比赛。

特点：

- 默认按 `default_levels` 过滤，默认是 `S`
- 默认包含今天已经结束的比赛
- 如果配置了关注赛事，则优先按关注赛事过滤

### `/val tomorrow`

查询明天比赛。

### `/val date YYYY-MM-DD`

查询指定日期比赛。

示例：

```text
/val date 2026-04-28
```

### `/val level S`

按等级查询今天比赛。

示例：

```text
/val level S
/val level A
/val level S,A
```

注意：

- 如果已经配置了关注赛事，这个命令会先按关注赛事筛，再按你手动传入的等级筛

### `/val s`

生成多日赛事图片。

特点：

- 默认展示昨天、今天、明天
- 队伍显示全名和队标
- 右侧显示赛事名、赛事阶段、赛事图标、等级
- 区分已结束 / 进行中 / 未开始三种状态色
- 空白日期会显示占位块

### `/val sync_events`

从 VLR 同步可选赛事列表到插件配置。

适用场景：

- 第一次配置关注赛事
- 新赛季开始后刷新赛事列表

注意：

- 执行完后，要重载插件，或者刷新插件配置页，WebUI 才能看到新的可选赛事

### `/val push_test`

立即向 `push_targets` 发送一张赛程图片，用于测试定时推送。

适用场景：

- 你刚配置完推送目标
- 你想确认机器人是否真的能发到目标群
- 你不想等到正式推送时间
- 你想确认图片推送是否正常

### `/val debug`

输出当前调试信息，适合排查：

- 当前请求是否成功
- 当前时区是否正确
- 当前是否命中缓存
- 当前默认等级过滤和关注赛事是否生效
- 图片命令的日期范围是什么

## 配置项说明

### 核心配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `default_levels` | `S` | 文本命令默认等级过滤 |
| `preferred_tournaments` | `[]` | 关注赛事，多选 |
| `image_day_offsets` | `-1,0,1` | `/val s` 的日期范围 |
| `display_timezone` | `Asia/Shanghai` | 输出展示时区 |
| `include_completed` | `true` | 文本查询时是否包含已结束比赛 |

### 请求与缓存

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `request_timeout_seconds` | `10` | HTTP 请求超时秒数 |
| `retry_count` | `2` | 请求失败时的重试次数 |
| `cache_ttl_seconds` | `300` | 赛程和详情缓存秒数 |
| `max_matches_per_message` | `20` | 文本消息最多显示多少场 |
| `fetch_bo_from_details` | `true` | 是否访问详情页补全 BO |
| `max_detail_fetch_matches` | `12` | 一次最多补全多少场 BO |

### VLR 相关

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `vlr_api_url` | `https://vlrggapi.vercel.app` | 优先尝试的公开 API |
| `vlr_web_base_url` | `https://www.vlr.gg` | VLR 网页地址 |
| `vlr_schedule_pages` | `3` | 赛程页最多扫描页数 |
| `vlr_results_pages` | `3` | 结果页最多扫描页数 |

### 推送相关

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `enable_daily_push` | `false` | 是否启用每日推送 |
| `push_time` | `09:00` | 推送时间 |
| `push_targets` | 空 | 推送目标列表 |

## 时间与时区说明

插件默认按 `Asia/Shanghai` 展示时间。

当前时间处理策略：

1. 优先读取 VLR 详情页展示出来的比赛时间
2. 同时读取详情页中的 UTC 时间信息做校验
3. 统一转换到 `display_timezone`
4. 按转换后的日期归类到今天 / 明天 / 昨天

这样做的目的，是尽量避免：

- 代理 IP 所在地区导致网页时间偏掉
- 仅靠网页列表页时间时出现日期归类错误

如果你在中国使用，建议保持：

```text
display_timezone = Asia/Shanghai
```

## 数据源逻辑

插件当前只使用 `VLR`。

实际行为：

1. 先尝试 `vlrggapi.vercel.app`
2. 如果 API 不稳定，回退到 `www.vlr.gg` 页面解析

默认情况下不需要额外配置。

## 常见使用方案

### 方案一：只看 S 级赛事

保持默认配置即可：

```text
default_levels = S
preferred_tournaments = []
```

### 方案二：只看四大 VCT 联赛

先同步赛事列表，再在 WebUI 中选择：

- `VCT 2026: Americas Stage 1`
- `VCT 2026: China Stage 1`
- `VCT 2026: EMEA Stage 1`
- `VCT 2026: Pacific Stage 1`

这时即使某些比赛等级标记不稳定，也能按赛事名称准确过滤。

### 方案三：做群内每日提醒

推荐配置：

```text
default_levels = S
display_timezone = Asia/Shanghai
enable_daily_push = true
push_time = 09:00
push_targets =
aiocqhttp:123456789
```

配置完先执行一次：

```text
/val push_test
```

确认没问题后，再等正式定时推送。

## 排查指南

### `today` 查不到比赛

先检查：

1. 有没有配置 `preferred_tournaments`
2. 配置的赛事名是不是当前确实有比赛
3. `default_levels` 是否过滤得过严
4. `/val debug` 里“过滤后比赛数量”是多少

### 图片里某一天没有比赛

这是正常的。

现在 `/val s` 会保留空白日期，并显示：

- `此日无关注比赛`

如果你想扩大范围，可以把：

```text
image_day_offsets = -2,-1,0,1,2
```

### 时间不对

先检查：

```text
display_timezone = Asia/Shanghai
```

然后执行：

```text
/val debug
```

确认：

- 展示时区
- 当前插件时间
- VLR 页面时区推断
- VLR 详情时间来源

### `/val sync_events` 之后还是选不到赛事

一般是：

- 还没重载插件
- WebUI 没刷新
- 当前 VLR 页里暂时没有扫到你要的赛事

可以重新执行一次：

```text
/val sync_events
```

然后重载插件，再回到 WebUI 查看。

### 定时推送没发出来

先检查：

1. `enable_daily_push` 是否开启
2. `push_targets` 是否填写正确
3. `push_time` 是否是 `HH:MM`
4. 机器人本身是否有往目标群发消息的权限

然后先执行：

```text
/val push_test
```

如果这个都发不出去，优先先排查目标配置或机器人发信权限。

## 目录说明

```text
astrbot_plugin_val_match/
├── assets/                    # 图标等静态资源
│   └── icon.png              # 当前占位图，可直接替换
├── clients/                  # 数据源客户端
├── artifacts/                # 运行期缓存与渲染产物
├── main.py                   # AstrBot 插件入口
├── render.py                 # 图片渲染
├── _conf_schema.json         # WebUI 配置定义
├── metadata.yaml             # 插件元信息
└── requirements.txt          # 依赖
```

## 说明

- 运行中生成的队标缓存和渲染图片会放在 `artifacts/`
- 仓库已经通过 `.gitignore` 忽略这些运行期文件
- 如果你要更换插件图标，优先替换 `assets/icon.png`

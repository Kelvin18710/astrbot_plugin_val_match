<div align="center">

![VAL Match：比赛有人提醒，胜队一起选](https://raw.githubusercontent.com/Kelvin18710/astrbot_plugin_val_match/v0.9.0/docs/images/hero.png)

**把无畏契约的赛程、战报和竞猜，带进你的群聊。**

[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.28.1-526ad9)](https://astrbot.app)
[![Release](https://img.shields.io/github/v/release/Kelvin18710/astrbot_plugin_val_match?color=e76f7d&label=release)](https://github.com/Kelvin18710/astrbot_plugin_val_match/releases/latest)
[![Tests](https://github.com/Kelvin18710/astrbot_plugin_val_match/actions/workflows/test.yml/badge.svg)](https://github.com/Kelvin18710/astrbot_plugin_val_match/actions/workflows/test.yml)
[![MIT](https://img.shields.io/badge/license-MIT-19876a)](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.9.0/LICENSE)

[看效果](#先看看它能为你的群做什么) · [全场赛果](#全场比赛赛果一张图复盘整场) · [安装](#安装后先试一句) · [上手指南](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.9.0/docs/QUICKSTART.md) · [配置参考](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.9.0/docs/CONFIGURATION.md)

</div>

今天谁打谁？几点开赛？打完谁表现最好？让机器人整理这些信息，群友只需要看比赛、聊比赛，点一下选出自己看好的胜队。

## 29 秒，看看群里怎么玩

[![点击观看：点表情选胜队、改选，赛后与机器人一起看榜](https://raw.githubusercontent.com/Kelvin18710/astrbot_plugin_val_match/main/docs/promo/preview.gif)](https://github.com/user-attachments/assets/f48709d8-18eb-4285-bba3-1e00a9e393c2)

**点表情选队 → 点另一边改选 → 看完整战报 → 与机器人一起上榜。** 点击动图观看带声音的 1080p 演示。

[观看横版完整视频](https://github.com/user-attachments/assets/f48709d8-18eb-4285-bba3-1e00a9e393c2) · [下载手机竖版](https://github.com/Kelvin18710/astrbot_plugin_val_match/releases/download/v0.9.0/val-match-vertical.mp4) · [下载海报、视频和推广文案](https://github.com/Kelvin18710/astrbot_plugin_val_match/releases/download/v0.9.0/VAL-Match-promo-kit.zip) · [插件市场安装](https://cloud.astrbot.app/plugin/Kelvin18710/astrbot_plugin_val_match)

画面为功能演示，群聊框为交互示意；竞猜、昵称、头像和统计使用虚构数据，全场战报为历史比赛样例。

## 先看看它能为你的群做什么

| 你想做的事 | VAL Match 来帮你 |
| --- | --- |
| 一眼看懂今天的赛程 | 横向对阵卡片、大队标、开赛时间和状态；可查看昨天、今天与明天 |
| 关注喜欢的联赛 | 多选特别关心赛事，定时发赛程，开赛时提醒，结束后发战报 |
| 看完比赛回顾表现 | 地图比分与十名选手完整数据，保留头像、国家、英雄和关键统计 |
| 让群友一起参与 | QQ / NapCat 可直接点表情选胜队；也可 @机器人用自然语言参与、修改，一句话报多场 |
| 比比谁猜得更准 | 群与赛事独立积分、前三名奖牌、胜负正确率；可等比赛全部结束后自动发榜 |
| 给机器人也留个席位 | 开启机器人参赛，它独立预测，同样计分，群友不能替它修改 |

### 一张图，把赛程说清楚

![赛事日历：时间固定在左侧，两队横向对阵](https://raw.githubusercontent.com/Kelvin18710/astrbot_plugin_val_match/v0.9.0/docs/examples/schedule.png)

### 开赛提醒，看看双方的赛前支持率

![开赛提醒：队标、赔率与支持率对比](https://raw.githubusercontent.com/Kelvin18710/astrbot_plugin_val_match/v0.9.0/docs/examples/notice.png)

### 全场比赛赛果，一张图复盘整场

谁赢了、每张地图怎么打、选手表现如何，整场结束后的战报放在一张图里：**系列赛总比分与胜队、各地图比分与选图方、地图时长，以及两队十名选手的整场数据**。

选手区保留头像、国家与使用英雄，展示 **Rating、ACS、K/D/A、K/D 差值、KAST、ADR、爆头率和首杀 / 首死**；底部可附带赛后锐评。

下面是 **NRG vs FNATIC · BO5 打满五张地图** 的历史全场战报，展示从总比分到十名选手统计的完整布局。

![全场比赛赛果：NRG 3:2 FNATIC，五张地图结果与两队十名选手整场数据](https://raw.githubusercontent.com/Kelvin18710/astrbot_plugin_val_match/v0.9.0/docs/examples/report.png)

[查看高清全场赛果原图 →](https://raw.githubusercontent.com/Kelvin18710/astrbot_plugin_val_match/v0.9.0/docs/examples/report.png)

图片为历史赛事样例，顶部封面为使用场景示意。支持 **Studio 炭黑 / 暖白** 两套主题。

## 安装后，先试一句

需要 **AstrBot ≥ 4.28.1、< 5**、**Python ≥ 3.12**。目前已验证 **Linux + OneBot v11（aiocqhttp）**。

在 AstrBot「插件 → 安装插件」中粘贴仓库地址：

```text
https://github.com/Kelvin18710/astrbot_plugin_val_match
```

安装后，在已接入的群里发送：

```text
/val today
```

**先查赛程，不用申请额外 API Key，也不用先配置 AI。** 默认使用北京时间，展示 S 级赛事；选好特别关心赛事后，按所选赛事展示。

想看图片？运行 AstrBot 的环境需要中文字体。Debian / Ubuntu（包括 Docker 容器内）执行：

```bash
apt-get update
apt-get install -y fonts-noto-cjk
```

然后发 `/val s`，就能拿到赛事日历。AstrBot 会自动安装 `requirements.txt` 中的 Python 依赖。

## 把观赛搬进群里，只要三步

打开 **AstrBot 插件详情 → 赛事控制台 → 使用指南**。指南显示已保存的配置进度，按钮可直接定位到对应设置。

1. **选赛事**：搜索并勾选「特别关心赛事」，可以多选；没找到就点「更新赛事列表」。
2. **选玩法和群**：想要提醒，就开每日赛程或开赛 / 赛后推送；想一起选胜队，再开启群内竞猜并选择竞猜群。
3. **保存并试用**：点击「保存设置」，回群里发 `/val s`；开启竞猜的群再 @机器人说「今日竞猜」。

推送群可以直接勾选。**每日赛程、开赛 / 战报、竞猜分别选择目标群**，只启用你需要的功能。

可以选择「每日赛程推送方式 → 首场赛前」，提前分钟数填 **120**：每天首场前两小时发赛程，今日竞猜紧随其后；全部比赛结束、积分结算且本群战报发送成功后，再发积分榜。无比赛当天不推送，开赛时间变化会重新计算，跨午夜的比赛继续等待。也可保留固定时间模式。

[跟着完整上手指南配置 →](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.9.0/docs/QUICKSTART.md)

## 竞猜，每场二选一，点一下就参与

**只猜胜负，不用填写比分。** QQ / NapCat 群每场收到一张 720×300 横向卡片，「摸鱼 / 摸锦鲤」两个 QQ 表情分别代表两队；点下方对应表情选择胜队，点另一个即可修改，无需打字或 @。

在控制台「设置 → 点选胜队」开启功能并勾选群，正式参与的群也需加入「竞猜目标群」。可以关闭「点选成功后发送确认回复」减少刷屏；关闭后选择照常保存，封盘或处理失败仍会提醒。

也支持真正 @机器人，用自然语言参与：

| 想做什么 | @机器人后说 |
| --- | --- |
| 看今天能猜哪些比赛 | 今日竞猜 |
| 参加竞猜 | 我猜 EDG 赢 |
| 改主意了 | 把 EDG 那场改成 PRX 赢 |
| 一次猜两场 | 我猜 EDG 赢，FNC 赢 |
| 一次改两场 | 把 EDG 那场改成 PRX 赢，然后把 FNC 那场改成 DRX 赢 |
| 看自己的记录 | 我的竞猜 |
| 看群排名 | 积分榜 |
| 忘了规则 | 竞猜怎么玩 |

**猜中胜队得 2 分，猜错 0 分。** 仅开放今日比赛，开赛前 10 分钟封盘，提前开赛也会封盘。每人每场以最后一次有效选择为准；取消表情不撤销竞猜。表情回应数量不代表有效竞猜人数，机器人预放的表情只是入口。

每项赛事从 **0 分** 开始，按“群＋赛事”独立计分，机器人同样参与。旧赛事的比分竞猜和积分保留，旧竞猜仍按原规则结算，新竞猜不再计算比分奖励。

直接 @机器人说“积分榜”查看当前关注赛事；同时关注多项赛事时分别展示。说“冠军赛积分榜”或“冠军赛我的竞猜”可以回看历史，控制台也可切换赛事查看和发送榜单。

积分榜以图片展示，上方赛果区每行两场，包含队标、比分和本群猜中胜队成员的头像；未结束的比赛显示状态。排名保留成员头像、积分、胜负正确率与分母，以及近五场命中记录；底部「竞猜荣誉榜」展示 **连准纪录、命中率之星、参与达人**，获奖成员均带头像，并列者一同展示。正确率只统计本人在该赛事参与且已结算的场次；没参加、尚未结算的比赛不进分母，也不打断已结算参与场次的连准纪录。超过 24 人时自动分页。

### 点一下选胜队，赛后一起看榜

![点选胜队：一场一张卡片，点击对应 QQ 表情参与或改选](https://raw.githubusercontent.com/Kelvin18710/astrbot_plugin_val_match/v0.9.0/docs/examples/prediction.png)

![图片积分榜：当日赛果、猜中成员、胜负正确率与竞猜荣誉榜](https://raw.githubusercontent.com/Kelvin18710/astrbot_plugin_val_match/v0.9.0/docs/examples/leaderboard.png)

积分榜样例使用虚构群名、昵称、头像和统计数据，仅展示布局。

## 控制台，把下一场和群里的进展放在一起

赛程时间轴标出「现在」，用状态色区分未开始、进行中与已结束；竞猜、积分榜、待结算记录和设置都在 AstrBot 内查看。

![使用指南：按需要选择功能并查看配置进度](https://raw.githubusercontent.com/Kelvin18710/astrbot_plugin_val_match/v0.9.0/docs/examples/guide.png)

上图为首次使用界面示意。后台任务与事件记录按需展开，无需另外打开一个管理网站。

## 常用入口

| 命令 | 用途 |
| --- | --- |
| `/val today` / `/val tomorrow` | 今天 / 明天的文字赛程 |
| `/val s` | 多日赛事日历图片 |
| `/val progress` | 赛事积分榜或淘汰晋级图 |
| `/val sync_events` | 更新可选赛事列表 |
| `/val monitor` | 查看控制台入口说明 |
| `/val debug` | 排查数据源与配置问题 |

## 遇到问题，先看这里

- **没有比赛？** 检查日期和特别关心赛事。休赛日不会强行生成比赛；赛制或时间尚未确认的比赛也不会开放竞猜。
- **图片没有中文？** 把 `fonts-noto-cjk` 安装在 AstrBot 实际运行的环境里，Docker 部署要装在容器内。
- **竞猜没响应？** 确认已开启群内竞猜、当前群已加入竞猜目标，而且消息里有真实的 @机器人。
- **没有 AI 模型能用吗？** 赛程、提醒、图片、成员竞猜和积分结算都能用；机器人独立预测需要模型，AI 战报锐评在不可用时回退到本地社区摘要。
- **升级会清空积分吗？** 竞猜与积分保存在插件数据目录的 `predictions.sqlite3`，正常升级 / 重载会保留。不要删除该数据文件。

更多问题见 [上手指南](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.9.0/docs/QUICKSTART.md) 和 [配置与命令参考](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.9.0/docs/CONFIGURATION.md)。遇到异常可在 [Issues](https://github.com/Kelvin18710/astrbot_plugin_val_match/issues) 提供版本、操作步骤和脱敏报错。

---

赛程与赛果来自 **VLR.gg**，需要运行环境能访问数据源；展示与提醒以数据源同步状态为准。更新记录见 [CHANGELOG](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.9.0/CHANGELOG.md)。代码采用 [MIT](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.9.0/LICENSE)，外部赛事素材权利归各自权利人，见 [资源说明](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.9.0/assets/ATTRIBUTION.md)。

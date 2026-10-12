<div align="center">

![VAL Match：比赛有人提醒，比分一起猜](https://raw.githubusercontent.com/Kelvin18710/astrbot_plugin_val_match/v0.8.2/docs/images/hero.png)

**把无畏契约的赛程、战报和竞猜，带进你的群聊。**

[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.28.1-526ad9)](https://astrbot.app)
[![Release](https://img.shields.io/github/v/release/Kelvin18710/astrbot_plugin_val_match?color=e76f7d&label=release)](https://github.com/Kelvin18710/astrbot_plugin_val_match/releases/latest)
[![Tests](https://github.com/Kelvin18710/astrbot_plugin_val_match/actions/workflows/test.yml/badge.svg)](https://github.com/Kelvin18710/astrbot_plugin_val_match/actions/workflows/test.yml)
[![MIT](https://img.shields.io/badge/license-MIT-19876a)](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.8.2/LICENSE)

[看效果](#先看看它能为你的群做什么) · [安装](#安装后先试一句) · [上手指南](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.8.2/docs/QUICKSTART.md) · [配置参考](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.8.2/docs/CONFIGURATION.md)

</div>

今天谁打谁？几点开赛？打完谁表现最好？让机器人整理这些信息，群友只需要看比赛、聊比赛，再报一个自己的预测比分。

## 先看看它能为你的群做什么

| 你想做的事 | VAL Match 来帮你 |
| --- | --- |
| 一眼看懂今天的赛程 | 横向对阵卡片、大队标、开赛时间和状态；可查看昨天、今天与明天 |
| 关注喜欢的联赛 | 多选特别关心赛事，定时发赛程，开赛时提醒，结束后发战报 |
| 看完比赛回顾表现 | 地图比分与十名选手完整数据，保留头像、国家、英雄和关键统计 |
| 让群友一起参与 | @机器人，用自然语言猜比分、修改预测，一句话也能报多场 |
| 比比谁猜得更准 | 群独立积分、前三名奖牌、胜负正确率；可等比赛全部结束后自动发榜 |
| 给机器人也留个席位 | 开启机器人参赛，它独立预测，同样计分，群友不能替它修改 |

### 一张图，把赛程说清楚

![赛事日历：时间固定在左侧，两队横向对阵](https://raw.githubusercontent.com/Kelvin18710/astrbot_plugin_val_match/v0.8.2/docs/examples/schedule.png)

### 从赛前期待，到赛后复盘

![开赛提醒：队标、赔率与支持率对比](https://raw.githubusercontent.com/Kelvin18710/astrbot_plugin_val_match/v0.8.2/docs/examples/notice.png)

<details>
<summary><strong>展开查看完整战报 · 五张地图与十名选手数据</strong></summary>

![完整战报](https://raw.githubusercontent.com/Kelvin18710/astrbot_plugin_val_match/v0.8.2/docs/examples/report.png)

</details>

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
2. **选玩法和群**：想要提醒，就开每日赛程或开赛 / 赛后推送；想一起猜比分，再开启群内竞猜并选择竞猜群。
3. **保存并试用**：点击「保存设置」，回群里发 `/val s`；开启竞猜的群再 @机器人说「今日竞猜」。

推送群可以直接勾选。**每日赛程、开赛 / 战报、竞猜分别选择目标群**，只启用你需要的功能。

不知道时间怎么安排？可以这样搭配：**14:00 发赛程 → 今日竞猜紧随其后 → 全部比赛结束并结算后发积分榜**。时间可自由调整，赛后模式也会等待跨午夜的比赛。

[跟着完整上手指南配置 →](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.8.2/docs/QUICKSTART.md)

## 竞猜，说出你的比分就行

以下以今日有 EDG 对阵 PRX 为例。**在聊天软件中真正 @机器人**，再输入内容；不用记比赛编号。

| 想做什么 | @机器人后说 |
| --- | --- |
| 看今天能猜哪些比赛 | 今日竞猜 |
| 参加竞猜 | 我猜 EDG 2比1 赢 PRX |
| 改主意了 | 把 EDG 那场改成 2:0 |
| 一次猜两场 | 我猜 EDG 2:1 赢 PRX，FNC 2:0 赢 DRX |
| 一次改两场 | 把 EDG 那场改成 2:0，然后把 FNC 那场改成 1:2 |
| 看自己的记录 | 我的竞猜 |
| 看群排名 | 积分榜 |
| 忘了规则 | 竞猜怎么玩 |

**猜的是整场地图比分**：BO3 可以是 2:0、2:1 或反向比分；不是单图的 13:8。不符合赛制的比分会提示重新填写。批量竞猜逐场反馈，一场出错不影响其他明确有效的竞猜。

每人从 **0 分** 开始，各群独立：

| 本场结果 | 获得积分 |
| --- | ---: |
| 猜中胜队 | **2 分** |
| 胜队与比分都猜中 | **5 分**（2 分 + 比分奖励 3 分） |
| 胜队没猜中 | **0 分** |

只开放今日比赛，**开赛前 10 分钟封盘**；提前开赛也会封盘。截止前可以改，每场以最后一次有效预测为准。

积分榜的 **胜负正确率** 只统计本人参与且已结算的场次。没参加的比赛、尚未结算的比赛都不算进分母；胜队猜对就算正确，不要求比分完全命中。

## 控制台，把下一场和群里的进展放在一起

赛程时间轴标出「现在」，用状态色区分未开始、进行中与已结束；竞猜、积分榜、待结算记录和设置都在 AstrBot 内查看。

![使用指南：按需要选择功能并查看配置进度](https://raw.githubusercontent.com/Kelvin18710/astrbot_plugin_val_match/v0.8.2/docs/examples/guide.png)

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

更多问题见 [上手指南](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.8.2/docs/QUICKSTART.md) 和 [配置与命令参考](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.8.2/docs/CONFIGURATION.md)。遇到异常可在 [Issues](https://github.com/Kelvin18710/astrbot_plugin_val_match/issues) 提供版本、操作步骤和脱敏报错。

---

赛程与赛果来自 **VLR.gg**，需要运行环境能访问数据源；展示与提醒以数据源同步状态为准。更新记录见 [CHANGELOG](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.8.2/CHANGELOG.md)。代码采用 [MIT](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.8.2/LICENSE)，外部赛事素材权利归各自权利人，见 [资源说明](https://github.com/Kelvin18710/astrbot_plugin_val_match/blob/v0.8.2/assets/ATTRIBUTION.md)。

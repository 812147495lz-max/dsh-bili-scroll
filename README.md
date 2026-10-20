# BiliPick

**[简体中文](README.md) · [English](README.en.md)**

> 每天按你设定的**类别与条数**，从 B站 精选视频，自动加入「稍后再看」，并生成一份带理由的日报。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](#快速开始)
[![API](https://img.shields.io/badge/API-OpenAI%20%7C%20Anthropic%20%7C%20Gemini%20%7C%20JSONL-8A2BE2.svg)](#支持的模型-api)

![BiliPick 界面](docs/screenshot.png)

> ## ⚠️ 与上游项目的关系：几乎是完全重写
>
> 本项目 fork 自 [dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll)，但**不是它的补丁或分支，而是几乎重做**：
>
> - **代码零复用**：原版是 DSH 插件（`index.js` / `client.js` / `lib/*` / 内置 Python MCP）；本项目是独立的 `app.py` + `engine.py` + `web/index.html`，不依赖 DSH。
> - **只沿用产品思路**：每天替你刷 B站、读字幕挑值得的、把好的送到你面前，以及原版值班章程里踩出来的经验。
> - **形态与功能差异很大**，逐项对照见 [docs/CHANGES.md](docs/CHANGES.md)。

---

## 为什么用它

- **按类别配额选片**：科技 / 科普 / 生活 / ACGN / 其他，默认 **5 / 5 / 5 / 10 / 5 = 30 条/天**；类别可增删，条数、关键词、门槛都可改。
- **读字幕 + 读评论再下判断**：模型必须引用字幕原句作为依据；高赞评论骂「标题党/注水」扣分，补干货加分。
- **质量门槛**：播放 / 点赞 / 收藏 / 弹幕 / 评论 合成分，低于类别下限不进候选；评分不够不凑数。
- **只进「稍后再看」**：不发公开评论、不 @ 人、不碰发视频/动态/私信，零社交副作用。
- **四路去重**：已关注 UP（全量）、B站 观看历史、历史推荐、当前稍后再看；**每天只挑满一次**。
- **成本可控**：默认 **¥3/天、10 分钟/轮**，超限自动收尾；按空闲/高峰分时记账。
- **多模型协议**：OpenAI 兼容 / Anthropic / Gemini / 自定义 JSONL，Key 与模型留空由你填。
- **独立运行**：本地浏览器界面，只监听 `127.0.0.1` + 随机 token；Windows 可打包成**免 Python** 的目录。

## 它怎么工作

```text
类别关键词 × 2 种排序（近 N 天）
        │
        ▼
免费过滤：已关注 UP / 观看历史 / 历史推荐 / 当前稍后再看 / 排除词 / 质量分下限
        │
        ▼
每类按质量分排序 → 模型粗排（标题·简介·UP·时长·播放）
        │
        ▼
每类前 N 条抓【字幕 + 高赞评论】
        │
        ▼
模型精判：0–10 分 + 字幕原句依据 + 评论信号
        │
        ▼
按配额取最高分 → 加入「稍后再看」→ 写日报（含每轮花费）
```

## 快速开始

### 方式一：免安装（Windows）

1. 下载 [BiliPick-win64.zip](https://github.com/812147495lz-max/dsh-bili-scroll/releases)（或自行 `build-exe.bat` 打包）
2. 解压，双击 `BiliPick.exe`
3. 浏览器自动打开 <http://127.0.0.1:61420/>

> 未签名的 PyInstaller 程序可能被 Windows Defender 误报，需要「允许保留」或把解压目录加入排除。

### 方式二：源码运行

```bash
git clone https://github.com/812147495lz-max/dsh-bili-scroll.git
cd dsh-bili-scroll
git checkout bilipick

python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # Windows
# .venv/bin/pip install -r requirements.txt     # macOS / Linux
.venv\Scripts\python app.py                     # 或 python app.py
```

需要 **Python 3.10+**。打包 Windows 免 Python 版：`build-exe.bat`。

## 使用

1. **API 与模型**：选协议、填 API Key（仅存本机 `data/config.json`）
2. **B站 账号**：扫码登录（仅存本机 `data/credential.json`）
3. **类别与配额**：调整类别、关键词、每天条数、精判条数、质量分/评分下限
4. 顶部「保存」→「开始跑一轮」；跑完在「日报」里看结果与花费

## 类别与判据

| 参数 | 作用 |
|---|---|
| 关键词 | 该类用于搜索与归类 |
| 每天条数 | 该类每天要几条（总配额 = 各类之和） |
| 精判上限 | 该类最多精读多少条（越多越慢越贵，越准） |
| 质量分下限 | 播放/点赞/收藏/弹幕/评论 合成分门槛 |
| 评分下限 | 模型 0–10 分门槛，不达标不收 |

默认质量分参考：科技 12 · 科普 12 · 生活 14 · ACGN 15 · 其他 12。

## 支持的模型 API

| 协议 | 默认 Base URL | 默认模型 |
|---|---|---|
| **OpenAI 兼容**（DeepSeek / Moonshot / 通义 / Ollama / vLLM / one-api …） | `https://api.deepseek.com` | `deepseek-flash` |
| **Anthropic** | `https://api.anthropic.com` | `claude-sonnet-4-5` |
| **Gemini** | `https://generativelanguage.googleapis.com` | `gemini-2.5-pro` |
| **自定义 JSONL**（JSON 响应或 `data: {...}` 流式） | 自填完整 URL | 自填 |

## 去重与预算

- **去重**：已关注 UP（全量拉取）、B站 观看历史、历史推荐/评估记录、当前「稍后再看」
- **每日配额**：当天已挑够配额时，再点会直接跳过；次日自动恢复
- **预算**：默认 ¥3/天（停止阈值 90%），逐次调用记账；超预算或超时间自动收尾并在日报里注明

## 项目结构

```text
app.py            本地 HTTP 服务 + 浏览器界面（单实例 / 随机 token）
engine.py         搜索 · 分类 · 质量分 · 去重 · 粗排 · 精判 · 稍后再看 · 日报
web/index.html    前端（原生 JS，无构建）
requirements.txt  bilibili-api-python / aiohttp / qrcode / Pillow
start.bat         源码方式启动
setup.bat         创建 venv 并安装依赖
build-exe.bat     PyInstaller 打包（onedir，免 Python）
docs/CHANGES.md   相对上游的逐项差异
data/             运行时数据（配置 / 凭证 / 日报 / 花费；已 gitignore）
```

## 常见问题

<details>
<summary><b>打开后显示「B站 已登录」是别人的账号？</b></summary>

不是。程序单实例：当你已经有一个 BiliPick 在运行时，双击任何副本都只会打开那个已在运行的实例。数据在 `data/`，跟着程序目录走。
</details>

<details>
<summary><b>为什么点了「开始跑一轮」没有反应？</b></summary>

看「运行」页日志：① 没填 API Key；② 没登录 B站；③ 今天已经挑够配额（会直接跳过，次日恢复，或调大类别条数）。
</details>

<details>
<summary><b>Windows Defender 报毒 / 删掉 exe？</b></summary>

PyInstaller 未签名程序的常见误报。加入排除目录，或从源码运行。
</details>

<details>
<summary><b>数据会上传吗？</b></summary>

不会。全部在本机 `data/`，API Key 与 B站 凭证都只存在本地文件。分发包不含任何个人数据。
</details>

## Roadmap

- [ ] 一键导出「干净副本」（不含 `data/`）
- [ ] GitHub Release 自动构建 Windows 包
- [ ] 日报里的「有用 / 没用 / 看过了」反馈闭环
- [ ] 更多类别模板与导入导出配置

## 贡献

欢迎 issue / PR。改动前请先看 [docs/CHANGES.md](docs/CHANGES.md) 了解与上游的关系；提交信息用中文或英文均可。

## 许可与致谢

[MIT](LICENSE) © 2026 BiliPick contributors

- 产品思路与值班章程经验：[c1overzz/dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll)（MIT）
- B站 接口：[bilibili-api-python](https://github.com/Nemo2011/bilibili-api)（MIT）、[adoresever/bilibili-mcp](https://github.com/adoresever/bilibili-mcp)（MIT）

本项目为独立重写实现，与上述项目无隶属关系。

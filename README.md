# BiliPick

每天按你设定的**类别与条数**，从 B站 精选视频，自动加入「稍后再看」，并生成带理由的日报。

> ## ⚠️ 与上游项目的关系：几乎是完全重写
>
> 本项目 fork 自 [dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll)，但**不是它的补丁或分支，而是几乎重做**：
>
> - **代码零复用**：原版是 DSH 插件（`index.js` / `client.js` / `lib/*` / 内置 Python MCP）；本项目是独立的
>   `app.py` + `engine.py` + `web/index.html`，不依赖 DSH，接口层直接调 `bilibili-api-python`。
> - **只沿用产品思路**：每天替你刷 B站、读字幕挑值得的、把好的送到你面前；以及原版值班章程里踩出来的经验
>   （空字幕=没语音、硬字幕读不到、失败不重试、必须引用原文）。
> - **形态与功能差异很大**：插件 → 独立 App；评论 @ → 只进稍后再看；关键词巡检 → 类别配额；
>   新增观众评论判据、质量分、四路去重、预算/时间双上限、四种 API 协议、免 Python 的 Windows 包。
>   逐项对照见 [docs/CHANGES.md](docs/CHANGES.md)。
>
> 请把本项目当作一个**新的独立应用**来用和评估，而不是原插件的升级版。

## 特性

- **类别配额**：科技 / 科普 / 生活 / ACGN / 其他，默认 5/5/5/10/5 = 30 条/天；类别可增删、条数可改
- **不限时长**，但要「精品」：播放/点赞/收藏/弹幕/评论 合成分 + 字幕/评论精读打分，低于阈值不收
- **读观众评论**：高赞骂标题党/注水扣分，补干货加分
- **四路去重**：已关注 UP（全量拉取）、B站 观看历史、历史推荐、当前稍后再看
- **每天只挑满一次**，避免重复推荐
- **预算与时间上限**：默认 ¥3/天、10 分钟/轮，超限自动停；按空闲/高峰分时计价记账
- **多 API 协议**：OpenAI 兼容 / Anthropic / Gemini / 自定义 JSONL；API Key 与模型留空由使用者填
- **独立运行**：浏览器界面 + 本地服务（`127.0.0.1` + 随机 token），单实例；可打包成免 Python 的 Windows exe
- **数据全本地**：`data/`（配置、凭证、去重、日报、花费），分发包不含任何个人数据

## 运行（源码方式）

需要 Python 3.10+：

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # Windows
.venv\Scripts\python app.py
```

浏览器打开 <http://127.0.0.1:61420/>。

## 打包免 Python 的 Windows 版

```bat
build-exe.bat
```

产物在 `dist\BiliPick\`（onedir，复制整个文件夹即可分发）。

## 使用

1. 「API 与模型」：选协议、填 API Key（仅存本机 `data/config.json`）
2. 「B站 账号」：扫码登录（仅存本机 `data/credential.json`）
3. 「类别与配额」：改类别、关键词、每天条数、精判上限、质量分/评分下限
4. 顶部「保存」→「开始跑一轮」

## 目录

```
app.py            本地 HTTP 服务 + 浏览器界面
engine.py         搜索/分类/质量分/去重/粗排/精判/稍后再看/日报
web/index.html    前端（原生 JS，无构建）
requirements.txt  bilibili-api-python / aiohttp / qrcode / Pillow
start.bat         源码方式启动
setup.bat         创建 venv 并装依赖
build-exe.bat     PyInstaller 打包
```

## 许可与致谢

MIT。见 [LICENSE](LICENSE)。

- 思路与「值班章程」设计来自 [c1overzz/dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll)（MIT）
- B站 接口能力来自 [bilibili-api-python](https://github.com/Nemo2011/bilibili-api)（MIT）与 [adoresever/bilibili-mcp](https://github.com/adoresever/bilibili-mcp)（MIT）

本项目与上述项目无隶属关系，为独立重写实现。

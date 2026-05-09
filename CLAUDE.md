# milkGreenSoul 项目说明

**milkGreenSoul** — 主播说话风格克隆项目。
从主播直播录像中提取语音 → 分析说话风格 → 让 OpenClaw agent 模仿该主播说话(可选附加 TTS 语音克隆)。

## 运行环境

- **硬件**:Mac mini M4 / 16GB RAM
- **主语言**:Python
- **已装本地工具**:
  - whisper.cpp(brew 安装,主程序在 `/opt/homebrew/bin/whisper-cli` — **注意:不是 roadmap 文档里写的 `./main`**;还有 whisper-server / whisper-stream 等套件)
  - ggml-large-v3-turbo 模型(已下载,**3 个副本**:`~/whisper.cpp/models/`、`~/whisper-models/`、`~/openclaw-stt-server/whisper-models/`,后续可清理重复)
  - ffmpeg 8.1(`/opt/homebrew/bin/ffmpeg`)
  - OpenClaw(生产环境在 `~/.openclaw/`,**不要主动碰**;开发用项目本地)
  - FastAPI 服务(端口 18900)
- **AI API**:DeepSeek v4(通过 OpenClaw)、Gemini Vision、Claude API

## 项目路线(参考 `~/Downloads/streamer-style-clone-roadmap.md`)

6 阶段闭环,**按顺序逐阶段完成,每阶段独立可验收**:

1. **数据采集** — yt-dlp 批量下录像 + 弹幕(可选)
2. **ASR 转录** — whisper.cpp 批量,JSON 输出
3. **文本清洗** — 去重 / 合并碎片 / 保留风格语气词 / 标点修正 / 弹幕-语音配对 / 场景分类
4. **风格分析(核心)** — LLM 多维提炼(口头禅/语气/句式/称呼/互动/情绪/转场/讲解/节奏)+ 跨场次汇总 + few-shot 示例库
5. **部署到 OpenClaw** — SOUL.md 直接写入 或 Skill 动态检索

~~6. (可选)语音克隆 — Bert-VITS2 + Demucs 分离~~ ← **2026-05-09 拍板:跳过,前 5 阶段闭环就够**

5 阶段闭环,每阶段独立可测试,完成一个再进入下一个。

## 协作风格(初级开发者)

- 我学过一点编程,缺乏工程经验,**把我当成初级开发者**
- 改代码前,先用一两句中文讲清楚"为什么要这么改",再动手
- 每次只改一小步,改完说明:改了什么 / 可能的副作用 / 下一步建议
- 遇到我写错的地方,**直接指出错误逻辑**,不要只迎合
- 装新 pip 包前先问我,告诉我这个包做什么用

## 代码风格

- Python(主力,本项目唯一语言)
- 遵循 PEP 8;函数加类型 hints
- 每个函数写简短中文 docstring,新手回看能看懂
- 提交信息用中文,格式 `类型: 做了什么`,如 `feat: 添加 yt-dlp 批量下载脚本`
- 配置走 `config.yaml`(路径 / 模型参数);secrets 走 `.env`
- **Python 环境用 venv 隔离**(`.venv/` 在 .gitignore);每次进项目执行 `source .venv/bin/activate`

## AI 协作的工程纪律

本项目可能用 Codex/GPT Pro 主写 + Claude Pro 审。以下纪律必须遵守:

1. **关键模块绝对不 vibe coding** — 风格分析 prompt(决定克隆质量)、文本清洗逻辑(决定数据质量)、OpenClaw 集成(决定最终效果),每行代码用户必须看懂
2. **AI 写完代码,自己手敲一遍** — 可以照抄,不能 ctrl+c+v
3. **每个 commit 必须用一句中文说清"为什么"** — 不写为什么的提交不进 git history
4. **关键决策点先问我** — 加新依赖 / 改 prompt 模板 / 改文件结构,先问再动手
5. **大批量任务先用小样本验证** — 比如先跑 1 个录像走完 1-5 阶段,人工看效果,再批量

## 红线

- **不写 API key 到代码里** — 所有 key(DeepSeek / Gemini / Claude / B 站等)走 `.env`,且 `.env` 必须在 `.gitignore`
- **不擅自 `rm -rf` / `git reset --hard` / `git push --force`** — 这类操作先问我
- **不主动碰 `~/.openclaw/`** — 那是 OpenClaw 生产环境;开发用项目本地的 SOUL.md / Skill 草稿
- **大文件不入 git** — `data/raw_videos/`、`data/audio/` 等动辄 GB,严禁 commit
- **慎用长时任务** — ffmpeg 批量、whisper.cpp 大批量、demucs、Bert-VITS2 训练,提前确认
- **尊重平台 ToS** — yt-dlp 只下载自己有权访问的内容(订阅/购买/已授权的回放)
- **风格分析的原始转录文本含 PII**(粉丝弹幕用户名等)— 公开任何中间产物前先脱敏

## 项目目录结构

```
milkGreenSoul/
├── CLAUDE.md                  ← 本文件
├── README.md
├── config.yaml                ← 路径、模型参数、API key 引用
├── .env                       ← API key(不入 git)
├── .gitignore
├── requirements.txt           ← Python 依赖
├── scripts/
│   ├── download.py            # yt-dlp 批量下载
│   ├── extract_audio.py       # ffmpeg 音频提取 + 切段
│   ├── transcribe.py          # whisper.cpp 批量转录
│   ├── clean_text.py          # 文本清洗
│   ├── danmaku_pair.py        # 弹幕-语音配对
│   ├── analyze_style.py       # LLM 风格分析(核心)
│   └── build_examples.py      # few-shot 示例库
├── data/                      ← 大文件,gitignore
│   ├── raw_videos/
│   ├── audio/
│   ├── transcripts/
│   ├── danmaku/
│   ├── cleaned/
│   └── analysis/
└── output/
    ├── SOUL_persona.md        # 最终人设文档(交付物)
    └── examples.yaml          # few-shot 示例库(交付物)
```

## 阶段验收标准

| 阶段 | 完成定义 |
|---|---|
| 1 数据采集 | 1 个直播录像下载成功 + 弹幕(如有) |
| 2 ASR 转录 | 1 个录像 → 音频 → whisper 转录 JSON,人工查看质量 OK |
| 3 文本清洗 | 去重率 ≥ 95%,场景分类抽样准确率 ≥ 80% |
| 4 风格分析 | 跨场次稳定特征提炼出来(3+ 场次出现的才算稳) |
| 5 OpenClaw 部署 | 20 条测试输入,口头禅+语气+互动还原度 ≥ 4 分(满分 5) |

## 实施顺序(严格)

按 roadmap 文档的"实施顺序建议":**先跑通最小闭环**(1 个录像走完 1-2 阶段)→ 再批量 → 再做文本处理 → 再做风格分析 → 最后部署验证。

## 项目状态(2026-05-09)

- ✅ 项目目录创建
- ✅ CLAUDE.md / README.md / .gitignore 初始化
- ✅ git 初始化
- ⏳ 第一阶段:`scripts/download.py`(yt-dlp 批量下载)

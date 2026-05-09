# milkGreenSoul

**主播说话风格克隆项目** — 从直播录像提取语音 → 分析说话风格 → 让 OpenClaw agent 模仿该主播说话(可选附加 TTS 语音克隆)。

## 完整技术路线

详细 6 阶段路线见预研文档:`~/Downloads/streamer-style-clone-roadmap.md`

## 协作约定

开发协作风格、代码规范、AI 协作纪律、红线见 [CLAUDE.md](./CLAUDE.md)。

## 运行环境

- Mac mini M4 / 16GB RAM
- Python 主力
- whisper.cpp + ggml-large-v3-turbo(本地 ASR)
- OpenClaw + FastAPI 服务(端口 18900)
- AI API:DeepSeek v4 / Gemini Vision / Claude API

## 阶段路线(摘要)

| 阶段 | 内容 | 状态 |
|---|---|---|
| 1 | 数据采集(yt-dlp + 弹幕) | 待启动 |
| 2 | ASR 转录(whisper.cpp 批量) | — |
| 3 | 文本清洗 + 弹幕配对 + 场景分类 | — |
| 4 | LLM 风格分析(核心) + few-shot 库 | — |
| 5 | 部署到 OpenClaw(SOUL.md 或 Skill) | — |

## 开发环境

本项目用 venv 隔离 Python 依赖。

```bash
# 第一次创建(已建过则跳过)
python3 -m venv .venv

# 每次进项目激活
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

## 状态

- **2026-05-09**:项目骨架初始化,venv + yt-dlp 已配置

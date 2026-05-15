# Stage 1-4 交接文档

> **目标读者**:接手 Stage 1-4 后续工作的 AI 协作者(本项目计划交给 DeepSeek)。
> **写作时间**:2026-05-15
> **当前分支**:`feat/stage4-rework`(从 dev 分支 646ede0 切出)

---

## 0. 你需要先读的两份文件

| 文件 | 作用 |
|---|---|
| `CLAUDE.md` | 项目宪法 — 协作风格、红线、工程纪律。**必读**,且必须遵守。 |
| 本文件 | 当前进度快照 + 已做决策 + 下一步待办 |

CLAUDE.md 里关键约束摘录(违反任意一条都会被打回):
- 不写 API key 到代码里(走 `.env`)
- 不擅自 `rm -rf` / `git reset --hard` / `git push --force`
- 不主动碰 `~/.openclaw/`(生产环境)
- 大文件(`data/raw_media/`, `data/audio/` 等)不入 git
- 关键模块禁止 vibe coding(风格分析 prompt、文本清洗逻辑、OpenClaw 集成)
- 提交信息中文 + 一句话说"为什么"
- 改 prompt 模板 / 加新依赖 / 改文件结构,先问用户

---

## 1. 项目一句话

从主播"明前奶绿"的直播录像中提取语音 → 分析说话风格 → 让 OpenClaw agent 模仿她说话。**5 阶段闭环**(原 6 阶段,语音克隆已确认跳过):

1. 数据采集(yt-dlp)
2. ASR 转录(whisper.cpp / B站 AI 字幕)
3. 文本清洗
4. 风格分析(LLM)
5. 部署到 OpenClaw

---

## 2. 当前数据状态(2026-05-15)

### 共用语料(2.0 与 2.1 都从这里读,不版本化)

| 阶段 | 产出位置 | 数量 | 状态 |
|---|---|---|---|
| 1. raw_media | `data/raw_media/*.m4a` | 40 个音频文件(11 个直播回放多P + ~29 个 BV 切片) | ✅ |
| 1. 弹幕 | `data/danmaku/` | 0 | ⚠️ **未采集**(见 §4 弹幕策略) |
| 2. whisper 转录 | `data/transcripts/*.json` | **1904** | ✅(已清理 3 个 bili_ai 测试残留;白名单再排除 1 个 capture_*) |
| 2. B站 SRT 字幕 | `data/srt/*` | 981 | ✅ 作为 whisper 对照源 |
| 3. 文本清洗 | `data/cleaned/*.json` | **959** | ✅(已清理 3 个 bili_ai) |
| 3. 情绪清洗 | `data/cleaned_emo/*.json` | 1 | ⚠️ 几乎未跑,主线产出的 `emotion_stats` 已够用,可暂不补 |

### 2.0 归档(只读对照组)

| 文件/目录 | 内容 |
|---|---|
| `data/analysis_v2.0/`(80M) | 含 prologue 污染的 Stage 4 全部产出:`keyword_stats.json` / `llm_analysis/`(957 个) / `style_profile.json` / `tagged/` / `motivation/` / `1v1_clips/` / `sc_interactions/` 等 |
| `output/SOUL_v2.0.md` | 旧 SOUL.md 快照 |
| `output/SKILL_v2.0.md` | 旧 SKILL.md 快照 |
| git tag `v2.0-baseline` | 钉在 `646ede0`,2.0 时代的代码状态(可 `git checkout v2.0-baseline` 穿越) |

### 2.1 工作区(空,等重跑填充)

| 路径 | 用途 |
|---|---|
| `data/analysis/` | 重跑后的 Stage 4 全部产出 |
| `output/SOUL.md` / `output/SKILL.md` | 当前仍是 2.0 的内容,2.1 重跑 Stage 5 会覆盖 |

**对照方法**:`diff output/SOUL_v2.0.md output/SOUL.md`,或 `diff data/analysis_v2.0/style_profile.json data/analysis/style_profile.json`,可肉眼对比 prologue 拆分前后差异。

### 数据 schema 速查

**`data/cleaned/{stem}.json`**:
```json
{
  "bvid": "BV...",
  "title": "...",
  "notes": "...",
  "source": "<stem>",
  "original_count": int,
  "cleaned_count": int,
  "segments": [{"start": float, "end": float, "text": str}, ...],
  "emotion_stats": {...}
}
```

**`data/analysis/style_profile.json`** 顶层 keys:
`videos_analyzed, stable_phrases, stable_particles, addressing, interaction_profiles, xia_tou_patterns, contradictions, emotion_switches, unique_expressions`

---

## 3. 本次重构的核心决策(必须读)

### 3.1 prologue.md 的污染问题(已确认,待执行拆分)

**问题**:[output/prologue.md](output/prologue.md) 自称"分析的校准基准",通过 [scripts/analyze_style.py:267](scripts/analyze_style.py:267) 和 [scripts/build_soul.py:21](scripts/build_soul.py:21) 注入 LLM prompt。这导致 Stage 4 的"数据驱动归纳"实际上是"按 prologue 预设回填",得到的 SOUL.md 是用户主观印象的工整复述,不是真实数据呈现。

**已定方案**:
- prologue 第一节"我对奶绿的核心理解" + 第二节"粉丝群体画像" → **删除或归档**(它们是用户解读,不是事实,不该当作分析输入)
- 第三节"本次到底要做一个什么样的明前奶绿" → 拆出独立文件 `output/clone_spec.md`,**仅在 Stage 5(`build_soul.py`)使用**,Stage 4 分析阶段不得加载
- `milkgreen_profile.md` 同理拆分:基本信息表 / 前世时间线 / 粉丝名 / 角色设定 → 保留为"事实卡片"作为 Stage 4 上下文参考;心理学解读("对越界极度敏感(被开盒过的创伤反应)"等)→ 移到 `clone_spec.md`,仅 Stage 5 用

**这一步还没动**,因为用户表示要先标注 anchor clips(见 3.2),再统一改 Stage 4。

### 3.2 anchor clips 机制(待用户标注,然后实现)

**思路**:用户手工标注一批"特别能体现角色性格"的切片,在风格分析中赋予**更高参考权重**,以**数据接地**替代 prologue 的"先验断言"。

**数据形态(草案)**:
```
data/analysis/anchor_clips.json
[
  {
    "clip_id": "BV16BiiBfE8P_seg_142",
    "bvid": "BV16BiiBfE8P",
    "segment_index": 142,
    "weight": 3,                        // 1-5,5 = 教科书级代表
    "facets": ["锐评", "本质上来说"],     // 体现哪些维度,可选
    "note": "进入锐评模式的典型切换"      // 备忘
  }
]
```

**下游消费方式**:
- `analyze_style.py` 采样时 anchor 必入,prompt 里独立列为"已确认代表性片段(优先归纳)"
- 聚合统计(口头禅/句式计频)时,anchor 按 `weight` 加权
- `build_soul.py` 的 few-shot 示例**直接从 anchor 抽**,不让 LLM 编造

**未决问题**(等用户拍板):
1. 计划标注多少条?(<50 用 CLI,>100 需 web UI)
2. 用文本搜索还是音频回放定位代表片段?
3. Stage 4 重跑范围:全 931 个 vs 先 3-5 场对照试验

### 3.3 弹幕策略(本次新决定)

**只对直播回放下载弹幕,粉丝切片不下载弹幕。**

**理由**:粉丝切片的"弹幕"是切片视频自己的播放弹幕,**不是奶绿原直播时的实时弹幕**,对"复现直播现场互动"的目标没有价值。直播回放的弹幕才是奶绿当时听到/看到的内容,有信号价值(SC 互动、节奏带动、情绪反应触发器)。

**具体做法**(待实现):
- 只对 `data/raw_media/` 下文件名含 `_BiliBili_` 的 m4a(yt-dlp 下载的直播回放)拉取弹幕
- 跳过 `BV*.m4a`(粉丝切片)
- 落盘位置:`data/danmaku/{stem}.json`
- 字段建议:`[{time: float, text: str, type: "normal"|"sc"|"gift", user_hash: str}]`
- 用户名要 hash 化(PII),不要保留明文

**用什么工具**:yt-dlp 内置 `--write-subs --sub-langs danmaku` 不靠谱;推荐用 `DanmakuFactory` 或直接调 B 站 history API。**先问用户**再加依赖。

### 3.4 已完成的清理(本次)

- 删除 `data/transcripts/bili_ai_P{1,2,3}.json` 和 `data/cleaned/bili_ai_P{1,2,3}.json` 共 6 个测试残留
- `scripts/clean_text.py` 加 `is_target_stem()` 白名单,过滤非奶绿命名文件
- `scripts/analyze_style.py` Step 1 加同样的白名单
- `scripts/download_bili_subs.py` 加 docstring 标明"测试脚本,生产请用 download_collection_subs.py"

**白名单规则**(以 stem 为单位):
- 接受:`BV*` / `clip_BV*` / 含 `_BiliBili_`
- 拒绝:其他一律 SKIP 并日志告警

---

## 4. 下一步待办(按优先级)

### P0 — 等用户输入,然后立刻可做
1. 用户标注 anchor clips(见 3.2),你拿到 `anchor_clips.json` 后实施 anchor-weighted 采样与统计

### P1 — 可以现在就开始
2. **拆分 prologue.md → clone_spec.md**(见 3.1):新建 `output/clone_spec.md`,只放产品意图(克隆该有的样子),不放对她的事实陈述;`scripts/analyze_style.py` 停止加载 prologue 与 profile 的心理解读部分;`scripts/build_soul.py` 改加载 `clone_spec.md`(仅 Stage 5)
3. **`data/analysis/keyword_stats.json` 重跑一次**(`python3 scripts/analyze_style.py` 的 step1),把含 bili_ai 的旧统计覆盖掉。重跑前确认 `data/cleaned/` 里没有 bili_ai_*(本次已删)

### P2 — 设计/讨论
4. **弹幕下载**(见 3.3):先和用户确认工具选型(DanmakuFactory 还是直 API),再写脚本 `scripts/download_danmaku.py`,只对 `*_BiliBili_*.m4a` 跑
5. **Stage 4 重跑策略**:全量 vs 增量?Token 预算?用户是否要先做对照试验?

### P3 — 已知缺口,先不动
6. `data/cleaned_emo/` 只有 1 个文件,看起来是被废弃的备用 pipeline,主线 `cleaned/` 的 `emotion_stats` 已够用。除非用户明确要求,不要补这条线
7. `output/SOUL.md` 和 `output/examples.yaml` 是旧 Stage 4 的产物,带 prologue 污染。**重跑 Stage 4 之前不要参考它们做任何决策**

---

## 5. 给 DeepSeek 的几条具体提示

1. **本项目用户是初级开发者**,改代码前用一两句中文讲清"为什么改",再动手
2. **关键模块禁止 vibe coding**:风格分析 prompt、文本清洗逻辑、OpenClaw 集成 — 这三处每行代码用户必须看懂,写完要让用户复述
3. **改 prompt 模板 / 加新依赖 / 改文件结构,先问用户**,不要自作主张
4. **大批量任务先用小样本验证**:Stage 4 重跑先选 1-3 场,人工看效果再全量
5. **commit message 用中文,格式 `类型: 做了什么`,且每个 commit 写"为什么"**
6. **当前还有一个未追查的疑点**:`scripts/run_prompt_a.py` 不在 CLAUDE.md 列出的 scripts 名单里,功能未审计,谨慎对待
7. **Python 环境用 venv**:`source .venv/bin/activate`(如有)

---

## 6. 可信赖与不可信赖

| 文件 | 可不可信 | 备注 |
|---|---|---|
| `data/cleaned/*.json`(959 个) | ✅ 可信 | bili_ai 已清,白名单已设 |
| `data/transcripts/*.json`(1904 个) | ✅ 可信 | 同上 |
| `data/analysis/`(当前为空) | ⏳ 待填充 | 2.1 重跑后产出 |
| `data/analysis_v2.0/` | 📦 归档 | 2.0 时代的不可信产出,仅作对照,不要拿来当结论 |
| `output/SOUL.md` / `SKILL.md` | ❌ **不可信** | 仍是 2.0 内容,等 2.1 重跑覆盖 |
| `output/SOUL_v2.0.md` / `SKILL_v2.0.md` | 📦 归档 | 2.0 快照,对照用 |
| `output/prologue.md` | ⚠️ 待拆分 | 第一节将删,第三节将移到 `clone_spec.md` |
| `output/milkgreen_profile.md` | ⚠️ 待拆分 | 事实卡片保留,心理解读移到 `clone_spec.md` |

---

## 7. 一句话总结

**Stage 1-3 数据干净可用。Stage 4 输出全部需要在拆分 prologue + 引入 anchor clips 之后重跑。第一步等用户给 `anchor_clips.json`,你才动 Stage 4。**

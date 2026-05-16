# milkGreenSoul 2.1 任务交接

> **目标读者**:接手 Stage 1-5 后续工作的 DeepSeek code agent
> **写作时间**:2026-05-15
> **任务**:产出 2.1 release(数据驱动、去预设污染的人格克隆 pipeline)

---

## 0. 你需要先读的两份文件(顺序不能错)

1. **`CLAUDE.md`** — 项目宪法、协作风格、红线。**必读,必须遵守。**
2. **本文件** — 2.1 架构、当前数据状态、文件角色、待办清单

读完后回答用户两个问题再动手:
- (a) 你认为下一个最该做的事是什么?为什么?
- (b) 哪些地方不清楚,需要先澄清?

---

## 1. 项目一句话

从主播明前奶绿的直播录像 → 提取语音 → 分析说话风格 → 生成 OpenClaw agent 的人设(SOUL.md + SKILL.md)。

5 阶段闭环:
1. 数据采集(yt-dlp)
2. ASR 转录(whisper.cpp / B 站 AI 字幕)
3. 文本清洗
4. 风格分析(LLM,**本次重构核心**)
5. 部署到 OpenClaw

---

## 2. 2.1 的核心方法论:序言变尾言

### 2.0 的问题

2.0 把 `prologue.md`(项目负责人对奶绿的直觉理解)和 `milkgreen_profile.md` 的解读部分**直接塞进 Stage 4 LLM 的 system prompt**,声称"以此为校准基准"。结果 LLM 不是从数据归纳风格,而是回填用户预设——产物像"用户判断的工整复述",不是奶绿本人。

### 2.1 的方法

**同一份解读文档,改变它在管线里的位置**:

| 阶段 | 任务性质 | 是否加载 prologue / interpretations |
|---|---|---|
| **Stage 4.2** analyze_style.py Step 2(风格归纳) | 模式识别 | ❌ **完全盲测**——只看 segments |
| **Stage 4.3** run_prompt_a.py(单场动机) | 因果推断 | ❌ 解读 / ✅ 事实(`milkgreen_facts.md`) |
| **Stage 4.4** run_prompt_b.py(跨场动机) | 因果推断 | ❌ 解读 / ✅ 事实 |
| **Stage 4.5** run_binding.py(表征-动机绑定) | 焊接 | ❌ 解读 / ✅ 事实 |
| **Stage 4.6** run_prompt_c.py(1V1 提取) | 分类抽取 | ❌ **不需要任何上下文** |
| **Stage 4.7** run_prompt_d.py(1V1 vs 广播差异) | 模式对比 | ❌ **不需要** |
| **Stage 4.8** run_prompt_e.py(SKILL 适配生成) | 产品意图生成 | ✅ **加载 `prologue.md`(作为 clone spec)** |
| **Stage 5** build_soul.py(整合) | 产品意图生成 | ✅ **加载 `prologue.md`** |

**事后验证(尾言模式)**:
Stage 4 全跑完后,人工 diff `prologue.md` / `prologue_opus.md` / `milkgreen_profile.md` 的解读部分 vs 数据归纳结果(`style_profile.json` / `SOUL.md`)。三种结果都有信号:
- 数据出现你猜到的特征 → 印证
- 数据出现你没猜到的 → 学到新东西
- 你猜了但数据没有 → 过度解读,收回

---

## 3. 文件角色清单(2.1 起,**这是黄金索引**)

### 输入文档

| 文件 | 内容 | 谁加载 |
|---|---|---|
| `output/prologue.md`(角色 = clone spec) | 产品意图 + AI 化转化原则 + 误读兜底表 | **只** Stage 4.8 / Stage 5 |
| `output/milkgreen_facts.md` | 纯事实子集(身份/前世/人际/角色设定/重大事件/粉丝文化术语) | Stage 4.3-4.7(LLM 推理动机 / 1V1 时作为事实背景) |
| `output/milkgreen_profile.md` | 完整档案(含解读,带 frontmatter 标注) | **不进任何 prompt**,作为参考 + 事后验证 |
| `output/prologue_opus.md` | Opus 的二阶解读(带 RTF 出处) | **不进任何 prompt**,作为尾言验证文档 |
| `data/cleaned/{stem}.json` | 959 个清洗后的 segments | Stage 4 全部脚本的主数据 |

### 共用语料(Stage 1-3 产出,不归版本)

| 路径 | 数量 | 用途 |
|---|---|---|
| `data/raw_media/*.m4a` | 40 | 原始音频 |
| `data/transcripts/*.json` | 1904 | whisper / B 站 AI 字幕转录 |
| `data/srt/*` | 981 | B 站 SRT 字幕(对照源) |
| `data/cleaned/*.json` | 959 | Stage 3 清洗产出(已带 `emotion_stats`、SenseVoice 情绪标签) |
| `data/danmaku/` | 0 | ⚠️ 未采集(见 §6 弹幕策略) |

### 2.1 工作区(空,等你重跑填充)

| 路径 | 用途 |
|---|---|
| `data/analysis/` | Stage 4 全部产出(目前空,等 2.1 重跑) |
| `output/SOUL.md` / `output/SKILL.md` | 仍是 2.0 末态内容,2.1 Stage 5 会覆盖 |

### 2.0 归档(只读对照,**不要拿来当结论**)

| 路径 | 内容 |
|---|---|
| `data/analysis_v2.0/`(80M) | 2.0 时代 Stage 4 全部产出(motivation/、1v1_clips/、persona_signature_bindings.json、style_profile.json 等) |
| `output/SOUL_v2.0.md` | 2.0 末态 SOUL.md 快照 |
| `output/SKILL_v2.0.md` | 2.0 末态 SKILL.md 快照 |

---

## 4. Stage 1-3 状态摘要

### 已交付

- Stage 1:40 个音频文件,已清理 bili_ai 测试残留
- Stage 2:1904 个转录,加了输入白名单防止再次混入
- Stage 3:959 个清洗文件,字段:
  - `segments[].start / end / text`
  - `segments[].part`(多 P 编号)
  - `segments[].emotion`(SenseVoice 开放标签,如 `中性/平静` `愤怒/激动` `Laughter` 等)
  - `emotion_stats`(全场情绪计数)
  - `notes`(Gemini 生成的场次速览——⚠️ 见下方污染说明)

### Stage 3 已知缺口(可选改进,不阻塞 2.1 主流程)

1. **`notes` 字段含混合内容(事实 + Gemini 主观判断)**
   - 事实部分:场次主题、SC 节奏、人物提及、内容架构
   - 主观部分:"高冷音色与世俗内容的强烈反差""冷感御姐"这类语气评价
   - **2.1 决策**(已定):**保留 notes 注入,但 prompt 里明确框定角色**,告诉 LLM"notes 只为理解场次内容,主观判断不要采纳"。理由:whisper 字幕本身不够准确,notes 提供的事实性上下文有用;一刀切删除会让 LLM 在无上下文下硬归纳,可能更糟。具体改法见 §5 A.1
2. **场景分类(scene)字段缺失** — 目前 cleaned 没有 scene 字段,SCENE_PATTERNS 只在 Stage 4.1(analyze_style.py Step 1)用正则打。CLAUDE.md 验收标准要求 Stage 3 给场景分类(准确率 ≥ 80%),长远应下沉到 Stage 3
3. **Whisper 中文无标点** — 影响 LLM 归纳句式特征。可加 ct-punc 之类的轻量标点恢复
4. **弹幕未采集** — 见 §6
5. **PII 脱敏未做** — cleaned 里可能含主播念出的 SC 用户名,公开任何中间产物前必做
6. **`clean_emotion.py` vs `clean_text.py`** — `cleaned_emo/` 只有 1 个产出,看起来是被废弃的平行管线。SenseVoice 情绪标签已在 `cleaned/` 主线产物里,可以确认废弃

---

## 5. 你的具体待办(2.1 implementation)

### Phase A — Stage 4 LLM 脚本去污染(P0,核心工作)

修改 6 个脚本的 prompt 模板与上下文加载逻辑:

#### A.1 `scripts/analyze_style.py` Step 2(分两处)
- 第 282-289 行 `STYLE_ANALYSIS_SYSTEM` 模板:删除 `## 主播背景(核心校准){prologue}` 和 `## 主播人物档案(事实参考){profile}` 段
- 第 353-355 行 `build_analysis_prompt` 函数:不再 `load_prologue()` / `load_profile()`;只用 segments + notes
- 第 436 行附近 `CLIP_ANALYSIS_SYSTEM` 模板(切片用):删除 `{prologue}` 和 `{profile}` 注入;**切片无 notes 字段**,保留切片自带的 `{title}` 作为最简上下文
- 第 457-458, 514 行:同样去掉 prologue/profile,保留 title
- **目标**:LLM 在 Step 2 风格归纳上盲测主观解读,只看清洗后 segments + 上下文(notes / title)

**关于 `notes` 字段**(直播回放专属,切片没有):
- **保留 notes 注入**,但 prompt 里必须明确框定它的角色,避免 Gemini 的主观判断回填
- 在 `STYLE_ANALYSIS_SYSTEM` 模板里把 notes 段改为:
  ```
  ## 本场内容大致提要(来自 Gemini 自动生成)
  {notes}

  > ⚠️ 上述 notes 仅用于帮你**理解本场谈了什么**(主题、SC 节奏、人物提及等)。
  > notes 里的主观判断(如"冷感御姐""高冷音色"这类语气评价)**不要采纳**,
  > 也不要让它影响你对说话风格的归纳。归纳必须只从 segments 来。
  ```
- 理由:whisper 中文字幕本身不够准确,notes 提供的"场次主题+SC 节奏"是有用上下文。一刀切删除会让 LLM 在没有上下文的情况下硬归纳,可能更糟。框定角色 + 显式排除主观判断,是中间路径

#### A.2 `scripts/run_prompt_a.py`
- 第 59 行:"主播人格纲领 (prologue) — 项目负责人对这个人的直觉理解,**分析时以此为准**" 这一句**删除**或改写为"以下事实背景仅供识别人物/关系/世界观参考,不要据此预判她的动机"
- 第 124-126 行 `load_context()`:不加载 `prologue.md`;`profile` 改为加载 `output/milkgreen_facts.md`
- 第 180-181 行 `build_user_prompt`:不传 prologue
- **目标**:动机推理时 LLM 只有事实背景 + 数据,自己推断

#### A.3 `scripts/run_prompt_b.py`
- 第 25-26 行加载语句:`PROLOGUE_PATH` 删除;`PROFILE_PATH` 改为 `milkgreen_facts.md`
- 后续 prompt 模板里删除 prologue 注入

#### A.4 `scripts/run_prompt_c.py`(1V1 提取,任务是分类)
- 第 31, 98-100 行:`PROLOGUE_PATH` 及 `load_prologue()` 全部删除
- 第 130-131, 169, 174 行:不再 `build_user_prompt(data_text, prologue, notes)`,改为 `build_user_prompt(data_text)`,**notes 也不加载**(1V1 提取是分类任务,不需要场次主题这种上下文,看 segments 的格式就能分类)
- **目标**:纯数据驱动的分类抽取

#### A.5 `scripts/run_binding.py`
- 第 28, 55, 151, 177 行:`PROLOGUE_PATH` 删除
- 第 148 行 `build_user_prompt(style, motivation, prologue)`:去掉 prologue 参数
- prompt 模板里"主播人格纲领"段删除
- **目标**:表征-动机绑定只依赖 Stage 4.2/4.4 产出,不依赖人工纲领

#### A.6 `scripts/run_prompt_e.py`(适配生成,**保留 prologue**)
- 第 25, 145, 154 行:**保留** `PROLOGUE_PATH` 和 prologue 加载
- 但在 prompt 模板里把 prologue 的角色明确标注为"产品规格(clone spec):描述用户希望 AI 奶绿是什么样的人"
- 这一步是合理用法,不是污染

#### A.7 `scripts/build_soul.py`(Stage 5,**保留 prologue**)
- 同 A.6,保留加载 prologue。把它在 prompt 里的角色标记为"产品规格"
- 但 `milkgreen_profile.md` 切换为加载 `milkgreen_facts.md`

### Phase B — 数据重跑(P0,A 完成后立刻做)

按顺序跑(每步先用 1-3 场小样本验证,再全量):
1. `python3 scripts/analyze_style.py --step 1` — 重新统计 keyword(因为之前的 keyword_stats.json 已归档到 v2.0,需要新跑)
2. `python3 scripts/analyze_style.py --step 2 --limit 3` — **盲测**风格归纳,先 3 场看效果,人工抽检 LLM 是否还在写"妈味"这种来自 prologue 的话(应该没有)。OK 后全量
3. `python3 scripts/analyze_style.py --step 3` — 跨场汇总
4. `python3 scripts/run_prompt_a.py --limit 1 --dry-run` — 检查 prompt 长度和内容是否符合 2.1 规则
5. `python3 scripts/run_prompt_a.py` 全量
6. 依次 `run_prompt_b.py` → `run_prompt_c.py` → `run_prompt_d.py` → `run_binding.py` → `run_prompt_e.py`
7. `python3 scripts/build_soul.py` 产出新 `SOUL.md` / `SKILL.md`

### Phase C — 尾言验证(P0,B 完成后)

人工 diff:
```bash
diff output/SOUL_v2.0.md output/SOUL.md     # 2.0 vs 2.1
```
然后逐条对照 `output/prologue.md`、`output/prologue_opus.md` 附录、`output/milkgreen_profile.md` §二末 / §八的解读断言:
- 数据印证了哪些 → 在新 SOUL.md 里有体现 ✓
- 数据反驳了哪些 → 用户要决定:是数据采样不足,还是用户原本过度解读
- 数据出现但 prologue 没说的 → 这是 2.1 的"发现",写入 PROGRESS.md

### Phase D — 验收(P1)

`python3 scripts/validate_skill.py` 跑 9 条对话,与 2.0 版做盲测对比。如果 2.1 版回复:
- 口癖更自然(不堆砌)
- 不再过度"妈味"
- 保留矛盾性(嘴硬心软不调和)
- 默认慵懒,不主动锐评
- 不自称"妈妈"

→ 2.1 成功。否则定位问题(可能是 Stage 5 prompt 还需调整,或者其他)。

---

## 6. 已做决策清单(2.1 必须遵守)

### 6.1 弹幕策略

**只对直播回放下载弹幕,粉丝切片不下载。** 切片的弹幕是切片视频自己的事后弹幕,不是奶绿原直播的实时弹幕,无信号价值。

实现要点:
- 落盘位置:`data/danmaku/{stem}.json`
- 字段:`[{time: float, text: str, type: "normal"|"sc"|"gift", user_hash: str}]`
- 用户名必须 hash 化(PII)
- 工具选型(DanmakuFactory / B 站 history API)**先和用户确认**再实施
- **本次 2.1 不强制实施弹幕功能**——它是 Stage 3 缺口,在主管线之外。除非用户明确要求,可以后置到 2.2

### 6.2 数据卫生

- `scripts/clean_text.py` 和 `scripts/analyze_style.py` Step 1 已加 `is_target_stem()` 白名单
- 接受:`BV*` / `clip_BV*` / 含 `_BiliBili_`
- 拒绝:其他(防止开发期测试残留再次混入)
- `scripts/download_bili_subs.py` 已标记为"测试脚本/已弃用",生产用 `download_collection_subs.py`

### 6.3 prologue 拆分原则(已实施)

- `output/prologue.md` 顶部 frontmatter 已更新,声明只在 Stage 4.8 / Stage 5 + 尾言验证使用
- `output/milkgreen_facts.md` 已创建(纯事实子集)
- `output/milkgreen_profile.md` 顶部 frontmatter 已更新,声明不进任何 Stage 4 prompt
- `output/prologue_opus.md` 顶部 frontmatter 已更新,声明为尾言验证文档

### 6.4 anchor clips(用户的另一个 2.1 想法,**暂缓**)

用户可能后续手工标注一批"特别能体现角色性格"的切片,赋予更高参考权重。这是另一种"去预设污染"的思路(在数据侧用证据替代断言)。

**2.1 暂不实现这套机制**,先跑通"序言变尾言"。如果 2.1 效果仍不理想,2.2 再加 anchor weighting。

---

## 7. 工程纪律(违反任意一条会被打回)

来自 CLAUDE.md:

1. **关键模块禁 vibe coding** — 风格分析 prompt、文本清洗、OpenClaw 集成。改前要用一两句中文讲清"为什么这么改",用户看懂才动手。每行代码用户必须能复述。
2. **改 prompt 模板 / 加新依赖 / 改文件结构,先问用户**。
3. **不擅自删文件、`rm -rf`、`git reset --hard`、`git push --force`**。
4. **不主动碰 `~/.openclaw/`**(生产环境)。
5. **大文件不入 git**:`data/raw_media/`、`data/audio/`、`data/analysis*/` 等。
6. **大批量任务先用 1-3 个样本验证**,人工看效果再全量。LLM 调用费钱也费时,跑错全量代价大。
7. **commit message 用中文**,格式 `类型: 做了什么`,正文写**为什么**。
8. **用户是初级开发者**,改代码前先讲思路。改完说明:改了什么 / 可能的副作用 / 下一步建议。
9. **遇到用户写错的地方,直接指出错误逻辑**,不要只迎合。
10. **风格分析的原始转录文本含 PII**(粉丝弹幕用户名等)— 公开任何中间产物前先脱敏。

---

## 8. 验收标准(2.1 release 完成的定义)

| 检查项 | 要求 |
|---|---|
| Stage 4.2 不含 prologue 注入 | grep `prologue` `scripts/analyze_style.py` 在第 282 行附近 prompt 模板里**搜不到** |
| Stage 4.3-4.7 加载 facts 不加载 prologue | grep 各脚本,加载的是 `milkgreen_facts.md` 不是 `milkgreen_profile.md` 或 `prologue.md` |
| `data/analysis/style_profile.json` 重新产出 | 文件存在,`videos_analyzed` 接近 940(959 - 几个空文件) |
| `output/SOUL.md` / `output/SKILL.md` 重新产出 | 与 `_v2.0.md` 对比有实质差异 |
| 抽检 5 条 SOUL.md 论断 | 每条能在 `style_profile.json` 找到至少一条数据支撑 |
| validate_skill.py 9 条对话 | 主观评分 ≥ 4/5 |

---

## 9. 一句话

**2.0 的产物是"用户判断的工整复述"。2.1 的产物应当是"数据归纳 + 产品意图 + 事后验证",三者职责分离。**

用户已经把所有意见出完了,剩下交给你。完成 Phase A-D 之后,把 2.1 产物给用户验收。

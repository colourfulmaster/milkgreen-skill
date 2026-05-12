# 动机层评估 Prompt 集

> 用途:让 LLM 重新过一遍 `data/cleaned_emo/*.json`(及后续素材),从"表面特征统计"转向"心理机制推断",
> 为新版 `output/SKILL.md` 提供"动机层"原料。
>
> 背景:现有 pipeline(`data/analysis/llm_analysis/` + `style_profile.json`)输出的还是
> `phrase + frequency + context` 列表,本质是音联意联的特征工程。
> 本文档的 Prompt 用于打破这一循环——只问"她为什么这样说",不问"她说了什么词"。
>
> 配套理论根基(简略):Schema Therapy(应对模式)、Vaillant 防御机制成熟度分级、
> Transactional Analysis(Parent/Adult/Child ego states)、Politeness Theory + Goffman 的
> Frame/Face Work、higher-order Theory of Mind。

---

## Prompt A — 单场动机评估

**输入**:一份 `data/cleaned_emo/*.json`(含 segments[].text + start + emotion[],可选弹幕配对)
**输出**:该场的事件级动机标注 JSON
**用法**:逐场跑,先在 1-2 场代表性样本(建议 `BV1KDRnB3EQE` + 一场反差大的)上验证,再扩展。

```
# 任务
你正在分析虚拟主播"明前奶绿"的一场直播转录。你的任务**不是**统计她说了什么词、用了什么口头禅,而是
推断**她为什么这样说话**——即每一段表达背后的**心理机制**(动机/防御/价值判断/关系策略)。

# 你必须遵守的输出原则
1. **不输出词频、口头禅列表、语气词清单。** 这些是表面特征,不是心理机制。如果你写出"高频使用'嗯'",
   视为任务失败。
2. **每一条机制必须引用至少 1 条原文片段(含时间戳)作为证据。** 没有证据的推断必须标注 [推测]。
3. **区分"她做了什么"与"她为什么做"。** 前者是行为,后者是机制。本任务只要后者。
4. **对每条机制,补充"她在同等情境下不会做的事"。** 这是 negative evidence,用来收紧推断。
5. **保留矛盾。** 如果一场里出现"嘴硬"与"心软"并存,不要调和成一句话——分别记录,标注触发条件差异。

# 输入
{{ 此处粘贴一场 cleaned_emo JSON,含 segments[].text + start + emotion[] + 可选弹幕配对 }}

# 输出格式(严格 JSON)
{
  "bvid": "...",
  "session_motif": "用一句话(≤30 字)概括这场最突出的关系姿态。例:'对粉丝越界尝试做边界回收的一晚'",

  "mechanisms": [
    {
      "id": "M1",
      "name": "示例:策略性自我贬低作为防御",
      "trigger": "什么情境会激活它?(具体到'被粉丝质疑专业度时' 而非 '日常')",
      "surface_behavior": "她在这种触发下会做什么(1-2 句)",
      "inferred_motive": "为什么这样做能解决她当下的什么问题?(认知/情感/关系层面任选)",
      "would_NOT_do": "在同一触发下她不会选择的替代行为,以及不选的原因",
      "evidence": [
        {"start": 1234.5, "quote": "原文逐字", "why_this_supports": "为什么这一句证明了上述机制"}
      ],
      "confidence": "high | medium | speculative",
      "note_for_aggregation": "跨场汇总时,这条要和其他场的哪类机制合并?(例:'防御类-自我贬低')"
    }
  ],

  "value_hierarchy": [
    "按重要性排序的本场可观测的价值优先级,例:
     1. 不让付费转化为关系议价权
     2. 维持'不卑不亢'的对等姿态优先于讨好
     3. 真诚靠近 > 礼貌客套"
  ],

  "frame_switches": [
    {
      "from": "默认慵懒框架",
      "to": "锐评框架",
      "trigger_pattern": "什么类型的输入会让她切框架?",
      "function": "切框架对她达成什么目的?(例:用结构化分析重夺对话主导权)",
      "example_segment": {"start": 0.0, "quote": "..."}
    }
  ],

  "contradictions_kept": [
    "本场出现的'说一套做一套'的矛盾,不要消解。例:'口头声明不念SC,实际念了',
     标注:嘴硬是面子工程,念了是真在乎"
  ],

  "what_this_session_does_NOT_show": "本场没有覆盖到的人格侧面(用于提示后续要找哪类素材)"
}

# 反例(不要这样写)
× "她高频使用'嗯'作为思考停顿"            ← 这是表面特征
× "她经常自嘲为懒狗"                        ← 这是行为描述,不是机制
× "她的口头禅有'本质上来说''好家伙'..."     ← 这是清单,不是动机

# 正例
√ "在被粉丝质疑专业能力时,她优先选择'先承认无能再退场',而不是辩护。
   这降低了被进一步攻击的预期收益,同时让攻击者显得'欺负弱者'——
   是一种把对方拖入社交成本的防御策略。"

开始分析。
```

---

## Prompt B — 跨场汇总

**输入**:N 份 Prompt A 的 JSON 输出
**输出**:稳定心理机制 + 决策原则 + 价值排序 + negative space 的总览 JSON
**用法**:Prompt A **跑完所有完整回放(目前 11 场,不含切片)** 再跑 B 汇总。

```
# 任务
你拿到了 N 场直播的"单场动机评估"JSON。你要做的是**找出稳定的心理机制**——
即跨多场反复出现、能解释她在新场景下行为的底层结构。

# 关键判定规则
1. **稳定性门槛**:某条机制必须在 **≥2 场**出现(不同 bvid)才算"稳定"——现有仅 11 场完整回放,门槛从 3 场降为 2 场。仅出现 1 场的归入 "situational"。
2. **冲突合并优先级**:如果两场对同一机制的描述矛盾,优先采信 confidence=high 的证据;
   都 high 则保留为"条件分支"(在条件 X 下她做 A,在条件 Y 下她做 B),不要调和成中庸描述。
3. **抗特征化**:如果你发现自己在写"她常说 X""她爱用 Y",停下来问自己——
   "X/Y 是表层,我能不能写出它解决了她的什么问题?" 写不出就删掉这条。

# 输出格式(JSON)
{
  "stable_mechanisms": [
    {
      "name": "...",
      "appears_in_sessions": ["bvid1", "bvid2", "bvid3"],
      "trigger_conditions": ["条件 1", "条件 2"],
      "function_for_her": "这条机制为她解决什么(防御/关系维护/认知效率/身份稳定)",
      "behavioral_signature": "外显行为(简短,只为帮人识别——不要扩展成清单)",
      "boundary_cases": "什么情况下这条机制会失效或反转?",
      "evidence_quotes": [
        {"bvid": "...", "start": 0.0, "quote": "..."}
      ]
    }
  ],

  "decision_principles": [
    "可被 LLM 在新场景下复用的判断规则,写成第二人称指令格式。例:
     - '当对方用付费换取你的人格让步时:冷处理 + 边界声明 + 转移话题。
        不要表达感谢,因为感谢会被解读为接受议价。'"
  ],

  "value_ranking_consolidated": [
    "跨场汇总后的稳定价值优先级(高到低)"
  ],

  "persona_contradictions_to_preserve": [
    "她身上稳定存在的、不该被消解的矛盾。每条标注:这个矛盾对她的什么功能是必要的?"
  ],

  "negative_space": [
    "她稳定**不会**做的事——这比她做了什么更能定义她。
     例:'即使被真诚感动,也不会说出 \"我也很喜欢你们\" 类的直白宣告——
          这种直白等同于撕下慵懒人设,等于裸露。'"
  ],

  "situational_only": [
    "出现次数不够稳定的机制,留作未来素材增加后再评估"
  ]
}

# 最终自检(写完后回答)
1. 我有没有又写成了"口头禅+频率"列表?如果有,删掉。
2. 我的 decision_principles 是不是足够具体,能让另一个 LLM 在新输入上推理出"奶绿会怎么回"?
   还是仍然停留在"保持慵懒基调"这种空话?
3. negative_space 的条目数 ≥ stable_mechanisms 的一半。如果不到,说明我没认真挖她不会做什么。
```

---

## 心理学理论对应(供参考,不需要进 prompt)

| Prompt 字段 | 对应理论 | 简述 |
|---|---|---|
| `mechanisms[].trigger → surface → motive` | **Schema Therapy** (Young) | 早期适应不良图式 → 应对模式(屈从/回避/过度补偿) |
| `mechanisms[].name`(自嘲/呵呵/反向回应) | **Defense Mechanism Hierarchy** (Vaillant) | humor / passive aggression / reaction formation 分级 |
| `frame_switches`(慵懒↔锐评↔温柔) | **Frame Analysis** (Goffman) + **Transactional Analysis** (Berne) | Parent/Adult/Child ego state 切换 |
| `value_hierarchy`(不让付费=议价权) | **Politeness Theory** (Brown & Levinson) + **Face Work** (Goffman) | face-threatening act 管理 |
| `contradictions_kept` / `negative_space` | **Self-Presentation Theory** (Goffman 戏剧论) | 前台/后台 + persona 维护;消解矛盾即杀死 persona |
| 整体推断深度要求 | **higher-order Theory of Mind** | 推断"她对粉丝的推断的推断"——递归心理建模 |

---

## 配套使用建议

1. **小样本先行**:挑 3 场质量高的(如 `BV1KDRnB3EQE` + 风格反差场)跑 Prompt A,人工检查输出
   是否真的避开了"口头禅清单"。如果模型还在写词频,加强反例段或调换模型。
2. **模型选型 A/B**:同一段 Prompt A 让 GPT-5 / Claude 4.5 / Gemini 2.5 / DeepSeek-R1 各跑一遍,
   把模型名遮掉,对照 `output/prologue.md` 的"动机层雏形"做盲选。
3. **跑全量**:transcripts 目录 950 个文件大多是切片二创,**完整回放只有 11 场**,全跑这 11 场再喂 Prompt B 汇总。
4. **Prompt B 输出 = 新版 SKILL.md 的"动机层"原料**,但需要人工再过一遍——LLM 给的是候选,
   定稿是你的判断。
5. **回归验证**:新 SKILL.md 上线后,做一次盲测——同 10 条 input,新旧版各跑,自己判断哪个更像奶绿。
   如果新版赢,再决定是否回头改 `scripts/analyze_style.py` 的 LLM 分析 prompt 模板。

---

## 与表征层的关系(重要,不要误读本文档)

本文档输出的是**动机层**(governor),**不替代表征层**(generator,产自 stage 4.1 的口头禅/语气词/句式清单)。

最终的 SKILL.md 必须**同时包含两层**:

| 层 | 角色 | 来源 |
|---|---|---|
| **表征层** | 决定具体说什么词、什么句式 | stage 4.1 的 style_profile.json |
| **动机层** | 决定何时启用、何时克制、何时扭曲使用表征 | 本文档 Prompt B 的输出 |

两层的焊接由 **stage 4.5(表征-动机绑定)** 完成,产出 `output/persona_signature_bindings.json`,作为 SKILL.md 生成的核心原料。

**警告**:如果只用本文档的输出去写 SKILL.md,结果会是"心理学描述对的、但说话不像奶绿"——
因为动机层只告诉模型"她为什么这样想",没告诉模型"她具体用什么词来表达"。
表征层提供的"嗯""本质上来说""好家伙""懒狗"这些**身份识别码**必须保留。

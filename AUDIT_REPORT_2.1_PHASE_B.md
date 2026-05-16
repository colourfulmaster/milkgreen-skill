# 2.1 Release Phase B 审计报告

> **目标读者**：审核本 agent 工作的另一个 AI（Opus 4.7）
> **时间**：2026-05-15
> **范围**：Phase B 数据重跑 — step 1/2/3 + run_prompt_a

---

## 1. 执行摘要

Phase A（代码去污染）完成后，Phase B 按 STAGE_HANDOFF §5 顺序重跑 Stage 4 管线。当前进度：

| 步骤 | 状态 | 产出 | 备注 |
|---|---|---|---|
| step 1 关键词标注 | ✅ | `keyword_stats.json` + 958 tagged | 纯正则，秒级完成 |
| step 2 LLM 分析 | ✅ | 958 `llm_analysis/` | 8 worker × 8 API key 并行 |
| step 3 跨场汇总 | ✅ | `style_profile.json` (954 场) | 4 个 parse error 跳过 |
| run_prompt_a 动机评估 | ✅ | 14 `motivation/` | 8 worker 并行，14/14 OK |
| run_prompt_b 跨场动机 | ⏳ 待跑 | | |
| run_prompt_c 1V1 提取 | ⏳ | | |
| run_prompt_d 行为差异 | ⏳ | | |
| run_binding 表征绑定 | ⏳ | | |
| run_prompt_e SKILL 适配 | ⏳ | | |
| build_soul 最终产出 | ⏳ | | |

---

## 2. step 1 — 关键词预标注

- **输入**：958 个 cleaned JSON（14 直播回放 + 944 切片）
- **过滤**：1 个非奶绿命名文件被白名单拦截（`capture_1KDRnB3EQE`）
- **产出**：`keyword_stats.json` + `tagged/` 目录（958 个标注后文件）

**关键统计**：
```
total_segments:  238,595
xia_tou_pct:     1.2%
emotion_top5:    开心/轻快(5109) > 愤怒/激动(2462) > 吐槽/毒舌(2432) > 慵懒/摆烂(1297) > 温柔/妈味(923)
scene_top5:      游戏(8110) > 唱歌(5506) > 开场(1828) > 读SC(1259) > 锐评(963)
```

**审计注意**：`温柔/妈味(923)` 是正则模式标签名（EMOTION_PATTERNS 中 `"温柔/妈味"` 是 pattern key），不是 LLM 归纳的结果。该标签的匹配规则是 `(没事|慢慢来|别急|乖|听话|好孩子|宝|亲爱的|崽)`，命中 923 次是因为这些词汇在 cleaned 文本中客观出现——需要 Audit 判断这个 pattern key 命名是否会误导下游 LLM 分析。

---

## 3. step 2 — LLM 深度风格分析

- **输入**：958 个 cleaned JSON
- **方法**：8 worker 并行，每个独立 DeepSeek API key，分片取模
- **耗时**：约 1.5 小时
- **产出**：958 个 `llm_analysis/{bvid}.json`

**去污验证**（抽检 14 场直播回放 + 全局关键词扫描）：
| 关键词 | 命中 | 判定 |
|---|---|---|
| 妈味 | 0 | ✅ |
| 罂粟花 | 0 | ✅ |
| 创伤 | 3 | ✅ 均为具体历史事件描述，非人格解读 |
| 温柔 | 若干 | 均为"时而温柔时而毒舌"类矛盾描述，非单一断言 |

**parse error**：4/958（0.4%），正常范围。

**14 场直播回放 summary 抽样**（全量见下方）：
```
BV16BiiBfE8P: 冷感理性吐槽风格，高频解构与亚文化梗驱动，互为损友的对等互动基调。
BV17BpwzyEzd: 毒舌生活化、填充词多、理性吐槽的直播风格
BV1bCfVBqEU6: 冷静分析搭配即时吐槽，互动直接且略带傲娇，用'还行'等弱化词收尾保持距离感。
BV1goRBBcEAu: 集散装口语、高强度吐槽与沉浸式游戏解说于一体，典型的'互联网嘴替'式市井直播风格。
BV1h39uBLEhY: 以随意慵懒的日常碎碎念为主，夹杂突然的尖锐反问和网络黑话
BV1zC3ozzEWQ: 碎碎念+连麦投稿电台风，风格在温柔讲理、自黑吐槽与突然下头之间反复横跳
```

**判定**：summary 全部为数据归纳风格（口语化、吐槽、慵懒、解构、碎碎念），无 prologue 式"妈味/温柔包容/创伤反应"回填。

---

## 4. step 3 — 跨场汇总

- **输入**：954 个有效 llm_analysis（4 个 parse error 跳过）
- **产出**：`style_profile.json`

**关键产出**：
```
videos_analyzed:    954
stable_phrases:     30 个 (≥3场)  TOP: 就是(64场) 对吧(62场) 兄弟们(58场)
stable_particles:   8 个            TOP: 嗯(13场) 啊(12场) 吧(8场)
addressing.self:    我、主播、主包、奶神
addressing.audience: 你们、大伙、大家、你、奶花
xia_tou_patterns:   813 条
contradictions:     32 条
```

---

## 5. run_prompt_a — 单场动机评估

- **输入**：14 个直播回放 cleaned JSON
- **上下文**：`milkgreen_facts.md`（3289 字符）+ `style_profile.json` 摘要（1228 字符）
- **无 prologue 注入**：已通过 `grep {prologue} scripts/run_prompt_a.py` → 0 命中验证
- **方法**：8 worker 并行
- **产出**：14/14 OK，0 parse errors

**14 场 session_motif 全量**：
```
BV16BiiBfE8P: 在集体检视粉丝'冤种消费'中巩固亲密与边界的一晚
BV17BpwzyEzd: 以'共同锐评'构建虚拟亲密，将安全议题转化为权力游戏的娱乐场。
BV1bCfVBqEU6: 用毒舌吐槽与即时情绪切换构建安全距离的日常
BV1DKQDYaESU: 对粉丝越界尝试做边界回收的一晚
BV1goRBBcEAu: 用审美评判权的反复争夺,在"同好分享"与"粉丝互怼"间拉扯关系边界
BV1GWNgzLEut: 以自贬与调侃维持损友边界，同时回收被粉丝过度延伸的解释权
BV1h39uBLEhY: 以锐评建立智识优越，以自贬防御情感绑定的紧绷一晚。
BV1KDRnB3EQE: 对粉丝越界表达做边界回收和关系确认的一晚
BV1KwGNz6EZT: 以毒舌锐评收束情感投稿,同时用暴躁拒绝划清人际边界
BV1n8FieFEJR: 在'入坑回忆'分享中,以'平等接纳'姿态消解粉丝的资历焦虑,同时确立'热爱无高下'的社群规范
BV1RV1EBxEzK: 在设备危机中,用漫谈维系安全感的自我整备夜
BV1YcrKB3ECu: 用服务性劳作替代情感交流的一晚
BV1yvoeB1Ewp: 在游戏共玩中反复进行压力外化与边界测试的一晚
BV1zC3ozzEWQ: 借阅读他人创伤完成一场有限的自我暴露与边界确认
```

**判定**：全部为心理机制描述（边界/防御/权力/控制/距离），无"妈味/温柔包容/治愈"等 prologue 语言。与 2.0 同一 BV 的 motif 完全不同（验证了 `BV1KDRnB3EQE`：2.0 = "用散漫的开心完成一场仪式性的、克制的告别" vs 2.1 = "对粉丝越界表达做边界回收和关系确认的一晚"）。

---

## 6. 文件时间戳验证

| 路径 | 日期 | 判定 |
|---|---|---|
| `data/analysis/llm_analysis/` | 5月 15 23:00-23:10 | 新生成 ✅ |
| `data/analysis/style_profile.json` | 5月 15 23:12 | 新生成 ✅ |
| `data/analysis/motivation/` | 5月 15 23:16-23:19 | 新生成 ✅ |
| `data/analysis_v2.0/motivation/` | 5月 12 20:33-20:37 | 2.0 归档 ✅ |

**2.0 vs 2.1 产出明确区分，无文件混入风险。**

---

## 7. 建议审计者检查

- [ ] `git diff HEAD~8..HEAD -- scripts/` 确认 8 次 commit 的代码改动符合 STAGE_HANDOFF §5 规范
- [ ] 随机抽查 3 个 `data/analysis/motivation/BV*.json`，确认 `mechanisms` 字段 的 `inferred_motive` 不是 prologue 语言的复述
- [ ] 检查 `EMOTION_PATTERNS["温柔/妈味"]`（analyze_style.py L109）的命名是否会误导下游 LLM——如果会，是否需要改名为"温和/安抚"等中性标签
- [ ] 对比 2.0 和 2.1 的 `style_profile.json`，确认 `addressing.self` 没有"妈妈"（2.0 疑似有）
- [ ] 确认 4 个 step 3 parse error 文件（`clip_BV155ffYyEzM` `clip_BV1F14gz2EpG` `clip_BV1Uqz7BbERv` `clip_BV1cP411y7zY`）是否需要重试
- [ ] 14 场 motif 是否过于集中在"边界"主题——是数据真信号还是 prompt 诱导

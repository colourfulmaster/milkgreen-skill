# Stage 4 进度快照 — 2026-05-12

## 已完成

| 步骤 | 状态 | 说明 |
|------|------|------|
| Stage 1 数据采集 | ✅ | 14 直播回放 + 943 切片 SRT |
| Stage 2 ASR | ✅ | B站 AI 字幕 API |
| Stage 3 文本清洗 | ✅ | import_srt.py + clean_text.py |
| Stage 4.1 关键词标注 | ✅ | keyword_stats.json (233K段) |
| Stage 4.2 LLM 逐文件分析 | ✅ | 957/957 完成 (v4-pro, 8路并行) |
| Stage 4.2 跨场汇总 | ✅ | style_profile.json 已生成 |
| 情绪标注 | ✅ | 14/14 回放 + 922/943 切片 |
| SC 互动提取 | ✅ | 376 条 |
| 投稿提取+标注 | ✅ | 111 篇, letter/react/comment/transition |
| 人物背景档案 | ✅ | milkgreen_profile.md |
| Prologue 最终版 | ✅ | output/prologue.md |
| Laplace CLI | ✅ | /Users/cm_macos/dev/laplace |
| Stage 4.3 Prompt A | ✅ | 14/14 完成 (72条机制, scripts/run_prompt_a.py) |
| Stage 4.4 Prompt B | ✅ | 8条稳定机制+10条决策原则 (motivation_cross_session.json) |
| Stage 4.5 表征-动机绑定 | ✅ | 8条绑定含表面特征+激活/抑制触发 (persona_signature_bindings.json) |
| Stage 4.6 Prompt C | ✅ | 14/14 完成 (138个1V1片段, scripts/run_prompt_c.py) |
| Stage 4.7 Prompt D | ✅ | 8行为差异+3保留+4放弃+3付费去化 (1v1_behavior_diff.json) |
| Stage 4.8 Prompt E | ✅ | SKILL_ai_adaptation.md (4场景+下头梗特化+9条negative) |
| SOUL.md | ✅ | 1283 字符 (output/SOUL.md) |
| SKILL.md | ✅ | 11751 字符 / 293 行 (output/SKILL.md) |
| OpenClaw 部署 | ✅ | v2.0 已部署到 ~/.openclaw/workspace/skills/milkgreen/SKILL.md |

## 待做 (重启后继续)

（全部完成！🎉）

## 关键文件路径

- 项目: /Users/cm_macos/dev/milkGreenSoul
- 清洗数据: data/cleaned/
- 情绪标注: 每个 JSON 带 emotion 字段
- LLM 分析: data/analysis/llm_analysis/
- 风格档案: data/analysis/style_profile.json
- 投稿标注: data/analysis/sc_interactions/submissions_annotated.json
- Opus Prompt: motivation_prompts.md, ai_adaptation_prompts.md
- 动机评估: data/analysis/motivation/BV*.json (14场)
- 跨场汇总: data/analysis/motivation_cross_session.json
- 表征动机绑定: data/analysis/persona_signature_bindings.json
- 1V1 片段: data/analysis/1v1_clips/BV*.json (14场, 138 clips)
- 1V1 行为差异: data/analysis/1v1_behavior_diff.json
- AI 对话适配章节: output/SKILL_ai_adaptation.md
- Prompt D 关键发现: output/prompt_d_key_findings.md
- SOUL.md: output/SOUL.md
- SKILL.md: output/SKILL.md
- Prologue: output/prologue.md
- 背景: output/milkgreen_profile.md
- API Keys (.env): 8个 deepseek-v4-pro key
- 模型: deepseek-v4-pro (需要 max_tokens≥16384 给 reasoning)

## 注意事项

- v4-pro 返回的 reasoning_content 不计入 content，max_tokens 要够大
- 用 WORKER_ID + TOTAL_WORKERS 分片并行
- .env 中 DEEPSEEK_API_KEYS 有全部 8 个 key
- 不要用 flash 或其他模型，只用 deepseek-v4-pro

# 2.1 Release Phase A 审计报告

> **目标读者**：审核本 agent 工作的另一个 AI（Opus 4.7）
> **时间**：2026-05-15
> **范围**：Phase A 全部 7 个脚本的去污染改造

---

## 1. 总体原则

2.0 的核心问题：`prologue.md`（用户直觉理解）和 `milkgreen_profile.md`（含解读）被直接注入 Stage 4 LLM 的 system prompt 作为"校准基准"。LLM 不是从数据归纳风格，而是回填用户预设——产物变成了"用户判断的工整复述"。

2.1 的方法论"序言变尾言"：同一份解读文档，改变它在管线里的位置和角色。

| 阶段 | prologue 角色 | 本次改造 |
|---|---|---|
| Stage 4.2（风格归纳） | ❌ 不加载 | 删除 `{prologue}` + `{profile}` 注入 |
| Stage 4.3-4.5（动机/绑定） | ❌ 解读 / ✅ 事实 | 删 prologue，profile → `milkgreen_facts.md` |
| Stage 4.6（1V1 提取） | ❌ 不需要 | 删 prologue + notes |
| Stage 4.7（run_prompt_d） | ❌ 不需要 | 原本干净，未动 |
| Stage 4.8 + Stage 5（整合） | ✅ 产品规格 | 保留 prologue，标注"clone spec" |

---

## 2. 逐脚本改动详情

### A.1 `scripts/analyze_style.py` — commit `4489ca5`

**改动**：6 处编辑
1. 删除 `PROLOGUE_PATH` / `PROFILE_PATH` 常量
2. 删除 `load_prologue()` / `load_profile()` 函数
3. `STYLE_ANALYSIS_SYSTEM`：删除 `## 主播背景{prologue}` 和 `## 主播人物档案{profile}` 段；`{notes}` 段从 system prompt 移到 user message，加防护框
4. `build_analysis_prompt`：不再调 load_prologue/profile，notes 拼入 user message
5. `CLIP_ANALYSIS_SYSTEM`：删除 `{prologue}` + `{profile}` 段，保留 `{title}`
6. `run_llm_analysis`：删除 load_prologue/profile 调用

**验证过程**：
- 第一版：notes 在 system prompt 内 + 文字警告 → `--limit 3` 测试 → 发现"高冷御姐音"泄漏
- 第二版（加固）：notes 移到 user message（结构分离），重新 `--limit 3` → "高冷御姐音"消失，仅残留单字"冷感"
- 用户确认可接受，全量 step 2 启动

### A.2 `scripts/run_prompt_a.py` — commit `e5e9a67`

**改动**：6 处编辑
1. 删除 `PROLOGUE_PATH`，`PROFILE_PATH` → `FACTS_PATH`
2. `load_context()`：删除 prologue 加载，返回 2 值（facts, style_summary）
3. `PROMPT_A_SYSTEM`：输入说明从"1. 主播人格纲领(prologue)—分析时以此为准"改为"1. 事实背景(facts)—不要据此预判动机"
4. `build_user_prompt()`：删 prologue 参数 + 章节，profile→facts
5. `run_prompt_a()`：删 prologue + profile 参数
6. `main()`：更新 load_context 解包和函数调用

**干跑验证**：`--bvid BV1KDRnB3EQE --sample 50 --dry-run` → facts=3289 字符加载正常，prompt 结构正确。

### A.3 `scripts/run_prompt_b.py` — commit `c446483`

**改动**：1 处编辑
1. `PROLOGUE_PATH` 删除（原本就未在 prompt 中使用），`PROFILE_PATH` → `FACTS_PATH`

**注意**：此脚本的 `PROMPT_B_SYSTEM` 从未注入 prologue 或 profile，改动仅限于常量重命名。跨场动机汇总本身只吃 Prompt A 产出。

### A.4 `scripts/run_prompt_c.py` — commit `0b9231f`

**改动**：5 处编辑
1. 删除 `PROLOGUE_PATH` + `load_prologue()` 函数
2. `build_user_prompt(data_text, prologue, notes)` → `build_user_prompt(data_text)`（1V1 提取是分类任务，不需要任何背景上下文）
3. `run_prompt_c` 签名：删 prologue 参数
4. 删 notes 加载（分类任务不需要场次主题）
5. `main()`：删 `prologue = load_prologue()` 和所有传递

**干跑验证**：prompt 从 ~3500 字符降到 ~1700 字符，减少 50% 噪声。

### A.5 `scripts/run_binding.py` — commit `b7dffc2`

**改动**：4 处编辑
1. 删除 `PROLOGUE_PATH`
2. `BINDING_SYSTEM`：输入说明从"1. 主播人格纲领"+"2. 表征层"+"3. 动机层"改为"1. 表征层"+"2. 动机层"
3. `build_user_prompt(style, motivation, prologue)` → `build_user_prompt(style, motivation)`
4. `main()`：删 prologue 加载

### A.6 `scripts/run_prompt_e.py` — commit `f305de4`

**改动**：1 处编辑（保留 prologue，重标角色）
- prompt 模板中 `# 主播人格纲领` → `# 产品规格 (clone spec)`，加注释：明确说这不是数据归纳结果、而是产品方向

### A.7 `scripts/build_soul.py` — commit `5fd5bfb`

**改动**：6 处编辑（保留 prologue，重标角色 + profile→facts）
1. `PROFILE_PATH` → `FACTS_PATH`（milkgreen_facts.md）
2. `load_inputs()`："人格纲领" → "产品规格 (clone spec)"；"人物背景" → "事实背景"
3. `BUILD_SYSTEM` 模板：所有"来源:prologue"标注改为"产品规格"并注明"数据归纳"区分
4. docstring 更新

---

## 3. 静态验收

| 检查项 | 结果 |
|---|---|
| `analyze_style.py` 无 `{prologue}`/`{profile}` | ✅ |
| `run_prompt_a.py` 无 `PROLOGUE_PATH`/`milkgreen_profile` | ✅ |
| `run_prompt_b.py` 同上 | ✅ |
| `run_prompt_c.py` 无 `prologue`/`PROLOGUE` | ✅ |
| `run_binding.py` 同上 | ✅ |
| `run_prompt_e.py` 保留 `PROLOGUE_PATH` + 标注"产品规格" | ✅ |
| `build_soul.py` 保留 `PROLOGUE_PATH` + 标注"产品规格" + `FACTS_PATH` | ✅ |
| `run_prompt_d.py` 未触碰（原本干净） | ✅ |
| `milkgreen_facts.md` 无解读混入（grep 证实） | ✅ |
| 所有脚本 Python 语法通过 | ✅ |

---

## 4. 当前运行状态

- **step 2 全量 LLM 分析**：后台运行中，8 worker 并行（每个独立 API key）
- **进度**：170/958 文件（~18%），预计剩余 1-1.5 小时
- **产出目录**：`data/analysis/llm_analysis/`
- **已有 2.0 归档**：`data/analysis_v2.0/`（只读对照）

---

## 5. 待办（Phase B-D）

Phase A 完成后，Phase B 数据重跑：
1. step 1（关键词统计）— 纯正则，不调 LLM
2. step 2 全量 — 运行中
3. step 3（跨场汇总）— 等 step 2 完成
4. 依次 `run_prompt_a` → `run_prompt_b` → `run_prompt_c` → `run_prompt_d` → `run_binding` → `run_prompt_e`
5. `build_soul.py` 产出最终 SOUL.md / SKILL.md

---

## 6. 建议审计者检查

- [ ] `git log --oneline HEAD~7..HEAD` 确认 7 次 commit 的 diff 无异常
- [ ] 随机抽查 2 个脚本的 final prompt 模板（如 `analyze_style.py` 的 `STYLE_ANALYSIS_SYSTEM` 和 `run_prompt_a.py` 的 `PROMPT_A_SYSTEM`），确认 prologue 段落不出现
- [ ] 检查 `run_prompt_e.py` 和 `build_soul.py` 的 prologue 角色标注是否为"产品规格"
- [ ] 确认 `milkgreen_facts.md` 确实没有"塑造""创伤""罂粟花"等解读措辞
- [ ] 确认 A.1 的 notes 防护框是否足够——"冷感"泄漏是否在可接受范围
- [ ] 检查 A.3 是否遗漏：`run_prompt_b.py` 的 `FACTS_PATH` 当前未被 prompt 使用，是否需要注入

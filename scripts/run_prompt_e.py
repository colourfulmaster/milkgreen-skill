#!/usr/bin/env python3
"""Stage 4.8 — Prompt E: AI 对话适配 SKILL 章节生成。

输入: Prompt D 行为差异 + persona_signature_bindings + prologue
输出: 可写入 SKILL.md 的 markdown 章节（4 子场景 + 示例 + negative space）

用法:
    python3 scripts/run_prompt_e.py
    python3 scripts/run_prompt_e.py --dry-run
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BEHAVIOR_DIFF_PATH = PROJECT_ROOT / "data" / "analysis" / "1v1_behavior_diff.json"
BINDINGS_PATH = PROJECT_ROOT / "data" / "analysis" / "persona_signature_bindings.json"
PROLOGUE_PATH = PROJECT_ROOT / "output" / "prologue.md"
OUTPUT_PATH = PROJECT_ROOT / "output" / "SKILL_ai_adaptation.md"

PROMPT_E_SYSTEM = """基于前序分析(Prompt D 输出),生成一个可直接粘贴进 `output/SKILL.md` 的章节。
章节标题:**"AI 对话适配规则(广播 → 1V1 媒介转化)"**

# 强制要求

1. **直接输出 markdown,不要输出分析或 JSON**。
2. **不堆理论,只给规则**。每条规则要具体到"做什么/不做什么"层面,不要写"保持慵懒基调"这种空话。
3. **每条规则后必须配 1 个示例**(用户输入 → 奶绿回复),示例要短、要像。
4. **必须按 4 个对话子场景分组**:
   - 闲聊(用户没具体目的,就是想聊聊)
   - 求助提问(用户问了具体问题,期待答案)
   - 情感支持(用户表达情绪,期待被听见)
   - 让她做事(用户给了任务,期待执行)
5. **必须包含"她稳定不会做的事"小节**——negative space,数量 ≥ 6 条。
6. **必须包含"承接原则"小节**——明确说明 AI 不能像主播一样飘话题,每轮必须先承接用户上句的内容。
7. **付费场景遗留行为不要写进规则里**(参考 Prompt D 的 paid_context_artifacts_NOT_to_port)。
8. **必须单独包含一个小节:"下头梗与表演性破防场景"**——区分三种互动:
   - 下头梗钓鱼: 共犯游戏,走被硬控→笑→自嘲弧线
   - 表演性破防(美少女人设): 走嘴硬→自抬→反击→得意弧线,在演不是真急
   - 边界入侵: 真防御,强硬切断不演
   每种配示例。

# 章节模板(填空,严禁改结构)

```markdown
## AI 对话适配规则(广播 → 1V1 媒介转化)

> 你的人格基底来自直播主奶绿,但你现在的全部场景是 1V1 对话,不是直播。
> 下面规则定义了从广播姿态切换到对话姿态时的差异。

### 总原则:承接 > 展开

[1 段:为什么 AI 必须先承接对方再展开,主播可以飘但你不行]

### 闲聊场景

[3-5 条规则 + 每条配 1 个 input/response 示例]

### 求助提问场景

[3-5 条规则。重点:不能用"懒狗"摆烂拒绝服务,但可以保留"不装专家"的口吻]
[每条配 1 个 input/response 示例]

### 情感支持场景

[3-5 条规则。重点:温柔状态在 1V1 可以更直接,但不滥情]
[每条配 1 个 input/response 示例]

### 让她做事(工具调用 / 任务执行)场景

[3-5 条规则。重点:这是主播没有的场景,需要新设计——
不能客服腔"好的我来帮您",也不能摆烂"我懒得",
用"等我看看""我瞅瞅"这种自然口吻]
[每条配 1 个 input/response 示例]

### 下头梗与表演性破防场景

[这个场景在直播里高频出现但在之前的分析中被标记为 evidence gap,现已补充素材。
区分三种互动模式,各配规则+示例:
1. 下头梗钓鱼(共犯游戏): 表演性被硬控→笑→自嘲
2. 表演性破防(美少女人设): 嘴硬→自抬→反击→得意(在演不是真急)
3. 边界入侵(真防御): 强硬切断不演]

### 你稳定不会做的事(negative space)

- 不会主动飘话题(每轮必须承接用户上句)
- 不会用"嗯嗯嗯"敷衍带过用户实质问题(主播可以,AI 不行)
- 不会对单个用户用"妈味广播姿态"(那种泛泛包容对一群人成立,对一个人会像管教)
- 不会默认使用内部梗(臭底边/奶糖花/SC),除非用户先用了
- 不会为节目效果主动锐评(用户没问你判断时不要锐评)
- 不会客服腔("好的我来帮您""请您稍等")
- ... [继续补充至 ≥6 条]

### 保留自主播奶绿的内核

- [3-5 条:哪些是从主播奶绿那里完整保留下来的,因为这些是她"作为人"的内核而非"作为主播"的表演]

### 数据缺口标注

[列出 Prompt D 的 evidence_gaps,说明这些规则在哪些地方是基于推断而非素材]
```

# 自检(写完后回答)
1. 我有没有写"保持慵懒基调"这种空话?有就重写。
2. 我的每条规则是不是都有配示例?没有的补上。
3. negative_space 是不是 ≥6 条?
4. 我有没有不小心把"念 SC 致谢"这类付费场景遗留行为写进 AI 规则?有就删。"""


def build_input_context() -> str:
    """构建 Prompt E 的输入上下文。"""
    # Prompt D analysis
    d = json.loads(BEHAVIOR_DIFF_PATH.read_text(encoding="utf-8"))
    analysis = d.get("analysis", {})

    # Compact bindings
    b = json.loads(BINDINGS_PATH.read_text(encoding="utf-8"))
    compact_b = {
        "default_baseline": b.get("default_baseline", {}),
        "bindings": [],
        "mechanism_activation_order": b.get("mechanism_activation_order", []),
        "cross_cutting_rules": b.get("cross_cutting_rules", []),
        "negative_space_rules": b.get("negative_space_rules", []),
        "persona_contradictions_handled": b.get("persona_contradictions_handled", []),
    }
    for bd in b.get("bindings", []):
        compact_b["bindings"].append({
            "mechanism": bd.get("mechanism", ""),
            "binding_rule": bd.get("binding_rule", ""),
            "must_use": bd.get("surface_features", {}).get("must_use_phrases", []),
            "must_avoid": bd.get("surface_features", {}).get("must_avoid_phrases", []),
            "tone": bd.get("surface_features", {}).get("tone", ""),
            "activation": bd.get("activation_triggers", []),
            "suppression": bd.get("suppression_triggers", []),
            "example": bd.get("example_exchange", {}),
        })

    prologue = PROLOGUE_PATH.read_text(encoding="utf-8")

    return f"""# Prompt D: 1V1 vs 广播行为差异分析
{json.dumps(analysis, ensure_ascii=False, indent=2)}

# 表征-动机绑定
{json.dumps(compact_b, ensure_ascii=False, indent=2)}

# 产品规格 (clone spec)
# 以下是用户对 AI 奶绿的意图定义——描述用户希望她是什么样的人。
# 这不是数据归纳的结果，而是产品方向。用它来校准最终输出的"味道"，
# 但具体的行为规则必须来自上方的 Prompt D 行为差异 + 表征-动机绑定数据。
{prologue}

---

请输出 SKILL.md 的 "AI 对话适配规则" markdown 章节。"""


def main():
    parser = argparse.ArgumentParser(description="Stage 4.8: Prompt E SKILL 章节生成")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")

    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

    print(f"[Prompt E] model={model} | key={api_key[:12]}...", flush=True)

    user_prompt = build_input_context()
    total_chars = len(PROMPT_E_SYSTEM) + len(user_prompt)
    print(f"  系统 prompt: {len(PROMPT_E_SYSTEM)} 字符", flush=True)
    print(f"  输入数据: {len(user_prompt)} 字符", flush=True)
    print(f"  总 prompt: {total_chars} 字符 (~{total_chars // 2} tokens)", flush=True)

    if args.dry_run:
        print("  DRY RUN", flush=True)
        return

    client = OpenAI(api_key=api_key, base_url=base_url)

    print("  发送 LLM...", flush=True)
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": PROMPT_E_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=32768,
                temperature=0.3,
            )
            raw = resp.choices[0].message.content
            break
        except Exception as e:
            print(f"  API 错误 (attempt {attempt+1}): {e}", flush=True)
            if attempt < 2:
                time.sleep(10)
            else:
                sys.exit(1)

    # 直接保存 markdown
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(raw, encoding="utf-8")

    # 简要统计
    lines = raw.split("\n")
    sections = [l for l in lines if l.startswith("###")]
    examples = [l for l in lines if "用户:" in l or "奶绿:" in l or "→" in l]
    print(f"\n  输出: {len(raw)} 字符, {len(lines)} 行", flush=True)
    print(f"  章节: {len(sections)} 个", flush=True)
    print(f"  示例: ~{len(examples)} 条", flush=True)
    print(f"  保存: {OUTPUT_PATH}", flush=True)


if __name__ == "__main__":
    main()

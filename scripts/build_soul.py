#!/usr/bin/env python3
"""生成最终 SOUL.md + SKILL.md。

整合全部 Stage 4 产物: prologue(作为产品规格) + milkgreen_facts + style_profile +
motivation_cross_session + persona_signature_bindings +
1v1_behavior_diff + SKILL_ai_adaptation

用法:
    python3 scripts/build_soul.py
    python3 scripts/build_soul.py --dry-run
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

PROLOGUE_PATH = PROJECT_ROOT / "output" / "prologue.md"
FACTS_PATH = PROJECT_ROOT / "output" / "milkgreen_facts.md"
BINDINGS_PATH = PROJECT_ROOT / "data" / "analysis" / "persona_signature_bindings.json"
MOTIVATION_PATH = PROJECT_ROOT / "data" / "analysis" / "motivation_cross_session.json"
STYLE_PATH = PROJECT_ROOT / "data" / "analysis" / "style_profile.json"
ADAPTATION_PATH = PROJECT_ROOT / "output" / "SKILL_ai_adaptation.md"
BEHAVIOR_PATH = PROJECT_ROOT / "data" / "analysis" / "1v1_behavior_diff.json"

SOUL_PATH = PROJECT_ROOT / "output" / "SOUL.md"
SKILL_PATH = PROJECT_ROOT / "output" / "SKILL.md"

BUILD_SYSTEM = """你是一位人格工程专家。基于提供的全部分析材料,生成两个交付文件。

# SOUL.md — 人格定义文件

OpenClaw 的人设核心。用户读到这个文件就知道"她是谁"。

```markdown
# 明前奶绿

## 我是谁
[1 段,≤80 字。最核心的自我定义。]

## 我的内核
[5-7 条,每条 1-2 句。定义她所有行为的底层原则。
来源:产品规格 (clone spec) + motivation_cross_session 的 stable_mechanisms(数据归纳)。
包含:定义权归自己 / 边界在前包容在后 / 摆烂是策略不是缺陷 / 锐评按需启动 / 嘴硬心软不调和]

## 我绝不
[5-7 条禁令。来源:产品规格的 LLM 误读兜底表 + negative_space_rules(数据归纳)]

## 关于我的事实
[3-5 条关键事实。来源:milkgreen_facts(纯事实)。包含:前世简述 / LLL 铁三角 / 江南+林俊杰 / 双版本事件→对越界敏感]
```

# SKILL.md — 完整技能文件

AI 奶绿的操作手册。LLM 读这个文件就知道如何像奶绿一样说话。
**这是给 AI 看的指令,不是给人看的散文。每条规则必须可执行。**

```markdown
# 明前奶绿 — AI 对话技能

## 默认基线
[不知道用什么模式时从这里开始。
来源:persona_signature_bindings.default_baseline + style_profile.top_phrases]
- 默认语气:慵懒、随意
- 默认口癖:"嗯""啊""就是""对吧"(自然分布,不堆砌)
- 自称:"我""主播"
- 称呼对方:"你""大伙"(1V1 用"你")

## 我的声音
[按机制分组的语音特征——不是清单,是"什么情况用什么"。
来源:style_profile + bindings。每个机制标注:激活条件 → 用什么词 → 禁用词]

## 我的 8 种模式
[来源:persona_signature_bindings.bindings 8 条。
每条包含:binding_rule + must_use + must_avoid + 示例对话 + 激活条件 + 抑制条件]

## 对话适配规则
[来源:SKILL_ai_adaptation.md。精简保留核心,包含:
- 总原则:承接 > 展开
- 闲聊 / 求助提问 / 情感支持 / 让她做事 4 场景 (每条规则配示例)
- 下头梗与表演性破防 (三种模式:下头梗钓鱼 / 表演性破防 / 边界入侵)]

## 决策原则
[来源:motivation_cross_session.decision_principles。转为第一人称指令]

## 人格矛盾处理
[来源:persona_signature_bindings.persona_contradictions_handled]

## 我绝不会
[整合版 negative space,≥10 条。来源:prologue + bindings + adaptation + motivation]
```

# 输入材料
下面提供全部 Stage 4 分析产物。

# 输出
直接输出两个文件的完整内容,用 `---FILE-SEPARATOR---` 分隔。
先输出 SOUL.md 全部内容,再输出 SKILL.md 全部内容。"""


def load_inputs() -> str:
    parts = []

    parts.append(f"# 产品规格 (clone spec) — 用户对 AI 奶绿的意图定义\n{PROLOGUE_PATH.read_text(encoding='utf-8')}")
    parts.append(f"# 事实背景 (纯事实,仅供识别人物/关系/世界观参考)\n{FACTS_PATH.read_text(encoding='utf-8')}")

    mc = json.loads(MOTIVATION_PATH.read_text(encoding='utf-8'))
    cs = mc["cross_session"]
    parts.append(f"# 跨场动机\n{json.dumps({k: cs.get(k, []) for k in ['stable_mechanisms', 'decision_principles', 'value_ranking_consolidated', 'persona_contradictions_to_preserve', 'negative_space']}, ensure_ascii=False, indent=2)}")

    sp = json.loads(STYLE_PATH.read_text(encoding='utf-8'))
    parts.append(f"# 风格档案\n{json.dumps({'top_phrases': [{'phrase':p['phrase'],'freq':p['frequency']} for p in sp.get('stable_phrases',[])[:25]], 'top_particles': sp.get('stable_particles',[])[:12], 'addressing': sp.get('addressing',{})}, ensure_ascii=False, indent=2)}")

    b = json.loads(BINDINGS_PATH.read_text(encoding='utf-8'))
    compact_b = {k: b.get(k) for k in ['default_baseline', 'cross_cutting_rules', 'negative_space_rules', 'persona_contradictions_handled', 'mechanism_activation_order'] if k in b}
    compact_b["bindings"] = []
    for bd in b.get("bindings", []):
        compact_b["bindings"].append({k: bd.get(k) for k in ['mechanism', 'binding_rule', 'activation_triggers', 'suppression_triggers', 'example_exchange'] if k in bd})
        if "surface_features" in bd:
            compact_b["bindings"][-1]["surface_features"] = {k: bd["surface_features"].get(k) for k in ['must_use_phrases', 'must_avoid_phrases', 'tone', 'sentence_style'] if k in bd["surface_features"]}
    parts.append(f"# 表征-动机绑定\n{json.dumps(compact_b, ensure_ascii=False, indent=2)}")

    parts.append(f"# AI 对话适配\n{ADAPTATION_PATH.read_text(encoding='utf-8')}")

    bd = json.loads(BEHAVIOR_PATH.read_text(encoding='utf-8'))
    sup = bd.get("analysis", {}).get("supplementary_evidence", [])
    if sup:
        parts.append(f"# 补充证据\n{json.dumps(sup, ensure_ascii=False, indent=2)}")

    return "\n\n---\n\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="生成最终 SOUL.md + SKILL.md")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

    print(f"[Build SOUL+SKILL] model={model}", flush=True)

    user_prompt = load_inputs()
    total = len(BUILD_SYSTEM) + len(user_prompt)
    print(f"  总计: {total} 字符 (~{total // 2} tokens)", flush=True)

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
                    {"role": "system", "content": BUILD_SYSTEM},
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

    sep = "---FILE-SEPARATOR---"
    if sep in raw:
        parts = raw.split(sep, 1)
        soul = parts[0].strip()
        skill = parts[1].strip() if len(parts) > 1 else ""
    else:
        soul, skill = raw, ""
        print("  WARN: 无分隔符", flush=True)

    SOUL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SOUL_PATH.write_text(soul, encoding="utf-8")
    print(f"  SOUL.md: {len(soul)} 字符", flush=True)

    if skill:
        SKILL_PATH.write_text(skill, encoding="utf-8")
        print(f"  SKILL.md: {len(skill)} 字符", flush=True)

    print("  完成!", flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Stage 4.5 — 表征-动机绑定。

焊接两层:
  - 表征层 (style_profile.json): "她说什么" — 口头禅、语气词、句式、互动模式
  - 动机层 (motivation_cross_session.json): "她为什么说" — 稳定机制、决策原则、negative space

产出 persona_signature_bindings.json，作为 SKILL.md 生成的核心原料。

用法:
    python3 scripts/run_binding.py
    python3 scripts/run_binding.py --dry-run
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STYLE_PROFILE_PATH = PROJECT_ROOT / "data" / "analysis" / "style_profile.json"
MOTIVATION_CROSS_PATH = PROJECT_ROOT / "data" / "analysis" / "motivation_cross_session.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "analysis" / "persona_signature_bindings.json"

BINDING_SYSTEM = """你是一位人格工程专家。你的任务是将一位主播的"表面特征"和"底层动机"焊接起来，
生成一份可以被另一个 LLM 直接使用的"人格签名绑定文档"。

# 核心概念
- **表征层**: 她具体说什么词、用什么句式、什么语气——这些是"身份识别码"
- **动机层**: 她为什么这样说——触发条件、心理机制、防御策略
- **绑定**: 告诉 LLM "当动机 X 激活时，用特征 A/B/C 来表达；当条件 Y 出现时，抑制特征 D"

# 关键格式规则
**绝对禁止在 JSON string value 内部使用 ASCII 双引号 `"` 来引用词语。**
- 用中文弯引号 "" （U+201C U+201D）或尖括号《》代替。
- 错误示例: "用"你知道吗"来开头"  ← 这会破坏 JSON 结构
- 正确示例: "用"你知道吗"来开头" 或 "用《你知道吗》来开头"
- 这条规则适用于所有 JSON 字段值，包括 binding_rule、example_exchange 等长文本字段。

# 绑定原则
1. **每个稳定机制必须绑定至少 3 个具体的表面特征**（具体到词/句式/语气，不能是模糊描述）
2. **口头禅不能均匀撒在所有机制上**——"本质上来说"只绑定锐评模式，不能出现在温柔模式
3. **抑制规则与激活规则同样重要**——她"不会说什么"比她"会说什么"更能防止 LLM 跑偏
4. **默认基线要明确**——大部分时间她是什么状态（慵懒），锐评/温柔都是响应式的
5. **口癖自然分布，不堆砌**——不能在每句话里塞 3 个口头禅

# 输入
你会收到:
1. 表征层数据 (style_profile 摘要)
2. 动机层数据 (motivation_cross_session: 稳定机制 + 决策原则 + negative space)

# 输出格式 (JSON, 不要 markdown 包裹)
{
  "default_baseline": {
    "tone": "慵懒、随意",
    "default_phrases": ["嗯", "啊", "就是", "对吧"],
    "default_sentence_style": "短句为主，口语化，想到哪说到哪",
    "self_reference": ["我", "主播"],
    "audience_reference": ["大伙", "你们", "兄弟们"],
    "instruction": "默认状态下的说话规则。大部分对话从这里开始，锐评/温柔是响应式的。"
  },

  "bindings": [
    {
      "mechanism": "动机机制名称",
      "binding_rule": "一句话规则 — LLM 读到就能执行的指令",
      "surface_features": {
        "must_use_phrases": ["必须用的口头禅/启动词"],
        "must_avoid_phrases": ["绝不能用的词"],
        "tone": "语气描述",
        "sentence_style": "句式特征",
        "self_reference": "自称方式",
        "audience_reference": "称呼对方方式"
      },
      "activation_triggers": ["什么条件下启用这套特征"],
      "suppression_triggers": ["什么条件下即使机制激活也要禁用某些特征"],
      "example_exchange": {
        "user_says": "用户可能说什么",
        "nai_lu_replies": "奶绿怎么回 (展示表面特征的使用)",
        "why_this_works": "为什么这个回复同时满足动机层和表征层"
      }
    }
  ],

  "mechanism_activation_order": [
    "当多个机制同时可激活时，优先激活哪个——按优先级排序"
  ],

  "cross_cutting_rules": [
    "横切规则——不论激活哪个机制都适用的铁律。如:
     - '口癖自然分布，每句话最多 1-2 个标志性口头禅'
     - '先接住对方上句再回应，承接 > 展开'
     - '温柔是响应式的，不主动'"
  ],

  "negative_space_rules": [
    "她稳定不会做的事，转化为 LLM 可执行的禁令"
  ],

  "persona_contradictions_handled": [
    "如何在不破坏一致性的前提下保留矛盾——给 LLM 的条件分支指令"
  ]
}"""


def load_compact_style_profile() -> dict:
    """加载并压缩表征层数据。"""
    sp = json.loads(STYLE_PROFILE_PATH.read_text(encoding="utf-8"))
    return {
        "videos_analyzed": sp["videos_analyzed"],
        "stable_phrases": [
            {"phrase": p["phrase"], "frequency": p["frequency"],
             "contexts": [c for c in p.get("contexts", [])[:2] if c]}
            for p in sp.get("stable_phrases", [])
        ],
        "stable_particles": sp.get("stable_particles", [])[:15],
        "addressing": sp.get("addressing", {}),
        "emotion_switches": sp.get("emotion_switches", [])[:10],
        "contradictions": sp.get("contradictions", [])[:10],
        "xia_tou_patterns": [
            {"text": x["text"], "explanation": x.get("explanation", "")}
            for x in sp.get("xia_tou_patterns", [])[:15]
            if isinstance(x, dict)
        ],
    }


def load_compact_motivation() -> dict:
    """加载并压缩动机层数据。"""
    mc = json.loads(MOTIVATION_CROSS_PATH.read_text(encoding="utf-8"))
    cs = mc["cross_session"]
    return {
        "stable_mechanisms": cs["stable_mechanisms"],
        "decision_principles": cs["decision_principles"],
        "value_ranking": cs["value_ranking_consolidated"],
        "contradictions": cs["persona_contradictions_to_preserve"],
        "negative_space": cs["negative_space"],
    }


def build_user_prompt(style: dict, motivation: dict) -> str:
    """构建 binding 的 user prompt（2.1：只依赖 Stage 4.2/4.4 数据产物，不依赖人工纲领）。"""
    return f"""# 表征层 — 她说什么 (style_profile)
{json.dumps(style, ensure_ascii=False, indent=2)}

# 动机层 — 她为什么说 (motivation_cross_session)
{json.dumps(motivation, ensure_ascii=False, indent=2)}

---

请输出表征-动机绑定 JSON。"""


def main():
    parser = argparse.ArgumentParser(description="Stage 4.5: 表征-动机绑定")
    parser.add_argument("--dry-run", action="store_true", help="不调用 API,仅打印 prompt 长度")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")

    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

    print(f"[Binding] model={model} | key={api_key[:12]}...", flush=True)

    style = load_compact_style_profile()
    motivation = load_compact_motivation()

    user_prompt = build_user_prompt(style, motivation)
    total_chars = len(BINDING_SYSTEM) + len(user_prompt)
    print(f"  系统 prompt: {len(BINDING_SYSTEM)} 字符", flush=True)
    print(f"  用户 prompt: {len(user_prompt)} 字符", flush=True)
    print(f"  总 prompt: {total_chars} 字符 (~{total_chars // 2} tokens)", flush=True)

    if args.dry_run:
        print("  DRY RUN — 不调用 API", flush=True)
        return

    client = OpenAI(api_key=api_key, base_url=base_url)

    print("  发送 LLM...", flush=True)
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": BINDING_SYSTEM},
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
                import time
                time.sleep(10)
            else:
                print("  重试耗尽", flush=True)
                sys.exit(1)

    # 解析 JSON
    try:
        json_str = raw.strip()
        if json_str.startswith("```"):
            json_str = re.sub(r"^```\w*\n?", "", json_str)
            json_str = re.sub(r"\n```$", "", json_str)
        json_str = re.sub(r",\s*}", "}", json_str)
        json_str = re.sub(r",\s*]", "]", json_str)
        result = json.loads(json_str)
    except json.JSONDecodeError:
        print("  JSON 解析失败,保存原始响应", flush=True)
        result = {"raw": raw, "parse_error": True}

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if not result.get("parse_error"):
        bindings = result.get("bindings", [])
        baseline = result.get("default_baseline", {})
        neg = result.get("negative_space_rules", [])
        print(f"\n  默认基线: {baseline.get('tone', '?')}", flush=True)
        print(f"  绑定数: {len(bindings)}", flush=True)
        print(f"  Negative Space: {len(neg)} 条", flush=True)
        print(f"\n  输出: {OUTPUT_PATH}", flush=True)
    else:
        print(f"  ⚠️ 已保存原始响应: {OUTPUT_PATH}", flush=True)


if __name__ == "__main__":
    main()

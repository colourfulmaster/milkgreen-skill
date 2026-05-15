#!/usr/bin/env python3
"""Stage 4.4 — Prompt B: 跨场动机汇总。

读取 14 份单场动机评估 (Prompt A 输出),让 LLM 跨场提炼稳定心理机制,
用于生成 SKILL.md 的"动机层"原料。

用法:
    python3 scripts/run_prompt_b.py
    python3 scripts/run_prompt_b.py --dry-run   # 只打印 prompt 长度
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
MOTIVATION_DIR = PROJECT_ROOT / "data" / "analysis" / "motivation"
OUTPUT_PATH = PROJECT_ROOT / "data" / "analysis" / "motivation_cross_session.json"

# ── Prompt B ──────────────────────────────────────

PROMPT_B_SYSTEM = """你拿到了 N 场直播的"单场动机评估"JSON。你要做的是**找出稳定的心理机制**——
即跨多场反复出现、能解释她在新场景下行为的底层结构。

# 关键判定规则
1. **稳定性门槛**:某条机制必须在 **≥2 场**出现(不同 bvid)才算"稳定"。仅出现 1 场的归入 "situational"。
2. **冲突合并优先级**:如果两场对同一机制的描述矛盾,优先采信 confidence=high 的证据;
   都 high 则保留为"条件分支"(在条件 X 下她做 A,在条件 Y 下她做 B),不要调和成中庸描述。
3. **抗特征化**:如果你发现自己在写"她常说 X""她爱用 Y",停下来问自己——
   "X/Y 是表层,我能不能写出它解决了她的什么问题?" 写不出就删掉这条。

# 输出格式(JSON,不要 markdown 代码块包裹)
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

# 最终自检(写完后在输出末尾附加 self_check 字段):
{
  "self_check": {
    "no_catchphrase_list": true/false,
    "decision_principles_specific": true/false,
    "negative_space_count_vs_mechanisms": "X vs Y"
  }
}

不要输出 markdown 代码块包裹。直接输出 JSON。"""


def load_motivation_data() -> list[dict]:
    """加载所有单场动机评估。"""
    sessions = []
    for f in sorted(MOTIVATION_DIR.glob("BV*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        mot = data.get("motivation", {})
        if mot.get("parse_error"):
            print(f"  SKIP {f.stem}: parse_error", flush=True)
            continue

        # 保留全部字段,但压缩 evidence(每机制只保留 1-2 条最关键的引用)
        compact_mechs = []
        for m in mot.get("mechanisms", []):
            evidence = m.get("evidence", [])
            # 保留所有 evidence 以保持完整性
            compact_mechs.append({
                "id": m.get("id", ""),
                "name": m.get("name", ""),
                "trigger": m.get("trigger", ""),
                "surface_behavior": m.get("surface_behavior", ""),
                "inferred_motive": m.get("inferred_motive", ""),
                "would_NOT_do": m.get("would_NOT_do", ""),
                "confidence": m.get("confidence", ""),
                "note_for_aggregation": m.get("note_for_aggregation", ""),
                "evidence": evidence,  # 保留全部 evidence
            })

        sessions.append({
            "bvid": f.stem,
            "session_motif": mot.get("session_motif", ""),
            "mechanisms": compact_mechs,
            "value_hierarchy": mot.get("value_hierarchy", []),
            "frame_switches": mot.get("frame_switches", []),
            "contradictions_kept": mot.get("contradictions_kept", []),
            "what_not_shown": mot.get("what_this_session_does_NOT_show", ""),
        })

    return sessions


def build_user_prompt(sessions: list[dict]) -> str:
    """构建 Prompt B 的 user message。"""
    sessions_json = json.dumps(sessions, ensure_ascii=False, indent=2)
    return f"""以下是 14 场直播的单场动机评估 JSON。请按 Prompt B 规则做跨场汇总。

# 单场动机评估数据
{sessions_json}

---

请输出跨场汇总 JSON。"""


def main():
    parser = argparse.ArgumentParser(description="Stage 4.4: Prompt B 跨场动机汇总")
    parser.add_argument("--dry-run", action="store_true", help="不调用 API,仅打印 prompt 长度")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")

    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

    print(f"[Prompt B] model={model} | key={api_key[:12]}...", flush=True)

    # 加载单场数据
    sessions = load_motivation_data()
    total_mech = sum(len(s["mechanisms"]) for s in sessions)
    print(f"  加载 {len(sessions)} 场, {total_mech} 条机制", flush=True)

    # 构建 prompt
    user_prompt = build_user_prompt(sessions)
    total_prompt_chars = len(PROMPT_B_SYSTEM) + len(user_prompt)
    print(f"  系统 prompt: {len(PROMPT_B_SYSTEM)} 字符", flush=True)
    print(f"  用户 prompt: {len(user_prompt)} 字符", flush=True)
    print(f"  总 prompt: {total_prompt_chars} 字符 (~{total_prompt_chars // 2} tokens)", flush=True)

    if args.dry_run:
        print("  DRY RUN — 不调用 API", flush=True)
        return

    # 调用 LLM
    client = OpenAI(api_key=api_key, base_url=base_url)

    print("  发送 LLM...", flush=True)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": PROMPT_B_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=32768,
                temperature=0.3,
            )
            raw = resp.choices[0].message.content
            break
        except Exception as e:
            print(f"  API 错误 (attempt {attempt+1}/{max_retries}): {e}", flush=True)
            import time
            if attempt < max_retries - 1:
                time.sleep(10)
            else:
                print("  重试耗尽,退出", flush=True)
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

    # 保存
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump({
            "sessions_analyzed": len(sessions),
            "total_mechanisms_input": total_mech,
            "cross_session": result,
        }, f, ensure_ascii=False, indent=2)

    if not result.get("parse_error"):
        stable = result.get("stable_mechanisms", [])
        principles = result.get("decision_principles", [])
        neg = result.get("negative_space", [])
        sit = result.get("situational_only", [])
        print(f"\n  稳定机制: {len(stable)} 条", flush=True)
        print(f"  决策原则: {len(principles)} 条", flush=True)
        print(f"  Negative Space: {len(neg)} 条", flush=True)
        print(f"  Situational: {len(sit)} 条", flush=True)
        if "self_check" in result:
            sc = result["self_check"]
            print(f"  自检: {sc}", flush=True)
        print(f"\n  输出: {OUTPUT_PATH}", flush=True)
    else:
        print(f"  ⚠️ 已保存原始响应: {OUTPUT_PATH}", flush=True)


if __name__ == "__main__":
    main()

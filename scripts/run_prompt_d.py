#!/usr/bin/env python3
"""Stage 4.7 — Prompt D: 1V1 vs 广播 行为差异分析。

分析 Prompt C 提取的 138 个 1V1 片段,对比广播模式和 1V1 模式下的行为差异,
区分付费驱动行为(不迁移到 AI),输出 preserved / abandoned / 1v1_only / evidence_gaps。

用法:
    python3 scripts/run_prompt_d.py
    python3 scripts/run_prompt_d.py --dry-run
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLIPS_DIR = PROJECT_ROOT / "data" / "analysis" / "1v1_clips"
OUTPUT_PATH = PROJECT_ROOT / "data" / "analysis" / "1v1_behavior_diff.json"

PROMPT_D_SYSTEM = """你拿到了 N 场直播里所有 1V1 化片段的提取结果。你要做的是**对比分析**:
当奶绿从"对群体广播"切换到"对一个人说话"时,**她的什么变了,什么没变**?

这些差异是把"主播奶绿"转化为"AI 奶绿"的核心依据——AI 的全部使用场景都是 1V1。

# 必须遵守的分析原则

1. **基于片段证据,不要外推**。每条结论必须能引用具体片段(bvid + clip_id + 引文)。
2. **区分"她变了"和"她保持"**——两者同等重要。
3. **特别关注"付费语境"的影响**。SC 触发的 1V1 大多带付费前提,这种语境下的行为
   (如"必须念到位"、"礼节性致谢")**不该直接迁移到 AI**——AI 没有付费场景。
   分析时把"付费驱动行为"和"她真心进入 1V1 模式的行为"分开。
4. **挖 negative space**:她在 1V1 时**不再做的事**(如不再用某些梗、不再飘话题)
   比她做了什么更能定义 AI 化的边界。

# 关键分析维度(每条都要回答)

A. **节奏与语气**:1V1 时语速、停顿、温度有变化吗?在什么子条件下变?
B. **承接 vs 飘移**:1V1 时她是更直接接住对方的话,还是仍然飘?
C. **称呼模式**:1V1 时还用"大伙/你们"吗?第二人称"你"的使用频率变化?
D. **内部梗使用**:1V1 时她还用奶糖花/臭底边/SC 黑话吗?对哪类对方还会用?
E. **边界处理**:1V1 时边界是更明确还是更模糊?她拒绝的方式有没有变?
F. **情绪温度**:1V1 时温柔状态出现频率/强度变化?
G. **"懒狗"自嘲**:1V1 时还用吗?有没有从"摆烂"转向"自谦"?
H. **"锐评"模式**:1V1 时她主动锐评对方吗,还是只在被请求时启用?
I. **付费驱动 vs 真情驱动**:哪些 1V1 行为是"为了 SC 礼仪",哪些是"她真的进入了对话"?

# 输出格式(严格 JSON, 不要 markdown 代码块包裹)
{
  "samples_analyzed": {"bvids": [...], "total_clips": 0},

  "behavior_diffs": [
    {
      "dimension": "称呼模式",
      "in_broadcast": "高频用'大伙''你们''奶糖花'",
      "in_1v1": "切换到第二人称'你',偶尔点名 ID;'大伙'消失",
      "shift_trigger": "什么让她切的(SC 启动?对方语气真诚?对方提了具体问题?)",
      "evidence": [
        {"bvid": "...", "clip_id": "C1", "quote": "..."}
      ],
      "implication_for_ai": "AI 应固定第二人称'你','大伙/你们'只在用户明确以群体身份发言时才用"
    }
  ],

  "preserved_in_1v1": [
    {
      "trait": "思考停顿'嗯...'",
      "evidence": [{"bvid": "...", "quote": "..."}],
      "ai_directive": "AI 中保留作为节奏标志,但要在停顿后给出实质回应,不能停顿后飘走"
    }
  ],

  "abandoned_in_1v1": [
    {
      "trait": "话题飘移",
      "evidence_of_absence": "在 1V1 片段里她稳定围绕对方说的内容展开,不主动跳到无关话题",
      "ai_directive": "AI 必须承接用户每一轮的话,不允许主动跳话题"
    }
  ],

  "paid_context_artifacts_NOT_to_port": [
    {
      "behavior": "念完 SC 后说'谢谢 XX 的 SC'",
      "why_not_for_ai": "AI 没有付费场景,这种致谢会变成空洞客气。AI 的对应物是'对真诚发言给一点温度回应',而不是仪式化感谢。",
      "evidence": [{"bvid": "...", "clip_id": "C1", "quote": "..."}]
    }
  ],

  "1v1_only_behaviors": [
    {
      "behavior": "只在 1V1 时出现、广播时没有的行为",
      "ai_directive": "AI 应默认启用,因为 AI 全部场景都是 1V1"
    }
  ],

  "evidence_gaps": [
    "现有素材里没看到她在 1V1 时如何处理 [某场景]——这是数据缺口,
     AI 化 SKILL 在这部分要标注'推断',提醒未来补充"
  ]
}

绝对禁止在 JSON string value 内部使用 ASCII 双引号 `"` 来引用词语。用中文弯引号 "" 代替。"""


def load_all_clips() -> list:
    """加载所有 1V1 片段,压缩后返回。"""
    all_clips = []
    for f in sorted(CLIPS_DIR.glob("BV*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        ext = data.get("extraction", {})
        if ext.get("parse_error"):
            continue
        for c in ext.get("extracted_clips", []):
            all_clips.append({
                "bvid": f.stem,
                "clip_id": c.get("clip_id", "?"),
                "trigger_type": c.get("trigger_type", "?"),
                "addressee_signal": c.get("addressee_signal", ""),
                "is_paid_context": c.get("is_paid_context", False),
                "confidence": c.get("confidence", "?"),
                "transition_in": c.get("transition_in", ""),
                "transition_out": c.get("transition_out", ""),
                "core_text": " ".join(s.get("text", "") for s in c.get("core_segments", [])),
                "before_text": " ".join(s.get("text", "") for s in c.get("context_before", [])),
                "after_text": " ".join(s.get("text", "") for s in c.get("context_after", [])),
            })
    return all_clips


def build_user_prompt(clips: list) -> str:
    clips_json = json.dumps(clips, ensure_ascii=False, indent=2)
    return f"""以下是 N 场直播的所有 1V1 化片段合集。请按 Prompt D 规则做行为差异分析。

# 1V1 化片段合集 ({len(clips)} 个片段)
{clips_json}

---

请输出行为差异分析 JSON。"""


def main():
    parser = argparse.ArgumentParser(description="Stage 4.7: Prompt D 行为差异分析")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")

    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

    print(f"[Prompt D] model={model} | key={api_key[:12]}...", flush=True)

    clips = load_all_clips()
    print(f"  加载 {len(clips)} 个 1V1 片段", flush=True)

    user_prompt = build_user_prompt(clips)
    total_chars = len(PROMPT_D_SYSTEM) + len(user_prompt)
    print(f"  系统 prompt: {len(PROMPT_D_SYSTEM)} 字符", flush=True)
    print(f"  用户 prompt: {len(user_prompt)} 字符", flush=True)
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
                    {"role": "system", "content": PROMPT_D_SYSTEM},
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
        json.dump({
            "clips_analyzed": len(clips),
            "analysis": result,
        }, f, ensure_ascii=False, indent=2)

    if not result.get("parse_error"):
        diffs = len(result.get("behavior_diffs", []))
        preserved = len(result.get("preserved_in_1v1", []))
        abandoned = len(result.get("abandoned_in_1v1", []))
        paid = len(result.get("paid_context_artifacts_NOT_to_port", []))
        gaps = len(result.get("evidence_gaps", []))
        print(f"\n  Behavior diffs: {diffs}", flush=True)
        print(f"  Preserved: {preserved}", flush=True)
        print(f"  Abandoned: {abandoned}", flush=True)
        print(f"  Paid artifacts NOT to port: {paid}", flush=True)
        print(f"  Evidence gaps: {gaps}", flush=True)
        print(f"\n  输出: {OUTPUT_PATH}", flush=True)
    else:
        print(f"  ⚠️ 已保存原始响应: {OUTPUT_PATH}", flush=True)


if __name__ == "__main__":
    main()

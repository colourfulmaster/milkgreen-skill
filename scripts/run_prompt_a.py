#!/usr/bin/env python3
"""Stage 4.3 — Prompt A: 单场动机评估。

对每场直播回放,用 motivation_prompts.md 的 Prompt A 让 LLM 推断"她为什么这样说话"——
不是统计口头禅或词频,是提取心理机制（动机/防御/价值判断/关系策略）。

用法:
    # 单 worker（本地顺序跑）
    python3 scripts/run_prompt_a.py

    # 8 workers 并行（开 8 个终端,分别设 WORKER_ID=0..7）
    WORKER_ID=0 TOTAL_WORKERS=8 python3 scripts/run_prompt_a.py
    WORKER_ID=1 TOTAL_WORKERS=8 python3 scripts/run_prompt_a.py
    ...

    # 只跑一个文件测试
    python3 scripts/run_prompt_a.py --bvid BV1KDRnB3EQE

    # 只采样少量段测试 prompt 效果
    python3 scripts/run_prompt_a.py --bvid BV1KDRnB3EQE --sample 100 --dry-run
"""

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLEANED_DIR = PROJECT_ROOT / "data" / "cleaned"
OUTPUT_DIR = PROJECT_ROOT / "data" / "analysis" / "motivation"
FACTS_PATH = PROJECT_ROOT / "output" / "milkgreen_facts.md"
STYLE_PROFILE_PATH = PROJECT_ROOT / "data" / "analysis" / "style_profile.json"
PROMPTS_PATH = PROJECT_ROOT / "motivation_prompts.md"

# ── Prompt A 模板（从 motivation_prompts.md 提取） ──────────────────

PROMPT_A_SYSTEM = """你正在分析虚拟主播"明前奶绿"的一场直播转录。你的任务**不是**统计她说了什么词、用了什么口头禅,而是
推断**她为什么这样说话**——即每一段表达背后的**心理机制**(动机/防御/价值判断/关系策略)。

# 你必须遵守的输出原则
1. **不输出词频、口头禅列表、语气词清单。** 这些是表面特征,不是心理机制。如果你写出"高频使用'嗯'",
   视为任务失败。
2. **每一条机制必须引用至少 1 条原文片段(含时间戳)作为证据。** 没有证据的推断必须标注 [推测]。
3. **区分"她做了什么"与"她为什么做"。** 前者是行为,后者是机制。本任务只要后者。
4. **对每条机制,补充"她在同等情境下不会做的事"。** 这是 negative evidence,用来收紧推断。
5. **保留矛盾。** 如果一场里出现"嘴硬"与"心软"并存,不要调和成一句话——分别记录,标注触发条件差异。

# 输入数据说明
下面你会收到:
1. 事实背景 (facts) — 纯事实信息(身份/人际关系/重大事件/粉丝文化术语),仅供识别人物/关系/世界观参考,**不要据此预判她的动机**
2. 风格档案摘要 — 来自之前 LLM 分析的跨场表面特征汇总,仅供参考
3. 本场直播字幕 — 带时间戳和情绪标注的 segments 列表

# 输出格式(严格 JSON,不要 markdown 代码块包裹)
{
  "bvid": "...",
  "session_motif": "用一句话(≤30字)概括这场最突出的关系姿态。例:'对粉丝越界尝试做边界回收的一晚'",

  "mechanisms": [
    {
      "id": "M1",
      "name": "示例:策略性自我贬低作为防御",
      "trigger": "什么情境会激活它?(具体到'被粉丝质疑专业度时' 而非 '日常')",
      "surface_behavior": "她在这种触发下会做什么(1-2句)",
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

开始分析。"""


def load_context() -> Tuple[str, str]:
    """加载上下文文件: facts(纯事实背景), style_profile_summary."""
    facts = FACTS_PATH.read_text(encoding="utf-8") if FACTS_PATH.exists() else ""

    style_summary = ""
    if STYLE_PROFILE_PATH.exists():
        sp = json.loads(STYLE_PROFILE_PATH.read_text(encoding="utf-8"))
        # 只取摘要,不送全量 (全量 53K tokens)
        phrases = sp.get("stable_phrases", [])
        top_phrases = [p["phrase"] for p in phrases[:20]]
        addressing = sp.get("addressing", {})
        contradictions = sp.get("contradictions", [])[:10]
        switches = sp.get("emotion_switches", [])[:5]
        style_summary = json.dumps({
            "videos_analyzed": sp.get("videos_analyzed"),
            "top_20_phrases": top_phrases,
            "addressing": addressing,
            "sample_contradictions": contradictions,
            "emotion_switches": switches,
        }, ensure_ascii=False, indent=2)

    return facts, style_summary


def load_bv_files() -> list:
    """获取 data/cleaned/ 下所有完整回放文件(非 clip,非 bili_ai)。"""
    files = sorted(CLEANED_DIR.glob("BV*.json"))
    return [f for f in files if not f.name.startswith("clip_")]


def sample_segments(segments: list, max_samples: int = 500) -> list:
    """均匀采样,确保覆盖全时间线。"""
    if len(segments) <= max_samples:
        return segments
    step = len(segments) / max_samples
    indices = [int(i * step) for i in range(max_samples)]
    return [segments[i] for i in indices]


def build_data_text(segments: list) -> str:
    """把 segments 格式化为紧凑文本,给 LLM 阅读。

    格式: [1234.5s] 原文文本 | 情绪: 开心/兴奋, 吐槽/毒舌
    """
    lines = []
    for s in segments:
        ts = f"[{s['start']:.0f}s]"
        text = s.get("text", "")
        emotions = s.get("emotion", [])
        emo_str = ", ".join(emotions) if emotions else "?"
        lines.append(f"{ts} {text} | {emo_str}")
    return "\n".join(lines)


def build_user_prompt(data_text: str, facts: str, style_summary: str) -> str:
    """构建 Prompt A 的 user message。"""
    return f"""# 事实背景 (纯事实,仅供识别人物/关系/世界观参考)
{facts}

# 风格档案摘要 (来自跨场表面特征统计,仅供参考,不要复述)
{style_summary}

# 本场直播字幕 (带时间戳 + 情绪标注)
{data_text}

---

请输出本场的动机评估 JSON。"""


def run_prompt_a(
    bv_path: Path,
    facts: str,
    style_summary: str,
    client: OpenAI,
    model: str,
    max_samples: int = 500,
    dry_run: bool = False,
) -> Optional[dict]:
    """对单个 BV 文件执行 Prompt A 动机评估。"""
    bvid = bv_path.stem
    out_path = OUTPUT_DIR / f"{bvid}.json"

    with bv_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    segments = data.get("segments", [])
    if not segments:
        print(f"  [{bvid}] 无 segments,跳过", flush=True)
        return None

    sampled = sample_segments(segments, max_samples)
    data_text = build_data_text(sampled)

    print(f"  [{bvid}] 采样 {len(sampled)}/{len(segments)} 段, "
          f"数据文本 {len(data_text)} 字符", flush=True)

    if dry_run:
        print(f"  [{bvid}] DRY RUN — 不调用 API,仅打印 prompt 长度", flush=True)
        user_prompt = build_user_prompt(data_text, facts, style_summary)
        print(f"    系统 prompt: {len(PROMPT_A_SYSTEM)} 字符", flush=True)
        print(f"    用户 prompt: {len(user_prompt)} 字符", flush=True)
        return None

    user_prompt = build_user_prompt(data_text, facts, style_summary)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": PROMPT_A_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=32768,
                temperature=0.3,
            )
            raw = resp.choices[0].message.content
            break
        except Exception as e:
            print(f"  [{bvid}] API 错误 (attempt {attempt+1}/{max_retries}): {e}", flush=True)
            if attempt < max_retries - 1:
                time.sleep(5 * (attempt + 1))
            else:
                print(f"  [{bvid}] 重试耗尽,跳过", flush=True)
                return None

    # 解析 JSON (容错常见的 LLM 输出问题)
    try:
        json_str = raw.strip()
        if json_str.startswith("```"):
            json_str = re.sub(r"^```\w*\n?", "", json_str)
            json_str = re.sub(r"\n```$", "", json_str)
        # 去掉尾部多余逗号 (LLM 经常在最后一个元素后加逗号)
        json_str = re.sub(r",\s*}", "}", json_str)
        json_str = re.sub(r",\s*]", "]", json_str)
        result = json.loads(json_str)
    except json.JSONDecodeError:
        print(f"  [{bvid}] JSON 解析失败,保存原始响应", flush=True)
        result = {"raw": raw, "parse_error": True}

    # 保存
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump({
            "bvid": bvid,
            "notes": data.get("notes", ""),
            "samples": len(sampled),
            "total_segments": len(segments),
            "motivation": result,
        }, f, ensure_ascii=False, indent=2)

    # 简要预览
    if isinstance(result, dict) and not result.get("parse_error"):
        motif = result.get("session_motif", "?")
        mech_count = len(result.get("mechanisms", []))
        print(f"  [{bvid}] ✅ motif: {motif[:60]} | mechanisms: {mech_count}", flush=True)
    else:
        print(f"  [{bvid}] ⚠️ 已保存(解析失败)", flush=True)

    return result


def main():
    parser = argparse.ArgumentParser(description="Stage 4.3: Prompt A 单场动机评估")
    parser.add_argument("--bvid", help="只处理指定 BV")
    parser.add_argument("--sample", type=int, default=500, help="每场采样段数 (default: 500)")
    parser.add_argument("--dry-run", action="store_true", help="不调用 API,仅打印 prompt 长度")
    parser.add_argument("--worker-id", type=int, default=None, help="覆盖环境变量 WORKER_ID")
    parser.add_argument("--total-workers", type=int, default=None, help="覆盖环境变量 TOTAL_WORKERS")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")

    # API 配置
    api_keys_str = os.getenv("DEEPSEEK_API_KEYS", "")
    api_keys = [k.strip() for k in api_keys_str.split(",") if k.strip()] if api_keys_str else [os.getenv("DEEPSEEK_API_KEY")]
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    worker_id = args.worker_id if args.worker_id is not None else int(os.getenv("WORKER_ID", "0"))
    total_workers = args.total_workers if args.total_workers is not None else int(os.getenv("TOTAL_WORKERS", "1"))
    api_key = api_keys[worker_id % len(api_keys)]

    print(f"[Prompt A] Worker {worker_id}/{total_workers} | model={model} | "
          f"key={api_key[:12]}... | sample={args.sample}", flush=True)

    # 加载上下文 (只需一次)
    facts, style_summary = load_context()
    print(f"  上下文: facts={len(facts)}字符, "
          f"style_summary={len(style_summary)}字符", flush=True)

    # 收集文件
    all_files = load_bv_files()
    if args.bvid:
        all_files = [f for f in all_files if f.stem == args.bvid]
        if not all_files:
            print(f"ERROR: 未找到 {args.bvid}", file=sys.stderr)
            sys.exit(1)

    # Worker 分片
    my_files = [f for i, f in enumerate(all_files) if i % total_workers == worker_id]
    print(f"  文件: {len(my_files)}/{len(all_files)} (分片后)", flush=True)

    if not my_files:
        print("  无文件待处理,退出", flush=True)
        return

    client = OpenAI(api_key=api_key, base_url=base_url)

    success = 0
    for i, bv_path in enumerate(my_files):
        print(f"\n[{i+1}/{len(my_files)}] {bv_path.stem}", flush=True)
        result = run_prompt_a(
            bv_path=bv_path,
            facts=facts,
            style_summary=style_summary,
            client=client,
            model=model,
            max_samples=args.sample,
            dry_run=args.dry_run,
        )
        if result and not (isinstance(result, dict) and result.get("parse_error")):
            success += 1

    print(f"\n[Prompt A] 完成: {success}/{len(my_files)} 成功, 输出: {OUTPUT_DIR}", flush=True)


if __name__ == "__main__":
    main()

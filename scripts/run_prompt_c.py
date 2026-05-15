#!/usr/bin/env python3
"""Stage 4.6 — Prompt C: 1V1 化片段提取。

从每场直播 cleaned JSON 中提取所有奶绿"对一个具体的人说话"的片段:
  - SC 回应 (nc/ac/sc 等)
  - 点名回应
  - 持续对话
  - 私语化语气切换

用法:
    python3 scripts/run_prompt_c.py
    WORKER_ID=0 TOTAL_WORKERS=8 python3 scripts/run_prompt_c.py
    python3 scripts/run_prompt_c.py --bvid BV1KDRnB3EQE --dry-run
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLEANED_DIR = PROJECT_ROOT / "data" / "cleaned"
OUTPUT_DIR = PROJECT_ROOT / "data" / "analysis" / "1v1_clips"
PROMPT_C_SYSTEM = """你正在从虚拟主播"明前奶绿"的一场直播转录里,**提取所有她切换到"对一个具体的人说话"模式的片段**。
这些片段是稀缺的——绝大多数时间她是在对一群匿名观众广播。我们要的是她**短暂 1V1 化**的瞬间。

# 1V1 化片段的识别信号(满足任一即可)

1. **SC 回应**:文本中出现 "SC"、"nc"、"ac"、"sc"(都是 SuperChat 的写法),
   或 "谢谢 XX"、"XX 的 SC" 这类感谢付费用户的措辞。
   注:字幕里 nc/ac 是 SC 的同音变体。
2. **点名回应**:她念出一个具体 ID/用户名,然后接一段回应内容。
   例:"XX 你说..."、"XX 问的这个..."、"我看到 XX 在说..."
3. **持续对话**:连续多个 segments 都在回应**同一具体内容/具体人**(而不是扫弹幕飘)。
4. **私语化语气切换**:语速变慢、语气变温、用第二人称"你"而非"你们/大伙",
   且明显不是在跟整体观众说话。

# 提取规则

- **保留前后文**:每个片段抓 2-3 条 context_before(铺垫)+ 2-3 条 context_after(收尾,
  通常是切回广播)。这能帮后续分析"她进入和退出 1V1 模式时的过渡"。
- **宁多不少**:边界模糊时纳入,标 confidence: medium。后续分析阶段会再过滤。
- **不要合并**:不同 1V1 时刻就算时间相近也分开记录,因为可能针对不同的人。
- **必须保留时间戳**:为后续核验。

# 输出格式(严格 JSON,不要 markdown 代码块包裹)
{
  "bvid": "...",
  "session_total_segments": 0,
  "extracted_clips_count": 0,

  "extracted_clips": [
    {
      "clip_id": "C1",
      "start": 1234.5,
      "end": 1280.0,
      "trigger_type": "SC | named_reply | sustained_1v1 | private_tone_shift",
      "addressee_signal": "她在回应谁/什么(尽量从原文提取,例:'某用户的SC,内容是...''某ID的提问')",
      "is_paid_context": true,
      "confidence": "high | medium",

      "core_segments": [
        {"start": 1234.5, "text": "..."}
      ],
      "context_before": [
        {"start": 1228.0, "text": "..."}
      ],
      "context_after": [
        {"start": 1281.0, "text": "..."}
      ],

      "transition_in": "她从广播切到 1V1 的过渡方式(1句描述)",
      "transition_out": "她从 1V1 切回广播的过渡方式(1句描述)"
    }
  ],

  "extraction_notes": "本场 1V1 化片段的整体分布特点。例:'集中在前 30 分钟,主要为 SC 回应';
                       '全场散布,多为对老粉点名';'几乎没有 1V1 化片段,本场以杂谈广播为主'"
}

# 注意
- 如果整场没有任何 1V1 化片段,extracted_clips 返回空数组,extraction_notes 说明原因。
- 不要为了凑数把"对群体的吐槽"算作 1V1。判断标准:"如果删掉这段,只有一个具体的人会觉得被忽略"。
- **绝对禁止在 JSON string value 内部使用 ASCII 双引号 `"` 来引用词语。用中文弯引号 "" 代替。**

开始分析。"""


def load_bv_files() -> list:
    files = sorted(CLEANED_DIR.glob("BV*.json"))
    return [f for f in files if not f.name.startswith("clip_")]


def sample_segments(segments: list, max_samples: int = 800) -> list:
    """均匀采样。1V1 片段稀少,采样密度比 Prompt A 更高。"""
    if len(segments) <= max_samples:
        return segments
    step = len(segments) / max_samples
    indices = [int(i * step) for i in range(max_samples)]
    return [segments[i] for i in indices]


def build_data_text(segments: list) -> str:
    """紧凑格式: [1234s] 文本 | 情绪: tag1, tag2"""
    lines = []
    for s in segments:
        ts = f"[{s['start']:.0f}s]"
        text = s.get("text", "")
        emotions = s.get("emotion", [])
        emo_str = ", ".join(emotions) if emotions else "?"
        lines.append(f"{ts} {text} | {emo_str}")
    return "\n".join(lines)


def build_user_prompt(data_text: str) -> str:
    """构建 Prompt C 的 user message（2.1：分类抽取不需要背景上下文，纯看 segments 格式）。"""
    return f"""# 本场直播字幕 (带时间戳 + 情绪标注)
{data_text}

---

请提取本场所有 1V1 化片段 JSON。"""


def run_prompt_c(
    bv_path: Path,
    client: OpenAI,
    model: str,
    max_samples: int = 800,
    dry_run: bool = False,
) -> Optional[dict]:
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

    print(f"  [{bvid}] 采样 {len(sampled)}/{len(segments)} 段, 数据 {len(data_text)} 字符", flush=True)

    if dry_run:
        user_prompt = build_user_prompt(data_text)
        print(f"    系统 prompt: {len(PROMPT_C_SYSTEM)} 字符", flush=True)
        print(f"    用户 prompt: {len(user_prompt)} 字符", flush=True)
        return None

    user_prompt = build_user_prompt(data_text)

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": PROMPT_C_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=32768,
                temperature=0.3,
            )
            raw = resp.choices[0].message.content
            break
        except Exception as e:
            print(f"  [{bvid}] API 错误 (attempt {attempt+1}): {e}", flush=True)
            if attempt < 2:
                time.sleep(10)
            else:
                return None

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
        print(f"  [{bvid}] JSON 解析失败,保存原始响应", flush=True)
        result = {"raw": raw, "parse_error": True}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump({
            "bvid": bvid,
            "samples": len(sampled),
            "total_segments": len(segments),
            "extraction": result,
        }, f, ensure_ascii=False, indent=2)

    if not result.get("parse_error"):
        n = result.get("extracted_clips_count", len(result.get("extracted_clips", [])))
        notes_out = result.get("extraction_notes", "?")[:60]
        print(f"  [{bvid}] ✅ {n} 片段 | {notes_out}", flush=True)
    else:
        print(f"  [{bvid}] ⚠️ 已保存(解析失败)", flush=True)

    return result


def main():
    parser = argparse.ArgumentParser(description="Stage 4.6: Prompt C 1V1 化片段提取")
    parser.add_argument("--bvid", help="只处理指定 BV")
    parser.add_argument("--sample", type=int, default=800, help="采样段数 (default: 800)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--worker-id", type=int, default=None)
    parser.add_argument("--total-workers", type=int, default=None)
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")

    api_keys_str = os.getenv("DEEPSEEK_API_KEYS", "")
    api_keys = [k.strip() for k in api_keys_str.split(",") if k.strip()] if api_keys_str else [os.getenv("DEEPSEEK_API_KEY")]
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    worker_id = args.worker_id if args.worker_id is not None else int(os.getenv("WORKER_ID", "0"))
    total_workers = args.total_workers if args.total_workers is not None else int(os.getenv("TOTAL_WORKERS", "1"))
    api_key = api_keys[worker_id % len(api_keys)]

    print(f"[Prompt C] Worker {worker_id}/{total_workers} | model={model} | "
          f"key={api_key[:12]}... | sample={args.sample}", flush=True)

    all_files = load_bv_files()
    if args.bvid:
        all_files = [f for f in all_files if f.stem == args.bvid]
        if not all_files:
            print(f"ERROR: 未找到 {args.bvid}", file=sys.stderr)
            sys.exit(1)

    my_files = [f for i, f in enumerate(all_files) if i % total_workers == worker_id]
    print(f"  文件: {len(my_files)}/{len(all_files)} (分片后)", flush=True)

    if not my_files:
        print("  无文件待处理", flush=True)
        return

    client = OpenAI(api_key=api_key, base_url=base_url)

    success = 0
    for i, bv_path in enumerate(my_files):
        print(f"\n[{i+1}/{len(my_files)}] {bv_path.stem}", flush=True)
        result = run_prompt_c(
            bv_path=bv_path,
            client=client,
            model=model,
            max_samples=args.sample,
            dry_run=args.dry_run,
        )
        if result and not (isinstance(result, dict) and result.get("parse_error")):
            success += 1

    print(f"\n[Prompt C] 完成: {success}/{len(my_files)} 成功, 输出: {OUTPUT_DIR}", flush=True)


if __name__ == "__main__":
    main()

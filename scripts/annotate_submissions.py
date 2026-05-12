#!/usr/bin/env python3
"""深度标注投稿: 用 LLM 分离来信原文 / 主播反应 / 评论 / 过渡。

输入: data/analysis/sc_interactions/submissions.json
输出: data/analysis/sc_interactions/submissions_annotated.json

每条 segment 标注为: letter(来信) | react(实时反应) | comment(评论) | transition(过渡)
"""

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = PROJECT_ROOT / "data" / "analysis" / "sc_interactions" / "submissions.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "analysis" / "sc_interactions" / "submissions_annotated.json"

ANNOTATION_SYSTEM = """你是一位直播内容分析师。你的任务是对虚拟主播"明前奶绿"读观众投稿的片段进行精细标注。

输入是一段投稿的全文（含主播在念读过程中的实时反应和后续评论）。

请将每一段标注为以下类型之一:
- **letter**: 观众投稿的原文内容(主播在念读)
- **react**: 主播念读过程中的实时反应(插话、吐槽、感叹、追问)
- **comment**: 主播念完后的评论、分析、扩展讨论
- **transition**: 主播切换到下一个话题/投稿的过渡语

标注规则:
1. 主播的"嗯"、"哈哈"、"呵"单独出现时,标为 react
2. 主播对投稿内容的直接回应(如"这啥呀"、"听起来好可怜")标为 react
3. 主播基于投稿展开自己的观点(如"本质上来说...")标为 comment
4. "我们看一下"、"下一个"等切换语标为 transition
5. 投稿原文通常语气中性、叙事连贯、用第一人称讲故事
6. 主播的反应/评论通常带情绪标记、使用第二人称"你"

输出格式(严格 JSON,不要 markdown 包裹):
{
  "segments": [
    {"text": "原文", "label": "letter|react|comment|transition", "note": "简短说明(可选)"}
  ],
  "summary": {
    "letter_ratio": 0.6,
    "react_ratio": 0.2,
    "comment_ratio": 0.15,
    "transition_ratio": 0.05,
    "topics": ["本期投稿涉及的主题标签"],
    "tone": "本期投稿的整体情绪基调"
  }
}"""


def annotate_submission(client, sub: dict, model: str) -> dict | None:
    """对单篇投稿做 LLM 标注。"""
    segs = sub["submit_segments"]
    if not segs:
        return None

    # 构建输入文本
    text_lines = []
    for s in segs:
        typ = s.get("type", "?")
        emo = s.get("emotion", [])
        t = s["text"]
        emo_str = f"[{','.join(emo)}]" if emo else ""
        prefix = "[读]" if typ == "reading" else "[应]"
        text_lines.append(f"{prefix}{emo_str} {t}")

    user_text = "以下是主播读一篇观众投稿的全文:\n\n" + "\n".join(text_lines)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": ANNOTATION_SYSTEM},
                {"role": "user", "content": user_text},
            ],
            max_tokens=4096,
            temperature=0.2,
        )
        raw = resp.choices[0].message.content
    except Exception as e:
        print(f"  LLM error: {e}", flush=True)
        return None

    # 解析 JSON
    json_str = raw.strip()
    if json_str.startswith("```"):
        json_str = re.sub(r"^```\w*\n?", "", json_str)
        json_str = re.sub(r"\n```$", "", json_str)

    try:
        result = json.loads(json_str)
    except json.JSONDecodeError:
        print(f"  JSON parse failed, raw: {raw[:200]}", flush=True)
        return {"raw": raw, "parse_error": True}

    return result


def main():
    load_dotenv(PROJECT_ROOT / ".env")
    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
    )
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    with INPUT_PATH.open() as f:
        data = json.load(f)

    submissions = data["submissions"]
    print(f"标注 {len(submissions)} 篇投稿...", flush=True)

    annotated = []
    for i, sub in enumerate(submissions):
        bvid = sub["bvid"]
        dur = sub.get("duration", 0)
        segs_n = sub.get("segment_count", 0)
        print(f"  [{i+1}/{len(submissions)}] {bvid} ({segs_n}段 {dur:.0f}s)", end=" ", flush=True)

        result = annotate_submission(client, sub, model)
        if result and not result.get("parse_error"):
            sub["annotation"] = result
            print("✓", flush=True)
        elif result:
            sub["annotation"] = result
            print("⚠️ raw", flush=True)
        else:
            print("✗", flush=True)

        annotated.append(sub)

    data["submissions"] = annotated
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 统计
    letter_ratios = []
    for s in annotated:
        ann = s.get("annotation", {})
        if ann.get("summary", {}).get("letter_ratio"):
            letter_ratios.append(ann["summary"]["letter_ratio"])

    print(f"\n完成: {len(annotated)} 篇")
    if letter_ratios:
        print(f"平均来信占比: {sum(letter_ratios)/len(letter_ratios):.0%}")
    print(f"输出: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""深度标注投稿: 多 worker 并行, 4 个 API key 同时跑。

输入: data/analysis/sc_interactions/submissions.json
输出: data/analysis/sc_interactions/submissions_annotated.json

用法: python3 scripts/annotate_submissions.py --worker-id 0-3
"""

import json, os, re, sys, time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = PROJECT_ROOT / "data/analysis/sc_interactions/submissions.json"
OUTPUT_DIR = PROJECT_ROOT / "data/analysis/sc_interactions"

API_KEYS = [
    "sk-9f409a96f9b04eabb88d104fdb43fa4a",
    "sk-9a4e295bd0b14f6daeb4e1a085aee91d",
    "sk-304359d63a0d4c58951f305e513edc10",
    "sk-0e6b59f22b9a44419fe509c3467e4f91",
]
BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-v4-pro"

SYSTEM_PROMPT = """标注虚拟主播"明前奶绿"读观众投稿的片段。

每行是一段字幕。标注为:
- letter: 观众投稿原文(主播念读中,叙事连贯,用第一人称)
- react: 主播念读过程中实时插话(吐槽/感叹/追问/哈哈),情绪外露
- comment: 主播念完后展开的分析、锐评、建议
- transition: 切到下一个投稿("我们看一下""下一个""好了拜拜")

规则:
1. 念稿中途的"嗯""哈哈""卧槽""好家伙"→ react
2. 念稿中插入的追问(如"这啥意思啊""你确定吗")→ react
3. 念完后的大段分析→ comment
4. 投稿原文特征是叙事性、连贯、中性语气
5. 输出纯JSON数组,每元素对应输入的一行: {"text":"原文","label":"letter|react|comment|transition"}
6. 你的reasion字段时间不计入付费token，不要担心字数，慢慢想

不要markdown包裹,直接输出JSON数组。"""


def get_worker_subs(worker_id, total_workers):
    """交替分配: worker0→0,4,8... worker1→1,5,9..."""
    with INPUT_PATH.open() as f:
        data = json.load(f)
    subs = data["submissions"]
    return [subs[i] for i in range(worker_id, len(subs), total_workers)]


def annotate_one(client, submission):
    segs = submission["submit_segments"]
    if not segs:
        return None

    lines = []
    for s in segs:
        emo = s.get("emotion", [])
        emo_str = f" [{','.join(emo)}]" if emo else ""
        lines.append(f"{emo_str} {s['text']}")

    chunk_size = 80
    all_labels = []

    for i in range(0, len(lines), chunk_size):
        chunk = lines[i:i + chunk_size]
        user_text = "\n".join(chunk)

        raw = None
        for attempt in range(3):
            try:
                r = client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_text},
                    ],
                    max_tokens=16384,
                    temperature=0.1,
                )
                raw = r.choices[0].message.content
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(3)
                else:
                    print(f"    API错误(重试3次失败): {e}", flush=True)
                    return None

        if not raw:
            print(f"    API返回空", flush=True)
            return None

        json_str = raw.strip()
        json_str = re.sub(r"^```\w*\n?", "", json_str)
        json_str = re.sub(r"\n```$", "", json_str)

        try:
            chunk_labels = json.loads(json_str)
        except json.JSONDecodeError:
            chunk_labels = [{"text": l, "label": "letter"} for l in chunk]
            print(f"    JSON解析失败,fallback letter", flush=True)

        all_labels.extend(chunk_labels)

    return all_labels


def main():
    parser = __import__('argparse').ArgumentParser()
    parser.add_argument("--worker-id", type=int, required=True, help="0-3")
    args = parser.parse_args()

    wid = args.worker_id
    api_key = API_KEYS[wid]
    client = OpenAI(api_key=api_key, base_url=BASE_URL)

    subs = get_worker_subs(wid, len(API_KEYS))
    total_segs = sum(s["segment_count"] for s in subs)
    print(f"Worker {wid}: {len(subs)}篇, {total_segs}段 (key: {api_key[:12]}...)", flush=True)

    results = []
    for idx, sub in enumerate(subs):
        bvid = sub["bvid"]
        segs_n = sub.get("segment_count", 0)
        dur = sub.get("duration", 0)
        print(f"  [{idx+1}/{len(subs)}] {bvid} ({segs_n}段 {dur:.0f}s)", end=" ", flush=True)

        labels = annotate_one(client, sub)
        if labels:
            ln = len(labels)
            letter_n = sum(1 for l in labels if l.get("label") == "letter")
            react_n = sum(1 for l in labels if l.get("label") == "react")
            comment_n = sum(1 for l in labels if l.get("label") == "comment")
            trans_n = sum(1 for l in labels if l.get("label") == "transition")
            sub["annotation"] = {
                "labels": labels,
                "summary": {"letter": letter_n, "react": react_n, "comment": comment_n, "transition": trans_n},
            }
            print(f"✓ 来信:{letter_n}({letter_n/ln*100:.0f}%) 反应:{react_n} 评论:{comment_n}", flush=True)
        else:
            sub["annotation"] = {"error": "annotate failed"}
            print("✗", flush=True)
        results.append(sub)

    # 写入本 worker 的输出文件
    out_path = OUTPUT_DIR / f"submissions_w{wid}.json"
    with out_path.open("w") as f:
        json.dump({"worker_id": wid, "count": len(results), "submissions": results}, f, ensure_ascii=False, indent=2)
    print(f"\nWorker {wid} done → {out_path}", flush=True)


if __name__ == "__main__":
    main()

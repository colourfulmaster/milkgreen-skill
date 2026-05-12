#!/usr/bin/env python3
"""投稿提取器 2.0 — 基于标记点分段,不再用滑动窗口。

逻辑:
    1. 收集所有"来自XX投稿"为 START 标记
    2. 两个 START 之间的内容 = 一个投稿单元
    3. 输出完整投稿段落(含主播反应)

用法:
    python3 scripts/extract_submissions.py
"""

import json
import re
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLEANED_DIR = PROJECT_ROOT / "data" / "cleaned"
OUTPUT_DIR = PROJECT_ROOT / "data" / "analysis" / "sc_interactions"

START_RE = re.compile(r"来自.{2,20}(?:的)?投稿")  # "来自自行车南话的投稿"
END_IMPLICIT = re.compile(r"我们看(?:一下|看)?(?:下一个|下个)")  # 切换到下一个


def extract_submissions(segments: list, bvid: str, title: str) -> list:
    """基于 START 标记分段,提取投稿。"""
    # 找所有 START 位置
    starts = []
    for i, s in enumerate(segments):
        t = s.get("text", "")
        if START_RE.search(t):
            starts.append(i)

    if not starts:
        return []

    submissions = []
    for idx, si in enumerate(starts):
        # 投稿内容: 从 START 行到下一 START(或末尾)
        ei = starts[idx + 1] if idx + 1 < len(starts) else len(segments)

        # 但 END_IMPLICIT 可能在 START 之前出现,需要往回找
        # 从 ei-1 往前搜,如果在 START+5 之后找到 "我们看一下下一个",截断
        for j in range(si + 5, ei):
            t = segments[j].get("text", "")
            if END_IMPLICIT.search(t):
                ei = j
                break

        submit_segs = segments[si:ei]
        if len(submit_segs) < 5:  # 太短不是真投稿
            continue

        dur = submit_segs[-1].get("end", 0) - submit_segs[0].get("start", 0)

        # 统计情绪
        emo_count = defaultdict(int)
        for s in submit_segs:
            for e in s.get("emotion", []):
                emo_count[e] += 1

        # 区分念读段 vs 反应段
        reading_segs = []
        reaction_segs = []
        for s in submit_segs:
            t = s.get("text", "")
            emo = s.get("emotion", [])
            # 反应段特征: 短、带情绪标记、有"哈哈""呵呵"等
            if len(t) < 15 and any(e in str(emo) for e in ["开心", "愤怒", "Laughter"]):
                reaction_segs.append(s)
            else:
                reading_segs.append(s)

        submissions.append({
            "bvid": bvid,
            "title": title,
            "start_time": submit_segs[0].get("start", 0),
            "end_time": submit_segs[-1].get("end", 0),
            "duration": round(dur, 1),
            "segment_count": len(submit_segs),
            "reading_segments": len(reading_segs),
            "reaction_segments": len(reaction_segs),
            "emotion_distribution": dict(emo_count),
            "tags": [],  # LLM 后续填充: 主题标签
            "full_text": " ".join(s.get("text", "") for s in submit_segs),
            "submit_segments": [
                {"start": s.get("start", 0), "end": s.get("end", 0),
                 "text": s.get("text", ""), "emotion": s.get("emotion", []),
                 "type": "reading" if s in reading_segs else "reaction"}
                for s in submit_segs
            ],
        })

    return submissions


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_subs = []

    for f in sorted(CLEANED_DIR.glob("BV*.json")):
        with f.open() as fp:
            d = json.load(fp)

        bvid = d.get("bvid", f.stem)
        title = d.get("title", "")
        segs = d.get("segments", [])
        if not segs:
            continue

        subs = extract_submissions(segs, bvid, title)
        if subs:
            print(f"{bvid}: {len(subs)} 投稿")
            all_subs.extend(subs)

    # 保存
    out_path = OUTPUT_DIR / "submissions.json"
    with out_path.open("w") as fp:
        json.dump({
            "total": len(all_subs),
            "submissions": all_subs,
        }, fp, ensure_ascii=False, indent=2)

    print(f"\n共 {len(all_subs)} 篇投稿 → {out_path}")


if __name__ == "__main__":
    main()

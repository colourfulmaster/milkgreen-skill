#!/usr/bin/env python3
"""从情绪标注后的字幕中提取 SC 互动 + 观众投稿 片段。

提取规则:
    1. SC 感谢句式: "谢谢***的sc/nc/ac"
    2. SC 内容念读: 主播念出 SC 内容 + 可能的回应
    3. 观众投稿: "投稿"、"南花投稿"、"XX投稿" 等标记
    4. 上下文窗口: 提取前后各 3-5 条,保留互动全貌

输出: data/analysis/sc_interactions.json (全部直播回放 + 切片中命中的)
    data/analysis/sc_by_bv/{bvid}.json (按 BV 拆分)

用法:
    python3 scripts/extract_sc.py
    python3 scripts/extract_sc.py --bvid BV1KDRnB3EQE
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLEANED_DIR = PROJECT_ROOT / "data" / "cleaned"
OUTPUT_DIR = PROJECT_ROOT / "data" / "analysis" / "sc_interactions"

# SC 识别模式
SC_PATTERNS = [
    # 直接感谢 SC
    re.compile(r"谢谢.{0,20}(?:的|了).{0,10}(?:[sS][cC]|[nN][cC]|[aA][cC]|醒目留言|舰长|提督|总督)"),
    # nc/ac 独立出现(可能是 SC 的同音/缩写)
    re.compile(r"(?:^|\s)([nN][cC]|[aA][cC])(?:\s|$)"),
    # SC 内容标记
    re.compile(r"[sS][cC][：:\s]"),
    re.compile(r"醒目留言[：:]"),
    # 付费用户称呼
    re.compile(r"(?:舰长|提督|总督).{0,10}(?:说|问|的|投稿)"),
]

# 投稿开始标记(精确匹配,避免误触发)
SUBMIT_START_PATTERNS = [
    re.compile(r"来自.{2,15}(?:的)?投稿"),       # "来自自行车南话的投稿"
    re.compile(r"我们看(?:一下|看)?(?:来自)?.{0,10}(?:的)?投稿"),  # "我们看一下来自XX的投稿"
    re.compile(r"下一个.{0,10}投稿"),             # "下一个XXX投稿"
]

# 投稿结束标记
SUBMIT_END_PATTERNS = [
    re.compile(r"我们看(?:一下|看)?下?一?个"),    # "我们看看下一个"
    re.compile(r"好(?:了|的).{0,5}下一个"),       # "好了下一个"
    re.compile(r"嗯.?下一个"),                    # "嗯下一个"
    re.compile(r"来自.{2,15}(?:的)?投稿"),        # 下一个投稿开始
]

# 主播反应标记(投稿中途的插话)
REACTION_PATTERNS = [
    re.compile(r"^(?:哈哈|呵呵|嘿嘿|哎|啊|嗯|卧槽|草)[^a-zA-Z]{0,20}$"),
]

# SC 短互动: 小窗口
SC_CONTEXT_BEFORE = 3
SC_CONTEXT_AFTER = 5

# 投稿可能上百字, 需要大窗口捕获全文
SUBMIT_CONTEXT_BEFORE = 10
SUBMIT_CONTEXT_AFTER = 20


def is_sc_line(text: str) -> bool:
    for pat in SC_PATTERNS:
        if pat.search(text):
            return True
    return False


def is_submit_start(text: str) -> bool:
    for pat in SUBMIT_START_PATTERNS:
        if pat.search(text):
            return True
    return False

def is_submit_end(text: str) -> bool:
    for pat in SUBMIT_END_PATTERNS:
        if pat.search(text):
            return True
    return False


def extract_interactions(segments: list, bvid: str, title: str) -> list:
    """从 segments 中提取 SC/投稿 互动片段。"""
    interactions = []

    i = 0
    while i < len(segments):
        seg = segments[i]
        text = seg.get("text", "")

        hit_type = None
        if is_sc_line(text):
            hit_type = "sc"
        elif is_submit_start(text):
            hit_type = "submit"

        if hit_type == "sc":
            ctx_start = max(0, i - SC_CONTEXT_BEFORE)
            ctx_end = min(len(segments), i + SC_CONTEXT_AFTER + 1)
            context_before = segments[ctx_start:i]
            core = segments[i]
            context_after = segments[i + 1:ctx_end]

            interactions.append({
                "bvid": bvid, "title": title, "type": "sc",
                "trigger_start": core.get("start", 0),
                "trigger_text": text,
                "emotion": core.get("emotion", []),
                "context_before": [
                    {"start": s.get("start", 0), "text": s.get("text", ""),
                     "emotion": s.get("emotion", [])} for s in context_before
                ],
                "core": {"start": core.get("start", 0), "end": core.get("end", 0),
                         "text": text, "emotion": core.get("emotion", [])},
                "context_after": [
                    {"start": s.get("start", 0), "text": s.get("text", ""),
                     "emotion": s.get("emotion", [])} for s in context_after
                ],
            })
            i = ctx_end - 1

        elif hit_type == "submit":
            # 投稿: 从 START 标记读到 END 标记(或下一个 START)
            j = i + 1
            while j < len(segments):
                t = segments[j].get("text", "")
                if is_submit_end(t) or is_submit_start(t):
                    break
                j += 1
            # j 指向 END 标记(不包含),往回找到真正的投稿内容结束
            submit_end = j
            # 投稿内容: i(标记) + 1 到 submit_end
            submit_segs = segments[i:submit_end]

            interactions.append({
                "bvid": bvid, "title": title, "type": "submit",
                "trigger_start": segments[i].get("start", 0),
                "trigger_text": text,
                "emotion": segments[i].get("emotion", []),
                "submit_segments": [
                    {"start": s.get("start", 0), "end": s.get("end", 0),
                     "text": s.get("text", ""), "emotion": s.get("emotion", [])}
                    for s in submit_segs
                ],
                "submit_duration": round(
                    submit_segs[-1].get("end", 0) - submit_segs[0].get("start", 0), 1
                ) if submit_segs else 0,
                "segment_count": len(submit_segs),
            })
            i = submit_end - 1

        i += 1

    return interactions


def process_file(json_path: Path) -> list:
    """处理单个 JSON 文件。"""
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    segments = data.get("segments", [])
    if not segments:
        return []

    bvid = data.get("bvid", json_path.stem)
    title = data.get("title", "")
    interactions = extract_interactions(segments, bvid, title)

    # 统计情绪
    emo_count = defaultdict(int)
    for itx in interactions:
        for e in itx.get("emotion", []):
            emo_count[e] += 1

    return interactions


def main():
    parser = argparse.ArgumentParser(description="提取 SC 互动内容")
    parser.add_argument("--bvid", help="只处理指定 BV")
    parser.add_argument("--no-clips", action="store_true", help="跳过切片文件")
    args = parser.parse_args()

    if args.bvid:
        json_files = [CLEANED_DIR / f"{args.bvid}.json"]
    else:
        json_files = sorted(CLEANED_DIR.glob("*.json"))
        if args.no_clips:
            json_files = [f for f in json_files if not f.name.startswith("clip_")]

    print(f"[extract_sc] 处理 {len(json_files)} 个文件", flush=True)

    all_interactions = []
    bv_stats = {}

    for i, f in enumerate(json_files):
        interactions = process_file(f)
        if not interactions:
            continue

        sc_count = sum(1 for itx in interactions if itx["type"] == "sc")
        sub_count = sum(1 for itx in interactions if itx["type"] == "submit")

        all_interactions.extend(interactions)

        bvid = interactions[0]["bvid"]
        bv_stats[bvid] = {
            "title": interactions[0]["title"],
            "sc": sc_count,
            "submit": sub_count,
            "total": len(interactions),
        }

        if (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(json_files)}] 已提取 {len(all_interactions)} 条互动", flush=True)

    # 保存全量
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_path = OUTPUT_DIR / "all_sc_interactions.json"
    with all_path.open("w", encoding="utf-8") as f:
        json.dump({
            "total_interactions": len(all_interactions),
            "sc_count": sum(1 for itx in all_interactions if itx["type"] == "sc"),
            "submit_count": sum(1 for itx in all_interactions if itx["type"] == "submit"),
            "bv_stats": bv_stats,
            "interactions": all_interactions,
        }, f, ensure_ascii=False, indent=2)

    # 统计
    sc_total = sum(1 for itx in all_interactions if itx["type"] == "sc")
    sub_total = sum(1 for itx in all_interactions if itx["type"] == "submit")

    print(f"\n[extract_sc] 完成:", flush=True)
    print(f"  SC 互动: {sc_total} 条", flush=True)
    print(f"  投稿互动: {sub_total} 条", flush=True)
    print(f"  涉及 BV: {len(bv_stats)} 个", flush=True)

    # Top BVs
    top_sc = sorted(bv_stats.items(), key=lambda x: x[1]["sc"], reverse=True)[:10]
    print(f"\n  SC 最多的视频:", flush=True)
    for bvid, stats in top_sc:
        print(f"    {bvid}: SC={stats['sc']} 投稿={stats['submit']} {stats['title'][:50]}", flush=True)

    print(f"\n  输出: {all_path}", flush=True)


if __name__ == "__main__":
    main()

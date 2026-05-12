#!/usr/bin/env python3
"""将 SRT 字幕文件按 BV 号合并,转成项目 JSON 格式。

输入: data/srt/ 下的 .srt 文件(Chrome 插件导出)
输出: data/transcripts/{bvid}.json

规则:
    - 按文件名前缀分 P: 无数字=P0, 1-=P1, 2-=P2
    - 同 BV 下各 P 按顺序拼接,时间戳不做偏移(各 P 内部时间戳独立)
    - 同 BV 的 P0/P1/P2 各保存为独立段落,保留原时间线

用法:
    python3 scripts/import_srt.py [--srt-dir data/srt/]
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRT_DIR = PROJECT_ROOT / "data" / "srt"
OUTPUT_DIR = PROJECT_ROOT / "data" / "transcripts"

TIME_RE = re.compile(
    r"(\d+):(\d+):(\d+)[\.,](\d+)\s*-->\s*(\d+):(\d+):(\d+)[\.,](\d+)"
)
BV_RE = re.compile(r"BV[0-9a-zA-Z]+")


def parse_srt(path: Path) -> tuple[list[dict], float]:
    """解析单个 SRT,返回 (segments, duration_seconds)。"""
    content = path.read_text(encoding="utf-8")
    blocks = content.strip().split("\n\n")
    segments: list[dict] = []
    max_end = 0.0

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        m = TIME_RE.match(lines[1])
        if not m:
            continue
        h1, m1, s1, ms1 = map(int, m.groups()[:4])
        h2, m2, s2, ms2 = map(int, m.groups()[4:])
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
        text = " ".join(lines[2:])
        segments.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
        })
        max_end = max(max_end, end)

    return segments, round(max_end, 2)


def extract_bvid(filename: str) -> str:
    """从文件名提取 BV 号。"""
    m = BV_RE.search(filename)
    return m.group(0) if m else "unknown"


def extract_p_order(filename: str) -> int:
    """提取 P 序号: 无数字前缀 = 0, 1- = 1, 2- = 2。"""
    base = Path(filename).name
    if base.startswith("1-"):
        return 1
    if base.startswith("2-"):
        return 2
    if base.startswith("3-"):
        return 3
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="SRT → JSON 转换")
    parser.add_argument("--srt-dir", default=str(DEFAULT_SRT_DIR), help="SRT 文件目录")
    args = parser.parse_args()

    srt_dir = Path(args.srt_dir)
    if not srt_dir.exists():
        print(f"ERROR: {srt_dir} 不存在", file=sys.stderr)
        sys.exit(1)

    srt_files = sorted(srt_dir.glob("*.srt"))
    if not srt_files:
        print(f"ERROR: {srt_dir} 下无 .srt 文件", file=sys.stderr)
        sys.exit(1)

    # 按 BV 分组
    groups: dict[str, dict[int, tuple[Path, list[dict], float]]] = defaultdict(dict)

    for f in srt_files:
        bvid = extract_bvid(f.name)
        pn = extract_p_order(f.name)
        segs, dur = parse_srt(f)
        groups[bvid][pn] = (f, segs, dur)
        print(f"  {bvid} P{pn}: {len(segs)} 条, {dur:.0f}s ({dur/60:.1f}min)")

    print(f"\n共 {len(groups)} 个 BV, {len(srt_files)} 个文件\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for bvid in sorted(groups.keys()):
        parts = groups[bvid]
        all_segs: list[dict] = []

        for pn in sorted(parts.keys()):
            fpath, segs, dur = parts[pn]
            all_segs.append({
                "part": pn,
                "source": fpath.name,
                "duration": dur,
                "segments": segs,
            })

        # 合并所有分 P 的 segments（保持各 P 内部时间戳不变）
        merged: list[dict] = []
        for part in all_segs:
            for seg in part["segments"]:
                seg["part"] = part["part"]
                merged.append(seg)

        total_dur = max((s["end"] for s in merged), default=0)
        out_path = OUTPUT_DIR / f"{bvid}.json"

        # 保留已有 notes
        notes = ""
        if out_path.exists():
            try:
                with out_path.open("r", encoding="utf-8") as f:
                    old = json.load(f)
                notes = old.get("notes", "")
            except Exception:
                pass

        with out_path.open("w", encoding="utf-8") as f:
            json.dump({
                "bvid": bvid,
                "notes": notes,
                "parts": [
                    {"pn": p["part"], "source": p["source"], "duration": p["duration"]}
                    for p in all_segs
                ],
                "duration_seconds": total_dur,
                "total_segments": len(merged),
                "segments": merged,
            }, f, ensure_ascii=False, indent=2)

        print(f"[{bvid}] {len(all_segs)}P, {len(merged)} 条 → {out_path}")

    print(f"\n完成,输出: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""将切片 SRT 文件按 BV 号转成项目 JSON，保留视频标题。

输入: data/srt/ 下 BV 开头的 .srt 文件(切片下载脚本输出)
输出: data/transcripts/clip_{bvid}.json

文件名格式: {bvid}_{标题}.srt
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRT_DIR = PROJECT_ROOT / "data" / "srt"
OUTPUT_DIR = PROJECT_ROOT / "data" / "transcripts"

TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[\.,](\d+)\s*-->\s*(\d+):(\d+):(\d+)[\.,](\d+)")


def parse_srt(path):
    segments = []
    content = path.read_text(encoding="utf-8")
    blocks = content.strip().split("\n\n")
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
        segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    return segments


def main():
    srt_files = sorted(SRT_DIR.glob("*.srt"))
    if not srt_files:
        print("ERROR: 无 SRT 文件", file=sys.stderr)
        sys.exit(1)

    # 只处理切片文件 (BV 开头), 跳过直播回放 (【直播回放】开头)
    clip_files = [f for f in srt_files if not f.name.startswith("【")]
    print(f"共 {len(srt_files)} 个 SRT, 其中 {len(clip_files)} 个切片\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total_segs = 0
    total_dur = 0
    count = 0

    for f in clip_files:
        name = f.stem  # 去掉 .srt
        # 格式: {bvid}_{标题}
        # 注意 bvid 是 BV 开头 + 10 位
        bv_match = re.match(r'(BV[0-9a-zA-Z]{10})_(.*)', name)
        if not bv_match:
            print(f"  SKIP: {f.name} (无法解析 BV)", flush=True)
            continue

        bvid = bv_match.group(1)
        title = bv_match.group(2)[:200]  # 限制长度

        segs = parse_srt(f)
        if not segs:
            print(f"  SKIP: {f.name} (空)", flush=True)
            continue

        dur = segs[-1]["end"]

        out_path = OUTPUT_DIR / f"clip_{bvid}.json"
        with out_path.open("w", encoding="utf-8") as fout:
            json.dump({
                "bvid": bvid,
                "title": title,
                "source": "clip",
                "duration_seconds": round(dur, 2),
                "total_segments": len(segs),
                "segments": segs,
            }, fout, ensure_ascii=False, indent=2)

        count += 1
        total_segs += len(segs)
        total_dur += dur

        if count % 100 == 0:
            print(f"  [{count}] {bvid} {title[:40]}... {len(segs)}段 {dur:.0f}s", flush=True)

    print(f"\n转换完成: {count} 个 JSON", flush=True)
    print(f"总段数: {total_segs}  总时长: {total_dur/60:.0f}min = {total_dur/3600:.1f}h", flush=True)
    print(f"输出: {OUTPUT_DIR}/clip_*.json", flush=True)


if __name__ == "__main__":
    main()

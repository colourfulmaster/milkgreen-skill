#!/usr/bin/env python3
"""批量下载切片音频 + 情绪标注。

流程:
    1. 从 data/srt/ 找切片文件名提取 BV
    2. 下载音频(m4a,仅音频)
    3. 跑 SenseVoice 情绪标注

用法:
    python3 scripts/batch_clip_audio.py --download    # 只下载
    python3 scripts/batch_clip_audio.py --tag         # 只标注
    python3 scripts/batch_clip_audio.py --all         # 下载+标注
    python3 scripts/batch_clip_audio.py --limit 10    # 测试前10个
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRT_DIR = PROJECT_ROOT / "data" / "srt"
MEDIA_DIR = PROJECT_ROOT / "data" / "raw_media" / "clips"
CLEANED_DIR = PROJECT_ROOT / "data" / "cleaned"

CLIP_BV_RE = re.compile(r"^(BV[0-9a-zA-Z]{10})_")


def list_clips():
    """从 SRT 目录获取切片 BV 列表。"""
    clips = []
    for f in sorted(SRT_DIR.glob("*.srt")):
        m = CLIP_BV_RE.match(f.name)
        if m:
            bvid = m.group(1)
            title = f.stem[len(bvid) + 1:][:100]
            clips.append({"bvid": bvid, "title": title, "srt": f})
    return clips


def download_audio(bvid: str, output_dir: Path) -> bool:
    """下载单个切片的音频。"""
    out_path = output_dir / f"{bvid}.m4a"
    if out_path.exists() and out_path.stat().st_size > 1000:
        return True  # 已存在

    url = f"https://www.bilibili.com/video/{bvid}/"
    result = subprocess.run([
        "yt-dlp",
        "-f", "bestaudio[ext=m4a]/bestaudio",
        "-o", str(out_path),
        "--no-playlist",
        "--cookies-from-browser", "chrome",
        url,
    ], capture_output=True, text=True, timeout=120)

    return result.returncode == 0 and out_path.exists()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--tag", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    do_download = args.all or args.download
    do_tag = args.all or args.tag

    clips = list_clips()
    if args.limit:
        clips = clips[:args.limit]

    print(f"切片: {len(clips)} 个")

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    if do_download:
        downloaded = 0
        for i, clip in enumerate(clips):
            bvid = clip["bvid"]
            ok = download_audio(bvid, MEDIA_DIR)
            if ok:
                downloaded += 1
            if (i + 1) % 100 == 0:
                print(f"  下载: {downloaded}/{i+1}", flush=True)
        print(f"  下载完成: {downloaded}/{len(clips)}", flush=True)

    if do_tag:
        print("标语标注请通过 emotion_tag.py 批量处理", flush=True)
        # 启动 emotion_tag.py --bvids 传入切片列表,分多个 worker


if __name__ == "__main__":
    main()

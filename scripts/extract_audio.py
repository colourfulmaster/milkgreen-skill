#!/usr/bin/env python3
"""阶段 2:音频格式转换 + 切段。

输入:data/raw_media/*.m4a (从 yt-dlp 下载的 AAC 音频,也支持 .mp4/.webm/.mp3/.aac)
输出:data/audio/{原文件 stem}/seg_NNN.wav
      格式:16kHz 单声道 16-bit PCM(whisper 标准输入)
      切段:每段 30 分钟(失败重启友好 + 内存安全 + 进度可见)

跳过策略:
    目标子目录已存在且包含 seg_*.wav → 视为已处理,跳过

为什么切段:
    - whisper.cpp 处理 30 分钟段在 M4 16GB 上稳定不 OOM
    - 阶段 3 转录中途失败,只需重跑失败的段
    - reset_timestamps 让每段从 0 计时,后续合并时按 段索引×段长 加偏移
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "data" / "raw_media"
OUTPUT_DIR = PROJECT_ROOT / "data" / "audio"

SEGMENT_SECONDS = 1800  # 30 分钟
SAMPLE_RATE = 16000     # whisper 推荐
CHANNELS = 1            # 单声道
INPUT_EXTENSIONS = {".m4a", ".mp4", ".webm", ".mp3", ".aac", ".wav"}


def find_inputs() -> list:
    """遍历 raw_media,返回所有支持格式的输入文件,按文件名排序。"""
    if not INPUT_DIR.exists():
        return []
    files = []
    for p in INPUT_DIR.iterdir():
        if p.is_file() and p.suffix.lower() in INPUT_EXTENSIONS:
            files.append(p)
    return sorted(files)


def is_processed(target_dir: Path) -> bool:
    """检查目标子目录是否已处理(存在且包含至少一个 seg_*.wav)。"""
    if not target_dir.exists():
        return False
    return any(target_dir.glob("seg_*.wav"))


def process_one(src: Path) -> int:
    """对单个输入文件做重采样 + 切段。返回生成的段数。"""
    target_dir = OUTPUT_DIR / src.stem

    if is_processed(target_dir):
        existing = sorted(target_dir.glob("seg_*.wav"))
        print(f"[skip] {src.name}")
        print(f"       已存在 {len(existing)} 段,跳过")
        return len(existing)

    target_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = target_dir / "seg_%03d.wav"

    cmd = [
        "ffmpeg",
        "-y",                                  # 覆盖输出(已 is_processed 兜底)
        "-i", str(src),
        "-vn",                                 # 不要视频流
        "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS),
        "-c:a", "pcm_s16le",
        "-map_metadata", "-1",                 # 清空元数据
        "-f", "segment",
        "-segment_time", str(SEGMENT_SECONDS),
        "-reset_timestamps", "1",              # 每段时间戳从 0 开始
        "-loglevel", "warning",                # 减少噪音输出,只看警告和错误
        str(output_pattern),
    ]

    print(f"[run]  {src.name}")
    print(f"       → {target_dir.name}/seg_NNN.wav")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: ffmpeg 失败,返回码 {result.returncode}", file=sys.stderr)
        print("--- ffmpeg stderr (最后 2000 字符) ---", file=sys.stderr)
        print(result.stderr[-2000:], file=sys.stderr)
        sys.exit(1)

    segs = sorted(target_dir.glob("seg_*.wav"))
    total_size_mb = sum(s.stat().st_size for s in segs) / (1024 * 1024)
    print(f"       生成 {len(segs)} 段,合计 {total_size_mb:.1f} MB")
    return len(segs)


def main() -> None:
    inputs = find_inputs()
    if not inputs:
        print(f"ERROR: {INPUT_DIR} 下没有支持的输入文件", file=sys.stderr)
        print(f"       支持的扩展名: {sorted(INPUT_EXTENSIONS)}", file=sys.stderr)
        sys.exit(1)

    print(f"[extract] 输入目录: {INPUT_DIR}")
    print(f"[extract] 输出目录: {OUTPUT_DIR}")
    print(f"[extract] 段长: {SEGMENT_SECONDS} 秒 = {SEGMENT_SECONDS // 60} 分钟")
    print(f"[extract] 待处理: {len(inputs)} 个文件")
    print()

    total_segs = 0
    for src in inputs:
        total_segs += process_one(src)

    print()
    print(f"[extract] 全部完成,共 {total_segs} 段。")


if __name__ == "__main__":
    main()

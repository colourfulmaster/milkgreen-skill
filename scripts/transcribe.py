#!/usr/bin/env python3
"""阶段 3:用 SenseVoice 批量转录(分块处理避 OOM)。

输入:
    data/audio/{stem}/seg_NNN.wav

输出:
    data/transcripts/{stem}.json

SenseVoice:
    - 单段全文(含 <|zh|><|BGM|> 等 token,本脚本自动剥离)
    - 无时间戳
    - 每段 WAV 切成 60s 子块逐一推理避 OOM,再拼接
    - 速度 ~40× 实时,远快于 whisper

跳过策略:
    输出 JSON 已存在 → 跳过该 stem
"""

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from funasr import AutoModel

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "data" / "audio"
OUTPUT_DIR = PROJECT_ROOT / "data" / "transcripts"
TMP_DIR = PROJECT_ROOT / ".tmp_transcribe"

SENSE_TOKEN_RE = re.compile(r"<\|[^|]+\|>")
CHUNK_SECONDS = 60  # 每次推理 60s 音频(~10MB WAV),M4 16GB 稳定


def strip_tokens(text: str) -> str:
    return SENSE_TOKEN_RE.sub("", text).strip()


def build_model() -> AutoModel:
    print(f"[init] 加载模型: iic/SenseVoiceSmall...")
    return AutoModel(model="iic/SenseVoiceSmall", device="cpu", disable_update=True)


def transcribe_seg(model: AutoModel, wav_path: Path) -> str:
    """单段 WAV → 切成 60s 子块 → 逐一送 SenseVoice → 拼接."""
    # 1. ffprobe 获取时长
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=duration", "-of",
         "default=noprint_wrappers=1:nokey=1", str(wav_path)],
        capture_output=True, text=True)
    try:
        duration = float(r.stdout.strip())
    except ValueError:
        return ""

    if duration <= 0:
        return ""

    # 2. 目标子块数
    num_chunks = math.ceil(duration / CHUNK_SECONDS)

    # 3. 把大 WAV 一次性切成子块
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    base = wav_path.stem
    pattern = str(TMP_DIR / f"{base}_chunk_%03d.wav")
    subprocess.run([
        "ffmpeg", "-y", "-i", str(wav_path),
        "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
        "-reset_timestamps", "1",
        "-c", "copy", "-loglevel", "error",
        pattern,
    ], capture_output=True)

    # 4. 逐一推理
    chunks = []
    for i in range(num_chunks):
        chunk_path = TMP_DIR / f"{base}_chunk_{i:03d}.wav"
        if not chunk_path.exists():
            continue
        result = model.generate(
            input=str(chunk_path),
            language="zh",
            text_norm="woitn",
        )
        raw = result[0].get("text", "")
        chunks.append(strip_tokens(raw))
        os.unlink(chunk_path)

    return " ".join(chunks)


def transcribe_stem(model: AutoModel, stem_dir: Path, out_path: Path) -> bool:
    """转录一个 stem 的所有 wav 段,合并输出。返回 True=新转录。"""
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"  [skip] {out_path.name}")
        return False

    wav_files = sorted(stem_dir.glob("seg_*.wav"))
    if not wav_files:
        print(f"  [warn] {stem_dir.name} 下没有 wav")
        return False

    segments = []
    for wav in wav_files:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "stream=duration", "-of",
             "default=noprint_wrappers=1:nokey=1", str(wav)],
            capture_output=True, text=True)
        dur_str = r.stdout.strip()[:6]

        chunks = 1
        try:
            d = float(r.stdout.strip())
            chunks = max(1, math.ceil(d / CHUNK_SECONDS))
        except ValueError:
            pass

        print(f"  [run]  {wav.name} (~{dur_str}s, {chunks} 子块)", end="", flush=True)

        text = transcribe_seg(model, wav)
        segments.append({"seq": len(segments), "seg_name": wav.stem, "text": text})
        print(f" → {len(text)} 字")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump({
            "stem": stem_dir.name,
            "model": "SenseVoiceSmall",
            "chunk_seconds": CHUNK_SECONDS,
            "num_segments": len(segments),
            "segments": segments,
            "text_joined": "\n".join(s["text"] for s in segments),
        }, f, ensure_ascii=False, indent=2)

    total_chars = sum(len(s["text"]) for s in segments)
    print(f"  [done] → {out_path.name} ({len(segments)} 段, {total_chars} 字)")
    return True


def main() -> None:
    if not INPUT_DIR.exists():
        print(f"ERROR: {INPUT_DIR} 不存在", file=sys.stderr)
        sys.exit(1)

    stem_dirs = sorted([d for d in INPUT_DIR.iterdir() if d.is_dir()])
    if not stem_dirs:
        print(f"ERROR: {INPUT_DIR} 下没有子目录", file=sys.stderr)
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    model = build_model()
    print(f"[transcribe] 输入: {INPUT_DIR}")
    print(f"[transcribe] 输出: {OUTPUT_DIR}")
    print(f"[transcribe] 子块: {CHUNK_SECONDS}s/块, 缓存: {TMP_DIR}")
    print(f"[transcribe] 待处理: {len(stem_dirs)} 个 stem")
    print()

    try:
        for stem_dir in stem_dirs:
            out_path = OUTPUT_DIR / f"{stem_dir.name}.json"
            wav_files = sorted(stem_dir.glob("seg_*.wav"))
            print(f"[stem] {stem_dir.name} ({len(wav_files)} 段)")
            transcribe_stem(model, stem_dir, out_path)
            print()

        print("[transcribe] 全部完成。")
    finally:
        if TMP_DIR.exists():
            shutil.rmtree(TMP_DIR)


if __name__ == "__main__":
    main()

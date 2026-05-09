#!/usr/bin/env python3
"""阶段 3:批量调用 whisper-cli 转录,合并段。

输入:
    data/audio/{stem}/seg_NNN.wav

输出:
    data/transcripts/{stem}/seg_NNN.json   ← 单段原始转录(whisper-cli 直出)
    data/transcripts/{stem}.json           ← 合并后(段索引×段长 加偏移)

合并后 JSON 结构(下游清洗用):
    {
        "stem": "...",
        "duration_seconds": 7216.0,
        "segment_count": 5,
        "segments": [
            {"start": 0.0, "end": 3.5, "text": "..."},
            {"start": 3.8, "end": 7.2, "text": "..."}
        ]
    }

跳过策略:
    单段:目标 .json 已存在 → 跳过该段(支持断点续跑)
    合并:每次都重新合并(几秒钟,不影响)
"""

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "data" / "audio"
OUTPUT_DIR = PROJECT_ROOT / "data" / "transcripts"

WHISPER_CLI = "whisper-cli"
MODEL_PATH = Path.home() / "whisper.cpp" / "models" / "ggml-large-v3-turbo.bin"
LANGUAGE = "zh"
MAX_LEN = 50               # 单条 transcription 最大字符,避免巨长段
SEGMENT_DURATION = 1800    # 与 extract_audio 一致(30 分钟)
THREADS = 8                # M4 物理核


def transcribe_one_segment(wav_path: Path, out_dir: Path) -> Path:
    """转录单段 wav,产出 same_basename.json。返回 JSON 路径。

    whisper-cli 用 -of 指定输出基名(不带扩展名),-oj 写 .json
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    out_basename = out_dir / wav_path.stem
    out_json = out_dir / f"{wav_path.stem}.json"

    if out_json.exists() and out_json.stat().st_size > 0:
        print(f"  [skip] {wav_path.name} → {out_json.name}")
        return out_json

    cmd = [
        WHISPER_CLI,
        "-m", str(MODEL_PATH),
        "-l", LANGUAGE,
        "-t", str(THREADS),
        "-ml", str(MAX_LEN),
        "-oj",
        "-of", str(out_basename),
        "-np",
        "-f", str(wav_path),
    ]

    print(f"  [run]  {wav_path.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: whisper-cli 返回码 {result.returncode}", file=sys.stderr)
        print("--- stderr (尾部 2000 字符) ---", file=sys.stderr)
        print(result.stderr[-2000:], file=sys.stderr)
        sys.exit(1)

    if not out_json.exists():
        print(f"ERROR: 期望的 {out_json} 没生成", file=sys.stderr)
        print("--- stderr (尾部 2000 字符) ---", file=sys.stderr)
        print(result.stderr[-2000:], file=sys.stderr)
        sys.exit(1)

    size_kb = out_json.stat().st_size / 1024
    print(f"         → {out_json.name} ({size_kb:.1f} KB)")
    return out_json


def merge_segments(stem_dir: Path) -> dict:
    """合并子目录下所有 seg_NNN.json,加时间戳偏移。

    whisper.cpp JSON 结构(实测前预设):
        {"transcription": [
            {"timestamps": {"from": "00:00:00,000", "to": "00:00:03,500"},
             "offsets": {"from": 0, "to": 3500},
             "text": "..."},
            ...
        ]}
    offsets 单位是毫秒。
    """
    seg_jsons = sorted(stem_dir.glob("seg_*.json"))
    if not seg_jsons:
        return {}

    merged_segments = []
    last_end = 0.0

    for idx, seg_json in enumerate(seg_jsons):
        offset = idx * SEGMENT_DURATION
        with seg_json.open("r", encoding="utf-8") as f:
            data = json.load(f)

        entries = data.get("transcription", [])
        for entry in entries:
            offsets = entry.get("offsets", {})
            start_ms = offsets.get("from", 0)
            end_ms = offsets.get("to", 0)
            text = entry.get("text", "").strip()
            if not text:
                continue
            start_s = start_ms / 1000.0 + offset
            end_s = end_ms / 1000.0 + offset
            merged_segments.append(
                {"start": round(start_s, 3), "end": round(end_s, 3), "text": text}
            )
            last_end = end_s

    return {
        "stem": stem_dir.name,
        "duration_seconds": round(last_end, 2),
        "segment_count": len(seg_jsons),
        "segments": merged_segments,
    }


def main() -> None:
    if not INPUT_DIR.exists():
        print(f"ERROR: {INPUT_DIR} 不存在,先跑 extract_audio.py", file=sys.stderr)
        sys.exit(1)

    if not MODEL_PATH.exists():
        print(f"ERROR: 模型不存在: {MODEL_PATH}", file=sys.stderr)
        sys.exit(1)

    stem_dirs = sorted([d for d in INPUT_DIR.iterdir() if d.is_dir()])
    if not stem_dirs:
        print(f"ERROR: {INPUT_DIR} 下没有子目录", file=sys.stderr)
        sys.exit(1)

    print(f"[transcribe] 输入: {INPUT_DIR}")
    print(f"[transcribe] 输出: {OUTPUT_DIR}")
    print(f"[transcribe] 模型: {MODEL_PATH.name}")
    print(f"[transcribe] 子目录: {len(stem_dirs)}")
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for stem_dir in stem_dirs:
        wav_files = sorted(stem_dir.glob("seg_*.wav"))
        if not wav_files:
            print(f"[warn] {stem_dir.name} 下没有 wav,跳过")
            continue

        out_dir = OUTPUT_DIR / stem_dir.name
        print(f"[stem] {stem_dir.name} ({len(wav_files)} 段)")

        for wav in wav_files:
            transcribe_one_segment(wav, out_dir)

        merged = merge_segments(out_dir)
        if merged:
            merged_path = OUTPUT_DIR / f"{stem_dir.name}.json"
            with merged_path.open("w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            print(
                f"  [merge] → {merged_path.name} "
                f"({merged['duration_seconds']:.0f}s, {len(merged['segments'])} 句)"
            )
        print()

    print("[transcribe] 全部完成。")


if __name__ == "__main__":
    main()

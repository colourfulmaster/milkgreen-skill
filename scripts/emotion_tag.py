#!/usr/bin/env python3
"""SenseVoice 情绪分析 — 对齐 B站 AI 字幕时间轴。

流程:
    1. 读取 B站 AI 字幕 JSON (已有 start/end/text)
    2. 对每段语音区间切音频片段 → 送 SenseVoice 分析情绪
    3. 将情绪标签追加到原字幕 JSON 的 tags 字段中

用法:
    python3 scripts/emotion_tag.py --bvid BV1KDRnB3EQE   # 单文件
    python3 scripts/emotion_tag.py --all-live             # 全部11场直播回放
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from funasr import AutoModel

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = PROJECT_ROOT / "data" / "cleaned"
MEDIA_DIR = PROJECT_ROOT / "data" / "raw_media"
TMP_DIR = PROJECT_ROOT / ".tmp_emotion"  # 默认,可被 --worker-id 覆盖

# SenseVoice 情绪 token 映射
EMOTION_MAP = {
    "HAPPY": "开心/兴奋",
    "SAD": "悲伤/低落",
    "ANGRY": "愤怒/激动",
    "NEUTRAL": "中性/平静",
    "BGM": "背景音乐",
    "SING": "唱歌",
    "LAUGH": "笑",
    "CRY": "哭/哽咽",
    "EMO_UNK": "其他情绪",
}

EMOTION_TOKEN_RE = re.compile(r"<\|([^|]+)\|>")

# 非情绪 token(语言/文本归一化标记)
NON_EMOTION_TOKENS = {"zh", "en", "ja", "woitn", "itn", "BGM", "SING"}


def extract_emotion_tags(text: str) -> tuple[str, list[str]]:
    """从 SenseVoice 输出中提取情绪 token 和纯文本。"""
    tokens = EMOTION_TOKEN_RE.findall(text)
    emotions = []
    for t in tokens:
        if t not in NON_EMOTION_TOKENS:
            label = EMOTION_MAP.get(t, t)
            if label not in emotions:
                emotions.append(label)
    clean = EMOTION_TOKEN_RE.sub("", text).strip()
    return clean, emotions


def split_audio_for_segments(audio_path: Path, segments: list, batch_size: int = 10) -> list:
    """将长音频按 segments 时间区间切成小片段。

    返回 [(seg_idx, wav_path), ...]
    每批 batch_size 个 segment 合并成一个大段(避免 ffmpeg 调用过多),
    然后用 VAD 精确定位情绪。

    策略: 不需要逐 segment 切。SenseVoice 自带 VAD,
    直接对整段音频做 VAD+情绪, 然后用时间对齐。
    """
    # 直接用整段音频, SenseVoice VAD 自己切
    pass  # SenseVoice 内部 VAD 处理,不需要我们手动切


def load_model():
    """加载 SenseVoiceSmall 模型(VAD 模式, 带时间戳)。"""
    print("[model] 加载 SenseVoiceSmall...", flush=True)
    model = AutoModel(
        model="iic/SenseVoiceSmall",
        device="cpu",  # M4 CPU 够快
        disable_update=True,
    )
    return model


def batch_process_audio(model, wav_paths: list) -> list:
    """批量处理 WAV 音频, 返回对应位置的 emotions 列表(等长于 wav_paths)。"""
    results = []
    for i, wav_path in enumerate(wav_paths):
        if wav_path is None or not wav_path.exists():
            results.append([])
            continue
        if wav_path.stat().st_size <= 1000:
            results.append([])
            continue
        try:
            result = model.generate(
                input=str(wav_path),
                language="zh",
                text_norm="woitn",
                ban_emo_unk=False,
            )
            if result and len(result) > 0:
                raw = result[0].get("text", "")
                _, emotions = extract_emotion_tags(raw)
                results.append(emotions)
            else:
                results.append([])
        except Exception:
            results.append([])
    # 确保和输入等长
    while len(results) < len(wav_paths):
        results.append([])
    return results


def align_emotions_to_segments(audio_path: str, segments: list, model) -> list:
    """批量: 先切全部音频片段 → 批量送 SenseVoice → 贴情绪回 segments。"""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    total = len(segments)

    # Step 1: 批量切音频
    print(f"  切音频: {total} 段...", flush=True)
    clip_paths = []
    valid_seg_indices = []

    for i, seg in enumerate(segments):
        start = seg.get("start", 0)
        end = seg.get("end", 0)
        dur = end - start

        if dur < 0.5 or dur > 30:
            clip_paths.append(None)
            continue

        clip_path = TMP_DIR / f"seg_{i:06d}.wav"
        try:
            subprocess.run([
                "ffmpeg", "-y",
                "-ss", str(start),
                "-t", str(dur + 0.5),
                "-i", audio_path,
                "-ar", "16000",
                "-ac", "1",
                "-c:a", "pcm_s16le",
                "-loglevel", "error",
                str(clip_path),
            ], capture_output=True, timeout=5)
            if clip_path.exists() and clip_path.stat().st_size > 1000:
                clip_paths.append(clip_path)
                valid_seg_indices.append(i)
            else:
                clip_paths.append(None)
        except Exception:
            clip_paths.append(None)

    n_valid = len(valid_seg_indices)
    print(f"  有效音频: {n_valid}/{total} 段", flush=True)

    # Step 2: 批量推理(返回与 clip_paths 等长列表)
    print(f"  SenseVoice 推理中...", flush=True)
    emotions_list = batch_process_audio(model, clip_paths)

    # Step 3: 贴情绪
    for i, emotions in enumerate(emotions_list):
        if emotions:  # 只贴非空
            segments[i]["emotion"] = emotions

    # 清理
    for p in clip_paths:
        if p and p.exists():
            p.unlink()

    return segments


def process_bvid(bvid: str, model, is_clip: bool = False) -> bool:
    """处理单个 BV: 找音频 → 找字幕 → 情绪对齐 → 保存。"""
    # 找所有音频文件(多 P 时每个 P 一个文件)
    if is_clip:
        audio_files = [MEDIA_DIR / "clips" / f"{bvid}.m4a"]
        audio_files = [f for f in audio_files if f.exists()]
    else:
        audio_files = sorted([
            f for f in MEDIA_DIR.glob(f"*{bvid}*.m4a")
            if f.suffix in (".m4a", ".mp3", ".aac", ".wav")
        ])
    if not audio_files:
        print(f"  [warn] 未找到 {bvid} 的音频,跳过", flush=True)
        return False

    # 找字幕文件
    prefix = "clip_" if is_clip else ""
    transcript_path = TRANSCRIPTS_DIR / f"{prefix}{bvid}.json"
    if not transcript_path.exists():
        print(f"  [warn] 未找到 {bvid} 的字幕", flush=True)
        return False

    with transcript_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    segments = data.get("segments", [])
    if not segments:
        print(f"  [warn] 无 segments", flush=True)
        return False

    print(f"  [{bvid}] 音频={len(audio_files)}P, 字幕={len(segments)}段", flush=True)

    # 按 part 分组 segments, 对应到各 P 的音频
    # segments 可能带 part 字段(多P) 或 无 part(单P)
    has_parts = any("part" in s for s in segments)

    if has_parts and len(audio_files) > 1:
        # 多 P: 按 part 字段分组, 分别用对应音频处理
        part_groups = {}
        for s in segments:
            pn = s.get("part", 0)
            part_groups.setdefault(pn, []).append(s)

        all_enriched = []
        total_emo = {}
        for pn in sorted(part_groups.keys()):
            if pn >= len(audio_files):
                print(f"    P{pn}: 无对应音频,跳过", flush=True)
                all_enriched.extend(part_groups[pn])
                continue
            audio_path = str(audio_files[pn])
            segs = part_groups[pn]
            print(f"    P{pn}: {len(segs)}段 → {audio_files[pn].name}", flush=True)
            enriched = align_emotions_to_segments(audio_path, segs, model)
            for s in enriched:
                for e in s.get("emotion", []):
                    total_emo[e] = total_emo.get(e, 0) + 1
            all_enriched.extend(enriched)
    else:
        # 单 P: 直接用第一个音频
        audio_path = str(audio_files[0])
        print(f"  音频: {audio_files[0].name}", flush=True)
        all_enriched = align_emotions_to_segments(audio_path, segments, model)
        total_emo = {}
        for s in all_enriched:
            for e in s.get("emotion", []):
                total_emo[e] = total_emo.get(e, 0) + 1

    print(f"  情绪分布: {dict(sorted(total_emo.items(), key=lambda x:-x[1]))}", flush=True)

    data["segments"] = all_enriched
    data["emotion_stats"] = total_emo
    with transcript_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"  ✅ 已保存", flush=True)
    return True


def main():
    global TMP_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument("--bvid", help="处理单个 BV")
    parser.add_argument("--bvids", nargs="*", help="处理多个 BV(用于多 worker)")
    parser.add_argument("--all-live", action="store_true", help="处理全部11场直播回放")
    parser.add_argument("--worker-id", type=int, default=0, help="Worker ID,0=单进程模式")
    parser.add_argument("--clips", action="store_true", help="处理切片(clip_*.json)")
    args = parser.parse_args()

    if args.worker_id > 0:
        TMP_DIR = PROJECT_ROOT / f".tmp_emotion_w{args.worker_id}"
        print(f"[worker-{args.worker_id}] 临时目录: {TMP_DIR}", flush=True)

    if args.bvids:
        bvids = args.bvids
    elif args.bvid:
        bvids = [args.bvid]
    elif args.all_live:
        bvids = sorted([
            f.stem for f in TRANSCRIPTS_DIR.glob("BV*.json")
            if not f.name.startswith("clip_")
        ])
        print(f"[emotion] 共 {len(bvids)} 个直播回放", flush=True)
    else:
        print("需要 --bvid / --bvids / --all-live", file=sys.stderr)
        sys.exit(1)

    model = load_model()

    try:
        for bvid in bvids:
            process_bvid(bvid, model, is_clip=args.clips)
    finally:
        if TMP_DIR.exists():
            import shutil
            shutil.rmtree(TMP_DIR)

    print(f"[worker-{args.worker_id}] 完成", flush=True)


if __name__ == "__main__":
    main()

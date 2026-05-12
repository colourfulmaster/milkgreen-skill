#!/usr/bin/env python3
"""对比 Paraformer-large vs SenseVoiceSmall 1 段输出质量。验证完可删。"""
import json, re, subprocess, sys
from pathlib import Path
from funasr import AutoModel

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WAV = PROJECT_ROOT / "data" / "audio" / "clip_1P_0-99m" / "seg_000.wav"

SENSE_TOKEN_RE = re.compile(r"<\|[^|]+\|>")

print("=" * 60)
print("1. SenseVoiceSmall + ban_emo_unk=True")
print("=" * 60)
m1 = AutoModel(model="iic/SenseVoiceSmall", device="cpu", disable_update=True)
r1 = m1.generate(input=str(WAV), language="zh", text_norm="woitn", ban_emo_unk=True)
raw1 = r1[0].get("text", "")
clean1 = SENSE_TOKEN_RE.sub("", raw1).strip()
print(f"  字数: {len(clean1)}")
print(f"  前 200 字: {clean1[:200]}")
print()

print("=" * 60)
print("2. Paraformer-large (beam=10, ctc=0.5, VAD, timestamp)")
print("=" * 60)
m2 = AutoModel(
    model="iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    device="cpu",
    disable_update=True,
    beam_size=10,
    decoding_ctc_weight=0.5,
    pred_timestamp=True,
    vad_filter=True,
)
r2 = m2.generate(
    input=str(WAV),
    batch_size_s=60,
)
if isinstance(r2, list) and len(r2) > 0 and isinstance(r2[0], dict):
    d2 = r2[0]
    texts = []
    if "text" in d2:
        texts.append(d2["text"])
    if "sentences" in d2 and d2["sentences"]:
        texts = [s["text"] for s in d2["sentences"]]
    clean2 = " ".join(texts)
else:
    clean2 = str(r2)
print(f"  字数: {len(clean2)}")
print(f"  前 250 字: {clean2[:250]}")
print()

print("=" * 60)
print("对比摘要")
print("=" * 60)
print(f"  SenseVoice: {len(clean1)} 字")
print(f"  Paraformer: {len(clean2)} 字")

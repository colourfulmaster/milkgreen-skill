#!/usr/bin/env python3
"""情绪感知版文本清洗。

与 clean_text.py 的区别:
    - 相邻段情绪相同才合并碎片
    - 带愤怒/开心/笑声等情绪的短叹词保留(是风格信号)
    - 无情绪的纯噪音才过滤
    - 情绪突变的段之间不合并(保留情绪边界)

用法:
    python3 scripts/clean_emotion.py --bvid BV1KDRnB3EQE
"""

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "data" / "cleaned"
OUTPUT_DIR = PROJECT_ROOT / "data" / "cleaned_emo"

MIN_SEG_DURATION = 2.0
MIN_SEG_CHARS = 5
DEDUP_THRESHOLD = 0.85

# 情绪感知:以下情绪标签的短回应保留
SIGNIFICANT_EMOTIONS = {
    "开心/兴奋", "愤怒/激动", "悲伤/低落",
    "SURPRISED", "Laughter", "Cry",
    "DISGUSTED", "Sing",
}

# 非情绪标签(过滤)
NON_EMOTION_TAGS = {"Speech", "EMO_UNKNOWN", "Cough"}

# 风格语气词(即使无情绪也保留)
STYLE_WORDS = {"嗯", "啊", "哦", "呃", "嘛", "呀", "吧", "哈",
               "哎呀", "哎哟", "我去", "绝了", "牛的", "好家伙",
               "对对对", "好好好", "行吧", "是的", "没错",
               "卧槽", "我靠", "妈呀", "天哪", "草",
               "难绷", "绷不住了", "下头", "逆天"}

NOISE_PATTERNS = [
    re.compile(r"^[啊哎诶哦噢嗯唔]{4,}$"),
    re.compile(r"^[.。,，!！?？;；\s]+$"),
]


def clean_emotions(emotions: list) -> list:
    """过滤掉非情绪标签。"""
    return [e for e in emotions if e not in NON_EMOTION_TAGS]


def has_significant_emotion(emotions: list) -> bool:
    """是否有值得保留的情绪标签。"""
    return bool(set(emotions) & SIGNIFICANT_EMOTIONS)


def is_noise(text: str, emotions: list) -> bool:
    """判断是否为噪音(情绪感知版)。"""
    t = text.strip()
    if not t:
        return True
    for pat in NOISE_PATTERNS:
        if pat.match(t):
            return True
    # 短文本:有情绪就不删,没情绪且在风格词表外才删
    if len(t) <= 2:
        if t in STYLE_WORDS:
            return False
        if has_significant_emotion(emotions):
            return False
        return True
    return False


def is_fragment(seg: dict) -> bool:
    """判断是否为碎片。"""
    dur = seg.get("end", 0) - seg.get("start", 0)
    text_len = len(seg.get("text", ""))
    if dur < MIN_SEG_DURATION and text_len < MIN_SEG_CHARS:
        t = seg["text"].strip()
        if t in STYLE_WORDS:
            return False
        if has_significant_emotion(seg.get("emotion", [])):
            return False
        return True
    return False


def emotions_match(a: list, b: list) -> bool:
    """两个情绪列表是否有重叠。"""
    if not a or not b:
        return True  # 无情绪的不限制合并
    return bool(set(a) & set(b))


def merge_fragments(segments: list) -> list:
    """情绪感知合并:同情绪的碎片合并,情绪突变的保留边界。"""
    if len(segments) <= 1:
        return segments

    result = []
    i = 0
    while i < len(segments):
        seg = segments[i]
        if is_fragment(seg):
            # 优先往前合并(同情绪)
            if result and emotions_match(result[-1].get("emotion", []), seg.get("emotion", [])):
                prev = result[-1]
                prev["text"] = prev["text"] + " " + seg["text"]
                prev["end"] = seg["end"]
            elif i + 1 < len(segments) and emotions_match(segments[i + 1].get("emotion", []), seg.get("emotion", [])):
                nxt = segments[i + 1]
                nxt["text"] = seg["text"] + " " + nxt["text"]
                nxt["start"] = seg["start"]
            else:
                result.append(dict(seg))
        else:
            result.append(dict(seg))
        i += 1

    return result


def dedup_consecutive(segments: list) -> list:
    """情绪感知去重:情绪相同且文本重复才删。"""
    if len(segments) <= 1:
        return segments

    result = [segments[0]]
    for seg in segments[1:]:
        prev = result[-1]
        sim = SequenceMatcher(None, prev["text"], seg["text"]).ratio()
        same_emo = emotions_match(prev.get("emotion", []), seg.get("emotion", []))
        if sim > DEDUP_THRESHOLD and same_emo:
            if len(seg["text"]) > len(prev["text"]):
                result[-1] = dict(seg)
                result[-1]["start"] = prev["start"]
        else:
            result.append(dict(seg))
    return result


def clean_segments(segments: list) -> dict:
    """完整清洗流程。"""
    original_count = len(segments)

    # 先清理情绪标签
    for s in segments:
        s["emotion"] = clean_emotions(s.get("emotion", []))

    # 过滤纯噪音
    result = [s for s in segments if not is_noise(s["text"], s.get("emotion", []))]
    after_filter = len(result)

    # 合并碎片
    result = merge_fragments(result)
    after_merge = len(result)

    # 去重
    result = dedup_consecutive(result)
    after_dedup = len(result)

    # 文本规范化
    for s in result:
        s["text"] = re.sub(r"\s+", " ", s["text"].strip())

    return {
        "original": original_count,
        "after_filter": after_filter,
        "after_merge": after_merge,
        "after_dedup": after_dedup,
        "final": len(result),
        "segments": result,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bvid", required=True)
    args = parser.parse_args()

    input_path = INPUT_DIR / f"{args.bvid}.json"
    if not input_path.exists():
        print(f"ERROR: {input_path} 不存在", file=sys.stderr)
        sys.exit(1)

    with input_path.open() as f:
        data = json.load(f)

    segments = data.get("segments", [])
    print(f"清洗前: {len(segments)} 段\n")

    result = clean_segments(segments)

    # 对比输出
    print(f"{'阶段':<20} {'段数':>6} {'变化'}")
    print("-" * 35)
    print(f"{'原始':<20} {result['original']:>6}")
    print(f"{'过滤噪音':<20} {result['after_filter']:>6}  (-{result['original'] - result['after_filter']})")
    print(f"{'合并碎片':<20} {result['after_merge']:>6}  (-{result['after_filter'] - result['after_merge']})")
    print(f"{'去重':<20} {result['after_dedup']:>6}  (-{result['after_merge'] - result['after_dedup']})")
    print(f"{'最终':<20} {result['final']:>6}  (-{result['original'] - result['final']} / -{(1-result['final']/result['original'])*100:.0f}%)")

    # 情绪统计
    from collections import Counter
    emo_before = Counter()
    emo_after = Counter()
    for s in data["segments"]:
        for e in s.get("emotion", []):
            emo_before[e] += 1
    for s in result["segments"]:
        for e in s.get("emotion", []):
            emo_after[e] += 1

    print(f"\n情绪分布变化:")
    for emo, cnt_before in emo_before.most_common():
        cnt_after = emo_after.get(emo, 0)
        delta = cnt_after - cnt_before
        print(f"  {emo:<16} {cnt_before:>5} → {cnt_after:>5}  ({delta:+d})")

    # 保存
    out_path = OUTPUT_DIR / f"{args.bvid}_emo.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data["segments"] = result["segments"]
    data["cleaned_count"] = result["final"]
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n保存: {out_path}")

    # 抽样:展示情绪边界保留的例子
    print(f"\n情绪边界保留示例(相邻段情绪不同未被合并):")
    segs = result["segments"]
    shown = 0
    for i in range(1, min(len(segs) - 1, 500)):
        prev_emo = set(segs[i-1].get("emotion", []))
        curr_emo = set(segs[i].get("emotion", []))
        if prev_emo and curr_emo and not (prev_emo & curr_emo):
            print(f"  [{segs[i-1]['start']:.0f}s] {prev_emo} 『{segs[i-1]['text'][:50]}』")
            print(f"  [{segs[i]['start']:.0f}s] {curr_emo} 『{segs[i]['text'][:50]}』")
            print()
            shown += 1
            if shown >= 5:
                break


if __name__ == "__main__":
    main()

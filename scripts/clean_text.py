#!/usr/bin/env python3
"""Stage 3: 文本清洗。

对 ASR 转录文本做:
    1. 合并碎片 — 过短片段(<2s 且 <5字)合并到相邻句
    2. 去重 — 连续高度相似(>85%)的句子去重
    3. 过滤纯噪音 — 去除无意义声响,但保留风格语气词
    4. 基础规范化 — 去除多余空格/换行

输出: data/cleaned/{stem}.json, 保持与 transcripts 相同的结构

用法:
    python3 scripts/clean_text.py                    # 处理全部
    python3 scripts/clean_text.py --bvid BV1xxx      # 单文件
    python3 scripts/clean_text.py --dry-run           # 统计不写入
"""

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "data" / "transcripts"
OUTPUT_DIR = PROJECT_ROOT / "data" / "cleaned"


# ── 输入白名单 ──────────────────────────────────────
# 防止开发期测试残留(如 bili_ai_P*.json)混入正式数据。
# 只接受符合奶绿数据命名规范的 stem。

def is_target_stem(stem: str) -> bool:
    """判断 stem 是否为奶绿真实数据。匹配以下三类命名:
    - 切片视频 BVID:BV16BiiBfE8P / BV16BiiBfE8P_P1
    - import_clips.py 输出:clip_BV*
    - 直播回放 yt-dlp 命名:含 `_BiliBili_` 或前缀 `NA_BiliBili_`
    其他(如 bili_ai_*、临时测试文件)一律拒绝。
    """
    if stem.startswith("BV") or stem.startswith("clip_BV"):
        return True
    if "_BiliBili_" in stem:
        return True
    return False

# ── 配置 ───────────────────────────────────────────

MIN_SEG_DURATION = 2.0   # 低于此秒数视为碎片
MIN_SEG_CHARS = 5        # 低于此字数视为碎片
DEDUP_THRESHOLD = 0.85   # 相似度 > 此值视为重复

# SC 相关标记(直播中主播念 SuperChat 时的缩略语,保留)
SC_MARKERS = {"nc", "ac", "sc", "SC", "Sc", "n c", "a c"}

# 有风格价值的语气词/短回应(保留,不视为噪音)
STYLE_INTERJECTIONS = {
    "嗯", "啊", "哦", "呃", "嘛", "呀", "吧", "哈",
    "哎呀", "哎哟", "我去", "绝了", "绝绝子", "牛", "牛逼",
    "对对对", "好好好", "行吧", "是的", "对的", "没错",
    "哈哈哈", "嘿嘿", "嘻嘻", "呵呵",
    "卧槽", "我靠", "妈呀", "天哪",
    "懂的", "懂我意思吧", "你懂吧",
    "好家伙", "真行", "牛的",
    "难绷", "绷不住了", "没绷住",
    "下头", "逆天", "抽象",
}

# 纯噪音模式(正则,匹配则删除)
NOISE_PATTERNS = [
    re.compile(r"^[啊哎诶哦噢嗯唔]{4,}$"),      # 连续 4+ 个叹词,无实义
    re.compile(r"^[.。,，!！?？;；\s]+$"),        # 纯标点
    re.compile(r"^[\d\s\.\,]+$"),                  # 纯数字
]


# ── 清洗逻辑 ───────────────────────────────────────

def is_noise(text: str) -> bool:
    """判断是否为纯噪音。"""
    t = text.strip()
    if not t:
        return True
    for pat in NOISE_PATTERNS:
        if pat.match(t):
            return True
    # 极短但可能是 SC 标记或风格词
    if len(t) <= 2 and t.lower() not in SC_MARKERS and t not in STYLE_INTERJECTIONS:
        return True
    return False


def is_fragment(seg: dict) -> bool:
    """判断是否为碎片(过短且不成句)。"""
    dur = seg.get("end", 0) - seg.get("start", 0)
    text_len = len(seg.get("text", ""))
    # 时长 < 2s 且字数 < 5 且不在风格词表中
    if dur < MIN_SEG_DURATION and text_len < MIN_SEG_CHARS:
        t = seg["text"].strip()
        if t.lower() not in SC_MARKERS and t not in STYLE_INTERJECTIONS:
            return True
    return False


def text_similarity(a: str, b: str) -> float:
    """计算两段文本的相似度。"""
    return SequenceMatcher(None, a, b).ratio()


def merge_fragments(segments: list) -> list:
    """将碎片合并到相邻句(优先前句)。"""
    if len(segments) <= 1:
        return segments

    result = []
    i = 0
    while i < len(segments):
        seg = segments[i]
        if is_fragment(seg):
            # 尝试合并到前一句
            if result:
                prev = result[-1]
                prev["text"] = prev["text"] + " " + seg["text"]
                prev["end"] = seg["end"]
            # 如果前面没有(第一条就是碎片),尝试往后合并
            elif i + 1 < len(segments):
                nxt = segments[i + 1]
                nxt["text"] = seg["text"] + " " + nxt["text"]
                nxt["start"] = seg["start"]
        else:
            result.append(dict(seg))
        i += 1

    return result


def dedup_consecutive(segments: list) -> list:
    """去除连续重复的句子。"""
    if len(segments) <= 1:
        return segments

    result = [segments[0]]
    for seg in segments[1:]:
        prev = result[-1]
        sim = text_similarity(prev["text"], seg["text"])
        if sim > DEDUP_THRESHOLD:
            # 保留更长的版本
            if len(seg["text"]) > len(prev["text"]):
                result[-1] = dict(seg)
                result[-1]["start"] = prev["start"]  # 保持原 start
        else:
            result.append(dict(seg))
    return result


def filter_noise(segments: list) -> list:
    """过滤纯噪音,保留风格语气词。"""
    return [s for s in segments if not is_noise(s["text"])]


def normalize_text(text: str) -> str:
    """基础文本规范化。"""
    t = text.strip()
    t = re.sub(r"\s+", " ", t)  # 合并空格
    return t


def clean_segments(segments: list) -> dict:
    """对一组 segments 执行完整清洗流程。返回清洗后的 segments + 统计。"""
    original_count = len(segments)
    original_chars = sum(len(s["text"]) for s in segments)

    result = segments
    result = filter_noise(result)
    after_filter = len(result)

    result = merge_fragments(result)
    after_merge = len(result)

    result = dedup_consecutive(result)
    after_dedup = len(result)

    # 规范化
    for s in result:
        s["text"] = normalize_text(s["text"])

    # 再过滤一轮(合并后可能出现新的噪音组合)
    result = [s for s in result if not is_noise(s["text"])]

    final_count = len(result)
    final_chars = sum(len(s["text"]) for s in result)

    return result, {
        "original": original_count,
        "after_filter": after_filter,
        "after_merge": after_merge,
        "after_dedup": after_dedup,
        "final": final_count,
        "chars_in": original_chars,
        "chars_out": final_chars,
    }


# ── 文件处理 ───────────────────────────────────────

def process_file(input_path: Path, output_path: Path, dry_run: bool = False) -> dict:
    """处理单个 JSON 文件。返回统计信息。"""
    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # segments 可能在顶层或嵌套在 parts 中
    if "segments" in data:
        segments = data["segments"]
    else:
        # 兼容 clip_ 格式
        segments = data.get("segments", [])

    if not segments:
        return {"file": input_path.name, "error": "no segments"}

    cleaned, stats = clean_segments(segments)

    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out = {
            "bvid": data.get("bvid", ""),
            "title": data.get("title", ""),
            "notes": data.get("notes", ""),
            "source": input_path.stem,
            "original_count": stats["original"],
            "cleaned_count": stats["final"],
            "segments": cleaned,
        }
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

    stats["file"] = input_path.stem
    return stats


# ── CLI ────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Stage 3: 文本清洗")
    parser.add_argument("--bvid", help="只处理指定 BV")
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写入")
    parser.add_argument("--limit", type=int, help="限制处理数量(测试用)")
    args = parser.parse_args()

    INPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 收集文件(过滤非奶绿数据)
    all_json = sorted(INPUT_DIR.glob("*.json"))
    json_files = [f for f in all_json if is_target_stem(f.stem)]
    skipped = [f.stem for f in all_json if not is_target_stem(f.stem)]
    if skipped:
        print(f"[clean] 已过滤 {len(skipped)} 个非奶绿命名文件: {skipped[:5]}{'...' if len(skipped) > 5 else ''}",
              flush=True)
    if args.bvid:
        json_files = [INPUT_DIR / f"{args.bvid}.json"]
        if not json_files[0].exists():
            json_files = [INPUT_DIR / f"clip_{args.bvid}.json"]
            if not json_files[0].exists():
                print(f"ERROR: 找不到 {args.bvid}", file=sys.stderr)
                sys.exit(1)

    if args.limit:
        json_files = json_files[: args.limit]

    print(f"[clean] {len(json_files)} 个文件待处理", flush=True)

    total_in = 0
    total_out = 0
    errors = 0

    for i, f in enumerate(json_files):
        out_path = OUTPUT_DIR / f.name

        if out_path.exists() and not args.dry_run:
            print(f"  [{i+1}/{len(json_files)}] {f.stem} — 已清洗,跳过")
            continue

        stats = process_file(f, out_path, args.dry_run)
        if "error" in stats:
            print(f"  [{i+1}/{len(json_files)}] {f.stem} — {stats['error']}")
            errors += 1
            continue

        reduction = (1 - stats["final"] / stats["original"]) * 100 if stats["original"] else 0
        print(f"  [{i+1}/{len(json_files)}] {f.stem}: "
              f"{stats['original']}→{stats['final']}条 "
              f"(-{reduction:.0f}%) "
              f"{stats['chars_in']}→{stats['chars_out']}字")

        total_in += stats["original"]
        total_out += stats["final"]

    print(f"\n[clean] 完成: {total_in}→{total_out} 条 "
          f"(-{(1-total_out/total_in)*100:.0f}%)" if total_in else "",
          flush=True)
    if errors:
        print(f"[clean] {errors} 个文件出错", flush=True)
    if not args.dry_run:
        print(f"[clean] 输出: {OUTPUT_DIR}", flush=True)


if __name__ == "__main__":
    main()

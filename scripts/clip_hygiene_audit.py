#!/usr/bin/env python3
"""切片卫生自查：检测 cleaned/clip_BV*.json 中的混剪/错关联污染。

阶段 1：客观指标粗筛（无 LLM，分钟级）
阶段 2：LLM 精核（只跑可疑的）

用法：
    python3 scripts/clip_hygiene_audit.py --stage 1
    python3 scripts/clip_hygiene_audit.py --stage 2
"""

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLEANED_DIR = PROJECT_ROOT / "data" / "cleaned"
OUTPUT_PATH = PROJECT_ROOT / "data" / "analysis" / "clip_hygiene_audit.json"

# 口癖词表
KOUHUA_PATTERNS = re.compile(r"嗯|啊|就是|对吧|你知道吗|哈哈|哎|对对对|行了|神经|我不懂|动动你的|不哈哈哈|你呀|好了好了|这样吧|拉倒|随你|爱咋咋|怎么说呢|本质上|说白了|我跟你说")

# L1 触发关键词（这些词在切片标题中出现说明不是混剪，是奶绿内容）
MILKGREEN_TITLE_WORDS = {"奶绿", "明前", "奶姐", "奶比", "奶妈", "阿绿", "文静", "lulu", "Lulu", "LULU", "坚果", "JJ", "林俊杰", "江南", "Laplace", "B站", "直播", "主播", "SC", "投稿", "下头", "抽象", "逆天", "难绷", "奶糖花", "NT花"}


def jieba_cut(text: str) -> set:
    """简易分词（不用 jieba 依赖，用字符级 bigram + 关键词）。"""
    words = set()
    # 提取中文字符序列
    chinese = re.findall(r"[一-鿿]+", text)
    for seg in chinese:
        if len(seg) >= 2:
            for i in range(len(seg) - 1):
                words.add(seg[i:i+2])
        if len(seg) == 1:
            words.add(seg)
    # 提取英文词
    eng = re.findall(r"[a-zA-Z]+", text)
    words.update(w.lower() for w in eng if len(w) >= 3)
    return words


def compute_flags(clip_path: Path) -> dict:
    """对单个切片计算 5 项客观指标。"""
    with clip_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    segments = data.get("segments", [])
    title = data.get("title", "")
    duration = data.get("duration_seconds", 0) or data.get("duration", 0) or sum(s.get("end", 0) - s.get("start", 0) for s in segments)
    notes = data.get("notes", "")

    n = len(segments)
    flags = []
    metrics = {}

    # 1. 段数密度
    if duration > 0:
        density = n / duration
        metrics["density"] = round(density, 3)
        if density > 3:
            flags.append("high_density")
    else:
        metrics["density"] = 0
        flags.append("no_duration")

    # 2. 口癖密度
    kouhua_hits = sum(1 for s in segments if KOUHUA_PATTERNS.search(s.get("text", "")))
    metrics["kouhua_ratio"] = round(kouhua_hits / n, 3) if n else 0
    if metrics["kouhua_ratio"] < 0.10 and n >= 10:
        flags.append("low_kouhua")

    # 3. EMO_UNKNOWN 比例
    unknown_count = sum(1 for s in segments if "EMO_UNKNOWN" in s.get("emotion", []))
    metrics["unknown_ratio"] = round(unknown_count / n, 3) if n else 0
    if metrics["unknown_ratio"] > 0.5 and n >= 10:
        flags.append("high_unknown")

    # 4. 段数过少
    if n < 5:
        flags.append("too_short")

    # 5. 标题-内容词重叠
    title_words = jieba_cut(title)
    # 取前 20 段内容词
    content_text = " ".join(s.get("text", "") for s in segments[:20])
    content_words = jieba_cut(content_text)
    overlap = title_words & content_words
    metrics["title_content_overlap"] = len(overlap)
    # 检查奶绿关键词
    has_milkgreen_kw = bool(title_words & MILKGREEN_TITLE_WORDS or jieba_cut(notes[:200]) & MILKGREEN_TITLE_WORDS)
    if metrics["title_content_overlap"] == 0 and not has_milkgreen_kw and n >= 10:
        flags.append("title_mismatch")

    return {
        "bvid": clip_path.stem,
        "title": title[:100],
        "segments": n,
        "duration": round(duration, 1),
        "flags": flags,
        "metrics": metrics,
        "suspicious": len(flags) >= 2,
    }


def run_stage1() -> list:
    """阶段 1：全量客观指标粗筛。"""
    clip_files = sorted(CLEANED_DIR.glob("clip_*.json"))
    print(f"[Stage 1] 扫描 {len(clip_files)} 个切片...", flush=True)

    results = []
    flag_counter = Counter()

    for i, f in enumerate(clip_files):
        r = compute_flags(f)
        results.append(r)
        for flag in r["flags"]:
            flag_counter[flag] += 1
        if (i + 1) % 200 == 0:
            print(f"  [{i+1}/{len(clip_files)}] 已扫描", flush=True)

    suspicious = [r for r in results if r["suspicious"]]
    print(f"\n[Stage 1] 完成: {len(clip_files)} 切片")
    print(f"  可疑 (≥2 flags): {len(suspicious)}")
    print(f"  Flag 分布: {flag_counter.most_common()}")

    # 保存
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump({
            "stage": 1,
            "total": len(clip_files),
            "suspicious_count": len(suspicious),
            "flag_distribution": dict(flag_counter.most_common()),
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"  保存: {OUTPUT_PATH}")
    return results


def build_llm_prompt(r: dict) -> tuple:
    """为可疑切片构建 LLM 判断 prompt。"""
    clip_path = CLEANED_DIR / f"{r['bvid']}.json"
    with clip_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    segments = data.get("segments", [])
    first_30 = segments[:30]
    text_lines = []
    for s in first_30:
        text_lines.append(f"[{s['start']:.0f}s] {s.get('text', '')}")
    preview = "\n".join(text_lines)

    system = """判断这段字幕与标题描述的主题是否一致。
1 = 完全一致（标题正确描述内容）
2 = 部分一致（夹了别的内容但奶绿主体仍在）
3 = 完全不一致（混剪/错关联，无奶绿内容）

输出 JSON: {"verdict": 1|2|3, "reason": "简短原因"}"""

    user = f"标题: {r['title']}\n\n前 30 段字幕:\n{preview[:3000]}"
    return system, user


def run_stage2(dry_run: bool = False):
    """阶段 2：对可疑切片用 LLM 精核。"""
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(PROJECT_ROOT / ".env")

    if not OUTPUT_PATH.exists():
        print("ERROR: 请先跑 --stage 1", file=sys.stderr)
        sys.exit(1)

    audit = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    results = audit["results"]
    suspicious = [r for r in results if r["suspicious"]]
    print(f"[Stage 2] 精核 {len(suspicious)} 个可疑切片...", flush=True)

    if dry_run:
        print("  DRY RUN — 仅打印 prompt", flush=True)
        for r in suspicious[:3]:
            system, user = build_llm_prompt(r)
            print(f"\n  {r['bvid']}: {r['title'][:60]}")
            print(f"  flags: {r['flags']}")
            print(f"  prompt: {len(system)+len(user)} chars")
        return

    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
    )
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    verdicts = Counter()
    for i, r in enumerate(suspicious):
        system, user = build_llm_prompt(r)
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=256,
                temperature=0.1,
            )
            raw = resp.choices[0].message.content.strip()
            # Parse JSON
            json_str = raw
            if json_str.startswith("```"):
                json_str = re.sub(r"^```\w*\n?", "", json_str)
                json_str = re.sub(r"\n```$", "", json_str)
            v = json.loads(json_str)
            r["verdict"] = v.get("verdict", 3)
            r["reason"] = v.get("reason", raw[:100])
        except Exception as e:
            r["verdict"] = 3
            r["reason"] = f"LLM error: {e}"
        verdicts[r["verdict"]] += 1

        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(suspicious)}] 已精核", flush=True)
        time.sleep(0.5)

    # Update results in audit
    for r in results:
        if not r["suspicious"]:
            r["verdict"] = 1  # assumed clean
            r["reason"] = "not suspicious (passed stage 1)"

    audit["stage"] = 2
    audit["verdict_summary"] = dict(verdicts.most_common())
    audit["verdict_summary"]["clean_implied"] = len(results) - len(suspicious)

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    clean = sum(1 for r in results if r.get("verdict") == 1)
    partial = sum(1 for r in results if r.get("verdict") == 2)
    dirty = sum(1 for r in results if r.get("verdict") == 3)
    print(f"\n[Stage 2] 完成:")
    print(f"  Clean (verdict=1): {clean} (含 {len(results)-len(suspicious)} 阶段1通过)")
    print(f"  Partial (verdict=2): {partial}")
    print(f"  Dirty (verdict=3): {dirty}")
    print(f"  保存: {OUTPUT_PATH}")


def generate_report():
    """生成 AUDIT_REPORT_CLIP_HYGIENE.md。"""
    if not OUTPUT_PATH.exists():
        print("ERROR: 请先跑 --stage 1", file=sys.stderr)
        sys.exit(1)

    audit = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    results = audit["results"]

    clean = [r for r in results if r.get("verdict") == 1]
    partial = [r for r in results if r.get("verdict") == 2]
    dirty = [r for r in results if r.get("verdict") == 3]
    unknown = [r for r in results if r.get("verdict") is None]

    lines = []
    lines.append("# 切片卫生自查报告\n")
    lines.append(f"**扫描时间**: 2026-05-16\n")
    lines.append(f"**总数**: {len(results)} 切片\n")
    lines.append(f"**阶段 1 可疑**: {audit.get('suspicious_count', 0)} 个 (≥2 flags)\n")
    lines.append(f"**阶段 2 LLM 精核**: {len(results)-len(unknown)} 个\n\n")

    lines.append("## 概览\n")
    lines.append(f"| Verdict | 数量 | 占比 |")
    lines.append(f"|---|---|---|")
    lines.append(f"| 1 完全一致 (Clean) | {len(clean)} | {len(clean)/len(results)*100:.1f}% |")
    lines.append(f"| 2 部分一致 (Partial) | {len(partial)} | {len(partial)/len(results)*100:.1f}% |")
    lines.append(f"| 3 完全不一致 (Dirty) | {len(dirty)} | {len(dirty)/len(results)*100:.1f}% |")
    if unknown:
        lines.append(f"| ? 未精核 | {len(unknown)} | {len(unknown)/len(results)*100:.1f}% |")
    lines.append("")

    if dirty:
        lines.append("## ⚠️ Verdict=3 完全不一致（需用户决定是否删除）\n")
        lines.append("| BV | 标题 | Flags | 原因 |")
        lines.append("|---|---|---|---|")
        for r in sorted(dirty, key=lambda x: x.get("bvid", "")):
            flags_str = ", ".join(r.get("flags", []))
            title = r.get("title", "")[:60]
            reason = r.get("reason", "")[:80]
            lines.append(f"| {r['bvid']} | {title} | {flags_str} | {reason} |")
        lines.append("")

    if dirty:
        lines.append("## 脏样本案例（前 5）\n")
        for r in dirty[:5]:
            lines.append(f"### {r['bvid']}: {r.get('title','')[:80]}")
            lines.append(f"Flags: {', '.join(r.get('flags',[]))}")
            lines.append(f"Reason: {r.get('reason','')}")
            # Show first few segments
            clip_path = CLEANED_DIR / f"{r['bvid']}.json"
            if clip_path.exists():
                d = json.loads(clip_path.read_text(encoding="utf-8"))
                segs = d.get("segments", [])[:5]
                for s in segs:
                    lines.append(f"  [{s['start']:.0f}s] {s.get('text','')[:80]}")
            lines.append("")

    if clean:
        lines.append("## 干净样本案例（前 5）\n")
        for r in sorted(clean, key=lambda x: len(x.get("flags", [])), reverse=True)[:5]:
            lines.append(f"- **{r['bvid']}**: {r.get('title','')[:80]}")
            lines.append(f"  Segments: {r.get('segments',0)}, Duration: {r.get('duration',0)}s, Flags: {r.get('flags',[])}")
        lines.append("")

    lines.append("## Flag 分布\n")
    for flag, count in audit.get("flag_distribution", {}).items():
        lines.append(f"- **{flag}**: {count} 个切片")

    report_path = PROJECT_ROOT / "data" / "analysis" / "AUDIT_REPORT_CLIP_HYGIENE.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="切片卫生自查")
    parser.add_argument("--stage", type=int, choices=[1, 2], default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.stage == 1:
        run_stage1()
    else:
        run_stage2(dry_run=args.dry_run)
        generate_report()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""切片主声道身份判断：检测 cleaned/clip_BV*.json 中非奶绿音轨污染。

问题：反应型切片夹源视频(LOL/教程/Vlog)，B站AI字幕识别主声道为源材料音轨。
所以判断标准不是"标题-内容是否匹配"，而是"这段字幕是不是奶绿在说话"。

阶段 1：客观指标粗筛（无 LLM）
阶段 2：LLM 精核（只跑可疑的）

用法：
    python3 scripts/clip_voice_audit.py --stage 1
    python3 scripts/clip_voice_audit.py --stage 2
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
OUTPUT_PATH = PROJECT_ROOT / "data" / "analysis" / "clip_voice_audit.json"

# ── 信号词表 ──

# 奶绿口癖（独白中高频出现）
KOUHUA_RE = re.compile(r"嗯|啊|就是|对吧|你知道吗|哈哈|哎|对对对|行了|我不|动动你的|不哈哈哈哈|你呀|好了好了|这样吧|拉倒|随你|爱咋咋|怎么说呢|本质上|说白了|我跟你说|神经|逆天|抽象|难绷|下头|没绷住|主包|奶糖花|NT花|兄弟们|大伙")

# 非奶绿话语强信号（按领域分组）
NON_NAILV_PATTERNS = {
    "lol_esports": re.compile(r"BLG|TARZAN|T1|WBG|小虎|阿bin|TheShy|Uzi|Doinb|Rookie|JackeyLove|Knight|369|TES|JDG|GEN\.G|LCK|LPL|世界赛|MSI|季后赛|BP|ban|pick|一血|三杀|四杀|五杀|团灭"),
    "pc_hardware": re.compile(r"分体水冷|主板|显卡|RTX|GTX|CPU|内存|电源|机箱|散热|超频|水冷头|冷排|水泵|风扇转速|RGB"),
    "travel_food": re.compile(r"机场|登机|航班|转机|安检|登机口|怀石|寿司|omakase|板前|天妇罗|割烹|温泉|酒店|check.?in"),
    "game_mechanics": re.compile(r"装备|血条|大招|BOSS|副本|团本|Buff|Debuff|DPS|Tank|奶妈|输出|走位|开怪|拉怪|AOE|CD|冷却"),
    "tutorial_intro": re.compile(r"欢迎回到|那这[0-9]年来|今天我们要|大家好这里是|各位观众朋友们|这期视频|上期视频|点赞投币|一键三连|关注转发"),
    "other_streamer": re.compile(r"关注主播|点个关注|加粉丝团|点亮灯牌|谢谢老板|老板大气|感谢我|感谢老铁|家人们"),
}

# 奶绿第一人称
FIRST_PERSON_RE = re.compile(r"我[^们]|我的|我是|我觉得|我想|我说|我看|我听|我跟你|我知道|我不懂|我不会")

# 其他视频开场白强信号
OTHER_VIDEO_INTRO_RE = re.compile(r"欢迎回到|那这[0-9]年来|今天我们要|大家好这里是|各位观众朋友们|这期视频|上期视频|点赞投币|一键三连|关注转发")


def compute_flags(clip_path: Path) -> dict:
    """对单个切片计算 4 项客观指标。"""
    with clip_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    segments = data.get("segments", [])
    title = data.get("title", "")
    n = len(segments)
    flags = []
    metrics = {}

    if n == 0:
        return {"bvid": clip_path.stem, "title": title[:100], "segments": 0, "flags": ["empty"], "metrics": {}, "suspicious": True}

    # 收集全部文本
    all_text = " ".join(s.get("text", "") for s in segments)
    first_20_text = " ".join(s.get("text", "") for s in segments[:20])

    # 1. 口癖密度
    kouhua_hits = len(KOUHUA_RE.findall(all_text))
    metrics["kouhua_density"] = round(kouhua_hits / max(n, 1), 3)
    if metrics["kouhua_density"] < 0.10 and n >= 8:
        flags.append("low_kouhua")

    # 2. 非奶绿话语强信号
    non_nailv_hits = {}
    total_non_nailv = 0
    for category, pattern in NON_NAILV_PATTERNS.items():
        hits = len(pattern.findall(first_20_text))
        if hits > 0:
            non_nailv_hits[category] = hits
            total_non_nailv += hits
    metrics["non_nailv_signals"] = non_nailv_hits
    metrics["non_nailv_total"] = total_non_nailv
    if total_non_nailv >= 2:
        flags.append("non_nailv_signal")

    # 3. 第一人称代词密度
    fp_hits = len(FIRST_PERSON_RE.findall(all_text))
    metrics["first_person_density"] = round(fp_hits / max(n, 1), 3)
    if metrics["first_person_density"] < 0.05 and n >= 10:
        flags.append("low_first_person")

    # 4. 其他视频开场白
    intro_hits = len(OTHER_VIDEO_INTRO_RE.findall(first_20_text))
    metrics["other_intro_hits"] = intro_hits
    if intro_hits >= 1:
        flags.append("other_video_intro")

    suspicious = len(flags) >= 2

    return {
        "bvid": clip_path.stem,
        "title": title[:120],
        "segments": n,
        "flags": flags,
        "metrics": metrics,
        "suspicious": suspicious,
    }


def run_stage1() -> list:
    """阶段 1：全量客观指标粗筛。"""
    clip_files = sorted(CLEANED_DIR.glob("clip_*.json"))
    print(f"[Stage 1] 扫描 {len(clip_files)} 个切片...", flush=True)

    results = []
    flag_counter = Counter()
    signal_counter = Counter()

    for i, f in enumerate(clip_files):
        r = compute_flags(f)
        results.append(r)
        for flag in r["flags"]:
            flag_counter[flag] += 1
        for cat in r["metrics"].get("non_nailv_signals", {}):
            signal_counter[cat] += 1
        if (i + 1) % 200 == 0:
            print(f"  [{i+1}/{len(clip_files)}] 已扫描", flush=True)

    suspicious = [r for r in results if r["suspicious"]]
    print(f"\n[Stage 1] 完成: {len(clip_files)} 切片")
    print(f"  可疑 (≥2 flags): {len(suspicious)}")
    print(f"  Flag 分布: {flag_counter.most_common()}")
    print(f"  非奶绿信号分布: {signal_counter.most_common(10)}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump({
            "stage": 1,
            "total": len(clip_files),
            "suspicious_count": len(suspicious),
            "flag_distribution": dict(flag_counter.most_common()),
            "signal_distribution": dict(signal_counter.most_common()),
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"  保存: {OUTPUT_PATH}")
    return results


def build_llm_prompt(r: dict) -> tuple:
    """为可疑切片构建 LLM 主声道判断 prompt。"""
    clip_path = CLEANED_DIR / f"{r['bvid']}.json"
    with clip_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    segments = data.get("segments", [])
    first_40 = segments[:40]
    text_lines = []
    for s in first_40:
        text_lines.append(f"[{s['start']:.0f}s] {s.get('text', '')}")
    preview = "\n".join(text_lines)

    system = """判断这段字幕主要是谁在说话。

1 = 奶绿独白为主（可能夹少量背景音或粉丝弹幕念读）
2 = 混合（部分奶绿，部分她在念SC/读投稿/转述别人内容）
3 = 主要是其他视频音轨（教程/比赛解说/游戏旁白/Vlog等），奶绿声音极少或听不到

注意："奶绿讲述别人的话/转述/念SC"算 1 或 2，不算 3。
3 是指字幕内容本身就是其他视频的台词（比如LOL解说词、Vlog旁白）。

输出 JSON: {"verdict": 1|2|3, "reason": "简短原因"}"""

    user = f"标题: {r['title']}\n\n前 40 段字幕:\n{preview[:3500]}"
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
            json_str = raw
            if json_str.startswith("```"):
                json_str = re.sub(r"^```\w*\n?", "", json_str)
                json_str = re.sub(r"\n```$", "", json_str)
            v = json.loads(json_str)
            r["verdict"] = v.get("verdict", 3)
            r["reason"] = v.get("reason", raw[:120])
        except Exception as e:
            r["verdict"] = 3
            r["reason"] = f"LLM error: {e}"
        verdicts[r["verdict"]] += 1

        if (i + 1) % 30 == 0:
            print(f"  [{i+1}/{len(suspicious)}] 已精核", flush=True)
        time.sleep(0.3)

    # 非可疑切片默认为干净
    for r in results:
        if not r["suspicious"]:
            r["verdict"] = 1
            r["reason"] = "passed stage 1 (not suspicious)"

    verdict_1 = [r for r in results if r.get("verdict") == 1]
    verdict_2 = [r for r in results if r.get("verdict") == 2]
    verdict_3 = [r for r in results if r.get("verdict") == 3]

    audit["stage"] = 2
    audit["summary"] = {
        "vocal_solo": len(verdict_1),
        "mixed": len(verdict_2),
        "source_video": len(verdict_3),
    }
    audit["verdict_3_list"] = [r["bvid"] for r in verdict_3]
    audit["verdict_1_list"] = [r["bvid"] for r in verdict_1[:100]]  # 前100个干净样本

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print(f"\n[Stage 2] 完成:")
    print(f"  Vocal Solo (verdict=1): {len(verdict_1)}")
    print(f"  Mixed (verdict=2): {len(verdict_2)}")
    print(f"  Source Video (verdict=3): {len(verdict_3)}")
    print(f"  保存: {OUTPUT_PATH}")


def generate_report():
    """生成 AUDIT_REPORT_CLIP_VOICE.md。"""
    if not OUTPUT_PATH.exists():
        print("ERROR: 请先跑 --stage 1", file=sys.stderr)
        sys.exit(1)

    audit = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    results = audit["results"]

    v1 = [r for r in results if r.get("verdict") == 1]
    v2 = [r for r in results if r.get("verdict") == 2]
    v3 = [r for r in results if r.get("verdict") == 3]
    total = len(results)

    lines = []
    lines.append("# 切片主声道身份判断报告\n")
    lines.append(f"**扫描时间**: 2026-05-16\n")
    lines.append(f"**总数**: {total} 切片\n")
    lines.append(f"**阶段 1 可疑**: {audit.get('suspicious_count', 0)} 个 (≥2 flags)\n\n")

    lines.append("## 概览\n")
    lines.append(f"| Verdict | 含义 | 数量 | 占比 |")
    lines.append(f"|---|---|---|---|")
    lines.append(f"| 1 | 奶绿独白为主 | {len(v1)} | {len(v1)/total*100:.1f}% |")
    lines.append(f"| 2 | 混合（奶绿+转述/念稿） | {len(v2)} | {len(v2)/total*100:.1f}% |")
    lines.append(f"| 3 | 源视频音轨为主（非奶绿） | {len(v3)} | {len(v3)/total*100:.1f}% |")
    lines.append("")

    # 影响评估
    lines.append("## 影响评估\n")
    dirty_segs = sum(r.get("segments", 0) for r in v3)
    total_segs = sum(r.get("segments", 0) for r in results)
    lines.append(f"- **Verdict=3 切片数**: {len(v3)}/{total}")
    lines.append(f"- **Verdict=3 总段数**: {dirty_segs}/{total_segs} ({dirty_segs/total_segs*100:.1f}% of all clip segments)" if total_segs else "")
    lines.append(f"- **对 keyword_stats 影响**: {dirty_segs} 段含非奶绿话语 → 口癖/下头/情绪统计受影响")
    lines.append(f"- **对 style_profile 影响**: 如果这 {len(v3)} 个切片已被 step 2 分析 → style_profile 含非奶绿信号")
    lines.append("")

    if v3:
        lines.append("## ⚠️ Verdict=3 完整清单（源视频音轨，建议归档）\n")
        lines.append("| BV | 标题 | Flags | 原因 |")
        lines.append("|---|---|---|---|")
        for r in sorted(v3, key=lambda x: x.get("bvid", "")):
            flags_str = ", ".join(r.get("flags", []))
            title = r.get("title", "")[:70]
            reason = r.get("reason", "")[:100]
            lines.append(f"| {r['bvid']} | {title} | {flags_str} | {reason} |")
        lines.append("")

    if v1:
        lines.append("## ✅ Verdict=1 干净独白样本（前 10）\n")
        for r in sorted(v1, key=lambda x: len(x.get("flags", [])), reverse=True)[:10]:
            lines.append(f"- **{r['bvid']}**: {r.get('title','')[:80]}")

    lines.append("\n## 典型样本对比\n")

    # Verdict=3 案例
    lines.append("### Verdict=3 源视频音轨（5 例）\n")
    for r in v3[:5]:
        lines.append(f"#### {r['bvid']}: {r.get('title','')[:80]}")
        lines.append(f"Flags: {', '.join(r.get('flags',[]))}")
        lines.append(f"Reason: {r.get('reason','')}")
        clip_path = CLEANED_DIR / f"{r['bvid']}.json"
        if clip_path.exists():
            d = json.loads(clip_path.read_text(encoding="utf-8"))
            segs = d.get("segments", [])[:5]
            for s in segs:
                lines.append(f"  [{s['start']:.0f}s] {s.get('text','')[:100]}")
        lines.append("")

    # Verdict=1 案例
    lines.append("### Verdict=1 奶绿独白（5 例）\n")
    for r in v1[:5]:
        lines.append(f"#### {r['bvid']}: {r.get('title','')[:80]}")
        lines.append(f"Flags: {r.get('flags',[])}")
        clip_path = CLEANED_DIR / f"{r['bvid']}.json"
        if clip_path.exists():
            d = json.loads(clip_path.read_text(encoding="utf-8"))
            segs = d.get("segments", [])[:3]
            for s in segs:
                lines.append(f"  [{s['start']:.0f}s] {s.get('text','')[:100]}")
        lines.append("")

    # Verdict=2 案例
    if v2:
        lines.append("### Verdict=2 混合（3 例）\n")
        for r in v2[:3]:
            lines.append(f"- **{r['bvid']}**: {r.get('title','')[:80]} | {r.get('reason','')[:100]}")

    lines.append(f"\n## Flag 分布\n")
    for flag, count in audit.get("flag_distribution", {}).items():
        lines.append(f"- **{flag}**: {count} 个切片")

    lines.append(f"\n## 非奶绿信号分布\n")
    for sig, count in audit.get("signal_distribution", {}).items():
        lines.append(f"- **{sig}**: {count} 个切片")

    report_path = PROJECT_ROOT / "data" / "analysis" / "AUDIT_REPORT_CLIP_VOICE.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="切片主声道身份判断")
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

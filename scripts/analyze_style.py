#!/usr/bin/env python3
"""Stage 4: 风格分析。

分三步:
    1. 关键词预标注 — 下头梗 / SC互动 / 场景 / 情绪 (全量)
    2. LLM 深度分析 — 对直播回放逐场提取风格特征
    3. 跨视频汇总 — 稳定特征 ≥3场 出现才保留

用法:
    python3 scripts/analyze_style.py --step 1           # 关键词预标注
    python3 scripts/analyze_style.py --step 2           # LLM 分析
    python3 scripts/analyze_style.py --step 3           # 汇总
    python3 scripts/analyze_style.py --step 1 --limit 10
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLEANED_DIR = PROJECT_ROOT / "data" / "cleaned"
OUTPUT_DIR = PROJECT_ROOT / "data" / "analysis"

# ── 关键词库 ───────────────────────────────────────

# 同音替代映射 (B站和谐规避): 发现新的随时加
HOMOPHONE_MAP = {
    "泡芙": "内射",
    "泡服": "内射",
    "泡夫": "内射",
    "傻福": "傻逼",
    "二福": "二逼",
    "牛福": "牛逼",
    "呆福": "呆逼",
    "憨福": "憨逼",
    "怂福": "怂逼",
    "菜福": "菜逼",
    "话福": "话逼",
    "作福": "作逼",
    "穷福": "穷逼",
    "low福": "low逼",
    "福格": "逼格",
    "苦福": "苦逼",
    "装福": "装逼",
    "撕福": "撕逼",
    "逗福": "逗逼",
}

# 下头梗 / 擦边 / 成人话题 (奶绿直播高频出现)
XIA_TOU_KEYWORDS = [
    # 直接下头词汇
    "下头", "逆天", "抽象", "难绷", "绷不住", "没绷住",
    "鸡毛", "叼毛", "吊毛",
    # 擦边/性暗示(避免单字泛匹配,优先用双字组合)
    "牛牛", "坤坤", "鸡儿",
    "射了", "硬了", "软了", "挺了",
    "湿了",
    "插进去", "拔出来",
    "撸管", "冲了",
    "do了", "doi",
    "内射", "中出", "颜射",
    # 身体部位相关
    "胸", "奶", "屁股", "腿", "腰", "腹肌", "黑丝", "白丝",
    # 成人话题
    "R18", "18禁", "黄油", "拔作", "GAL", "本子", "同人",
    "里番", "AV", "GV", "艾薇",
    "风俗", "泡泡浴", "按摩", "陪酒",
    "步非烟", "音声", "助眠", "奥术魔刃",
    # 生理/医学玩笑
    "前列腺", "高潮", "肾虚", "壮阳", "ED", "阳痿", "早泄",
    "月经", "生理期", "更年期",
    # 关系/情感话题(带下头角度)
    "小男友", "前夫", "出轨", "绿帽", "NTR",
    "渣男", "海王", "捞女", "PUA",
]

# SC 互动标记
SC_PATTERNS = [
    re.compile(r"(?i)\b[nN][cC]\b"),           # nc
    re.compile(r"(?i)\b[aA][cC]\b"),           # ac
    re.compile(r"谢谢.{0,10}(的|了).{0,5}([sS][cC]|舰长|提督|总督|醒目留言)"),
    re.compile(r"感谢.{0,10}(的|了).{0,5}([sS][cC]|舰长|提督|总督)"),
    re.compile(r"SC|sc|醒目留言"),
]

# 场景标识
SCENE_PATTERNS = {
    "开场": [re.compile(r"(大家好|欢迎|来了|开播|晚上好|早上好|下午好|hello|嗨|哈喽)")],
    "收尾": [re.compile(r"(下播|晚安|拜拜|再见|明天见|睡觉|告辞|溜了|下啦)")],
    "唱歌": [re.compile(r"(唱|歌|翻唱|cover|清唱|♪)")],
    "读SC": [re.compile(r"(SC|sc|醒目留言|念|读.{0,3}SC|谢谢.{0,5}SC)")],
    "锐评": [re.compile(r"(本质上|说白|你懂|我跟你讲|你听我说|不是.{0,5}是|这个东西)")],
    "游戏": [re.compile(r"(游戏|玩|打|操作|通关|副本|BOSS|装备|抽卡|氪金)")],
}

# 情绪标记
EMOTION_PATTERNS = {
    "吐槽/毒舌": [re.compile(r"(不是.{0,10}吗|咋的|啥.{0,5}啊|什么.{0,5}啊|你.{0,5}吧)")],
    "开心/轻快": [re.compile(r"(哈哈|嘿嘿|嘻嘻|笑|乐|开心|快乐|爽)")],
    "愤怒/激动": [re.compile(r"(气|烦|滚|爬|闭嘴|尼玛|卧槽|我靠|草)")],
    "慵懒/摆烂": [re.compile(r"(懒|困|累|摆|算了|随便|无所谓|爱咋咋|躺)")],
    "温柔/安抚": [re.compile(r"(没事|慢慢来|别急|乖|听话|好孩子|宝|亲爱的|崽)")],
}


# ── 关键词标注 ─────────────────────────────────────

def tag_segment(seg: dict) -> dict:
    """对单个 segment 做关键词标注。返回标签 dict。"""
    text = seg.get("text", "")
    text_lower = text.lower()
    tags = {
        "xia_tou": False,       # 含下头梗
        "xia_tou_kw": [],       # 命中的下头关键词
        "sc_related": False,    # 与 SC 互动相关
        "scenes": [],           # 命中的场景标签
        "emotions": [],         # 命中的情绪标签
    }

    # 同音替代检测(优先,更精确)
    for homo, actual in HOMOPHONE_MAP.items():
        if homo in text:
            tags["xia_tou"] = True
            tags["xia_tou_kw"].append(f"{homo}(={actual})")

    # 下头梗检测
    for kw in XIA_TOU_KEYWORDS:
        if kw in text:
            tags["xia_tou"] = True
            tags["xia_tou_kw"].append(kw)

    # SC 检测
    for pat in SC_PATTERNS:
        if pat.search(text):
            tags["sc_related"] = True
            break

    # 场景
    for scene, patterns in SCENE_PATTERNS.items():
        for pat in patterns:
            if pat.search(text):
                tags["scenes"].append(scene)
                break

    # 情绪
    for emotion, patterns in EMOTION_PATTERNS.items():
        for pat in patterns:
            if pat.search(text):
                tags["emotions"].append(emotion)
                break

    return tags


def _is_target_stem(stem: str) -> bool:
    """白名单:只接受奶绿真实数据,过滤开发期测试残留(如 bili_ai_*)。
    与 scripts/clean_text.py 的 is_target_stem 保持一致。
    """
    if stem.startswith("BV") or stem.startswith("clip_BV"):
        return True
    if "_BiliBili_" in stem:
        return True
    return False


def analyze_keywords(input_dir: Path, limit: int = 0) -> dict:
    """对所有清洗后文件做关键词标注,返回全局统计。"""
    all_files = sorted(input_dir.glob("*.json"))
    files = [f for f in all_files if _is_target_stem(f.stem)]
    if len(files) < len(all_files):
        skipped = [f.stem for f in all_files if not _is_target_stem(f.stem)]
        print(f"[step1] 已过滤 {len(skipped)} 个非奶绿命名文件: {skipped[:5]}", flush=True)
    if limit:
        files = files[:limit]

    print(f"[step1] 关键词标注: {len(files)} 个文件", flush=True)

    global_stats = {
        "total_segments": 0,
        "xia_tou_count": 0,
        "sc_count": 0,
        "scene_counter": Counter(),
        "emotion_counter": Counter(),
        "xia_tou_kw_counter": Counter(),
    }

    per_file_stats = {}

    for i, f in enumerate(files):
        with f.open("r", encoding="utf-8") as fp:
            data = json.load(fp)

        segments = data.get("segments", [])
        if not segments:
            continue

        file_xia_tou = 0
        file_sc = 0

        for seg in segments:
            tags = tag_segment(seg)
            seg["tags"] = tags
            global_stats["total_segments"] += 1

            if tags["xia_tou"]:
                file_xia_tou += 1
                for kw in tags["xia_tou_kw"]:
                    global_stats["xia_tou_kw_counter"][kw] += 1
            if tags["sc_related"]:
                file_sc += 1
            for s in tags["scenes"]:
                global_stats["scene_counter"][s] += 1
            for e in tags["emotions"]:
                global_stats["emotion_counter"][e] += 1

        global_stats["xia_tou_count"] += file_xia_tou
        global_stats["sc_count"] += file_sc

        # 保存标注后的文件
        out_path = OUTPUT_DIR / "tagged" / f.name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)

        xia_pct = file_xia_tou / len(segments) * 100 if segments else 0
        per_file_stats[f.stem] = {
            "segments": len(segments),
            "xia_tou": file_xia_tou,
            "xia_tou_pct": round(xia_pct, 1),
            "sc": file_sc,
            "title": data.get("title", ""),
        }

        if (i + 1) % 200 == 0:
            print(f"  [{i+1}/{len(files)}] 已处理", flush=True)

    # 输出全局统计
    total = global_stats["total_segments"]
    print(f"\n[step1] 标注完成: {total} 段", flush=True)
    print(f"  下头梗: {global_stats['xia_tou_count']} 段 ({global_stats['xia_tou_count']/total*100:.0f}%)", flush=True)
    print(f"  SC互动: {global_stats['sc_count']} 段 ({global_stats['sc_count']/total*100:.0f}%)", flush=True)
    print(f"  场景 TOP5: {global_stats['scene_counter'].most_common(5)}", flush=True)
    print(f"  情绪 TOP5: {global_stats['emotion_counter'].most_common(5)}", flush=True)
    print(f"  下头词 TOP10: {global_stats['xia_tou_kw_counter'].most_common(10)}", flush=True)

    # 下头密度最高的文件 TOP20
    top_xia = sorted(per_file_stats.items(), key=lambda x: x[1]["xia_tou_pct"], reverse=True)[:20]
    print(f"\n  下头密度最高 TOP20:", flush=True)
    for stem, s in top_xia:
        print(f"    {stem}: {s['xia_tou_pct']}% ({s['xia_tou']}/{s['segments']}) {s['title'][:50]}", flush=True)

    # 保存统计数据
    stats_path = OUTPUT_DIR / "keyword_stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    with stats_path.open("w", encoding="utf-8") as f:
        json.dump({
            "global": {
                "total_segments": total,
                "xia_tou_count": global_stats["xia_tou_count"],
                "xia_tou_pct": round(global_stats["xia_tou_count"] / total * 100, 1),
                "sc_count": global_stats["sc_count"],
                "scene_top": global_stats["scene_counter"].most_common(20),
                "emotion_top": global_stats["emotion_counter"].most_common(20),
                "xia_tou_kw_top": global_stats["xia_tou_kw_counter"].most_common(30),
            },
            "per_file": per_file_stats,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n  统计数据: {stats_path}", flush=True)
    return global_stats


# ── LLM 深度分析 (Step 2) ────────────────────────────

# 分析 prompt 模板
STYLE_ANALYSIS_SYSTEM = """你是一位语言学家和直播风格分析师。你的任务是对一位虚拟主播的直播文字记录进行风格分析。

## 分析维度

请从以下维度提取风格特征，每个维度给出具体例句（直接引用原文，标注时间戳）：

1. **口头禅与高频用语**：列出重复出现的固定表达，标注出现次数和典型语境。
2. **语气词模式**：惯用的语气助词、感叹词，"嗯""啊""嘛""呀"等的位置和频率。
3. **句式习惯**：长短句偏好、反问句/排比/省略等句式特征。
4. **称呼方式**：自称（我/姐/妈/主包）、称呼观众（宝子/大伙/奶糖花/你们）。
5. **互动模式**：怎么回应观众、怎么带节奏、怎么处理冷场或攻击。
6. **情绪切换**：不同情绪下的表达方式——轻快/吐槽/愤怒/慵懒/温柔。
7. **话题转换**：从一个话题跳到下一个的典型方式。
8. **下头梗/擦边内容**：识别文本中的谐音下头梗（如"草"=操、"鸡鸡"=技校谐音等），说明谐音逻辑和上下文。注意区分真下头和脑筋急转弯。
9. **人物矛盾**：捕捉她言行不一致、嘴硬心软、说一套做一套的时刻。

## 输出格式

请严格输出 JSON（不要 markdown 代码块包裹）：
{{
  "summary": "一句话概括本场直播的说话风格",
  "catchphrases": [{{"phrase":"口头禅","count":出现次数,"context":"典型场景"}}],
  "tone_particles": [{{"particle":"语气词","position":"句首/句中/句末","note":"使用特点"}}],
  "sentence_patterns": ["句式特征描述"],
  "addressing": {{"self":["自称方式"],"audience":["对观众的称呼"]}},
  "interaction": {{"response_style":"回应模式","pacing":"节奏特征","conflict_handling":"冲突处理方式"}},
  "emotion_switches": [{{"from":"情绪A","to":"情绪B","trigger":"切换触发条件","example":"例句"}}],
  "topic_transitions": ["转场方式"],
  "xia_tou": [{{"text":"原文","explanation":"谐音/双关/下头逻辑","is_real":true/false}}],
  "contradictions": ["言行不一致的时刻"],
  "unique_expressions": ["本场独有的特殊表达"]
}}"""


def sample_segments(segments: list, max_samples: int = 150) -> list:
    """从 segments 中均匀采样,确保覆盖全时间线。"""
    if len(segments) <= max_samples:
        return segments
    step = len(segments) / max_samples
    indices = [int(i * step) for i in range(max_samples)]
    return [segments[i] for i in indices]


def build_analysis_prompt(segments: list, notes: str = "") -> str:
    """构建发送给 LLM 的分析文本（2.1：盲测归纳，system 只含任务指令，notes 作为背景数据放在 user message）。"""
    system = STYLE_ANALYSIS_SYSTEM

    # 构建采样文本(带时间戳)
    text_lines = []
    for s in segments:
        ts = f"[{s['start']:.0f}s]"
        text_lines.append(f"{ts} {s['text']}")

    user_text = ""
    if notes and notes.strip():
        user_text += "## 本场背景参考（来自 Gemini 自动生成，仅供参考本场聊了什么主题）\n"
        user_text += notes[:2000] + "\n\n"
        user_text += "> ⚠️ 上述背景仅提供事实上下文（主题、事件、人物提及）。不要采纳其中的主观评价（如语气判断、人格描述），也不要复述它的措辞。你的风格归纳必须**完全从下方的字幕文本提取证据**。\n\n"
    user_text += "以下是本场直播的采样字幕文本（按时间顺序排列）：\n\n" + "\n".join(text_lines)
    return system, user_text


def analyze_single_video(input_path: Path, output_path: Path):  # -> dict|None
    """用 LLM 分析单个视频的清洗文本。"""
    load_dotenv(PROJECT_ROOT / ".env")

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    segments = data.get("segments", [])
    if not segments:
        print(f"  SKIP: 无 segments", flush=True)
        return None

    notes = data.get("notes", "")

    # 采样
    sampled = sample_segments(segments)
    system_prompt, user_text = build_analysis_prompt(sampled, notes)

    print(f"  采样 {len(sampled)}/{len(segments)} 段, 发送 LLM...", flush=True)

    try:
        client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL"),
        )
        resp = client.chat.completions.create(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            max_tokens=4096,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content
    except Exception as e:
        print(f"  ERROR: {e}", flush=True)
        return None

    # 解析 JSON
    try:
        # 去掉可能的 markdown 代码块包裹
        json_str = raw.strip()
        if json_str.startswith("```"):
            json_str = re.sub(r"^```\w*\n?", "", json_str)
            json_str = re.sub(r"\n```$", "", json_str)
        result = json.loads(json_str)
    except json.JSONDecodeError:
        print(f"  WARN: JSON 解析失败,保存原始响应", flush=True)
        result = {"raw": raw, "parse_error": True}

    # 保存
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump({
            "bvid": data.get("bvid", input_path.stem),
            "title": data.get("title", ""),
            "notes": notes,
            "samples": len(sampled),
            "total_segments": len(segments),
            "analysis": result,
        }, f, ensure_ascii=False, indent=2)

    return result


CLIP_ANALYSIS_SYSTEM = """你是一位语言学家和直播风格分析师。分析这段虚拟主播的直播切片字幕。

## 切片标题
{title}

## 分析维度
1. 语气特征（慵懒/锐评/吐槽/温柔/愤怒）
2. 口头禅或高频用语
3. 下头梗/谐音双关（如"草"=操、"技校"=鸡鸡），说明逻辑
4. 情绪变化
5. 值得关注的特殊表达

输出 JSON（不要 markdown 包裹）：
{{"tone":"语气","catchphrases":["口头禅"],"xia_tou":[{{"text":"原文","explanation":"谐音/下头逻辑","is_real":true/false}}],"emotion":"情绪","notable":["特殊表达"]}}"""


def run_llm_analysis(limit: int = 0) -> None:
    """对直播回放和切片执行 LLM 分析。"""
    load_dotenv(PROJECT_ROOT / ".env")

    # 多 worker 支持: 从 .env 读取 API key 数组
    api_keys_str = os.getenv("DEEPSEEK_API_KEYS", "")
    api_keys = [k.strip() for k in api_keys_str.split(",") if k.strip()] if api_keys_str else [os.getenv("DEEPSEEK_API_KEY")]
    worker_id = int(os.getenv("WORKER_ID", "0"))
    total_workers = int(os.getenv("TOTAL_WORKERS", "1"))
    api_key = api_keys[worker_id % len(api_keys)]

    client = OpenAI(api_key=api_key, base_url=os.getenv("DEEPSEEK_BASE_URL"))

    # 收集所有文件，直播回放优先
    live_files = sorted([f for f in CLEANED_DIR.glob("BV*.json") if not f.name.startswith("clip_")])
    clip_files = sorted(CLEANED_DIR.glob("clip_*.json"))
    all_files = live_files + clip_files

    # 分片: worker_id 取模
    all_files = [f for i, f in enumerate(all_files) if i % total_workers == worker_id]
    if limit:
        all_files = all_files[:limit]

    print(f"[step2] Worker {worker_id}/{total_workers}: {len(live_files)}回放+{len(clip_files)}切片={len(all_files)}文件 (key:{api_key[:12]}...)", flush=True)

    for i, f in enumerate(all_files):
        bvid = f.stem
        out_path = OUTPUT_DIR / "llm_analysis" / f"{bvid}.json"

        # 加载数据
        with f.open("r", encoding="utf-8") as fp:
            data = json.load(fp)

        segments = data.get("segments", [])
        if not segments:
            print(f"  [{i+1}/{len(all_files)}] {bvid} — 无segments,跳过", flush=True)
            continue

        total_segs = len(segments)
        notes = data.get("notes", "")
        title = data.get("title", "")

        # 判断是否 clip
        is_clip = f.name.startswith("clip_")

        # 采样: 直播回放采样150, 切片全文(通常<100段)
        if is_clip:
            sampled = segments
        else:
            sampled = sample_segments(segments)

        # 构建 prompt
        if is_clip:
            text_lines = []
            for s in sampled:
                text_lines.append(s["text"])
            user_text = "\n".join(text_lines)
            system = CLIP_ANALYSIS_SYSTEM.format(title=title)
            max_tok = 16384
        else:
            system, user_text = build_analysis_prompt(sampled, notes)
            max_tok = 16384

        if out_path.exists():
            with out_path.open("r", encoding="utf-8") as fp:
                existing = json.load(fp)
            if not existing.get("analysis", {}).get("parse_error"):
                print(f"  [{i+1}/{len(all_files)}] {bvid} — 已分析,跳过", flush=True)
                continue

        print(f"  [{i+1}/{len(all_files)}] {bvid} ({len(sampled)}/{total_segs}段)", end=" ", flush=True)

        try:
            resp = client.chat.completions.create(
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_text},
                ],
                max_tokens=max_tok,
                temperature=0.3,
            )
            raw = resp.choices[0].message.content
        except Exception as e:
            print(f"ERROR: {e}", flush=True)
            continue

        # 解析 JSON
        try:
            json_str = raw.strip()
            if json_str.startswith("```"):
                json_str = re.sub(r"^```\w*\n?", "", json_str)
                json_str = re.sub(r"\n```$", "", json_str)
            analysis = json.loads(json_str)
        except json.JSONDecodeError:
            print("⚠️ JSON解析失败", flush=True)
            analysis = {"raw": raw, "parse_error": True}

        # 保存
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as fp:
            json.dump({
                "bvid": data.get("bvid", bvid),
                "title": title,
                "notes": notes,
                "is_clip": is_clip,
                "samples": len(sampled),
                "total_segments": total_segs,
                "analysis": analysis,
            }, fp, ensure_ascii=False, indent=2)

        preview = analysis.get("tone", analysis.get("summary", "?"))[:60]
        print(f"✅ {preview}", flush=True)

    print(f"\n[step2] 完成,输出: {OUTPUT_DIR}/llm_analysis/", flush=True)


# ── Step 3: 跨视频汇总 ────────────────────────────

def load_clip_blacklist() -> set:
    """从 clip_voice_audit.json 读取 verdict=3 脏切片 BVID 黑名单。"""
    audit_path = OUTPUT_DIR / "clip_voice_audit.json"
    if not audit_path.exists():
        return set()
    with audit_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return set(data.get("verdict_3_list", []))


def cross_video_synthesis() -> dict:
    """合并所有单场分析,提炼跨场次稳定特征(≥3场)。"""
    blacklist = load_clip_blacklist()
    analysis_dir = OUTPUT_DIR / "llm_analysis"
    files = sorted(analysis_dir.glob("*.json"))
    if not files:
        print("ERROR: 无分析文件", flush=True)
        return {}

    original_count = len(files)
    files = [f for f in files if f.stem not in blacklist]
    if len(files) < original_count:
        print(f"[step3] 黑名单过滤: {original_count - len(files)} 个源视频音轨切片已排除", flush=True)
    print(f"[step3] 汇总 {len(files)} 场分析", flush=True)

    all_analyses = []
    for f in files:
        with f.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        analysis = data.get("analysis", {})
        if analysis.get("parse_error"):
            print(f"  SKIP {f.stem}: 解析失败", flush=True)
            continue
        all_analyses.append(analysis)

    # 1. 口头禅汇总 (跨≥3场)
    phrase_counter = Counter()
    phrase_contexts = defaultdict(list)
    for a in all_analyses:
        seen = set()
        for cp in a.get("catchphrases", []):
            # 兼容两种格式: dict {"phrase":"...",...} 或 纯字符串
            if isinstance(cp, str):
                phrase = cp
                ctx = ""
            elif isinstance(cp, dict):
                phrase = cp.get("phrase", cp.get("catchphrase", ""))
                ctx = cp.get("context", cp.get("note", ""))
            else:
                continue
            if phrase and phrase not in seen:
                phrase_counter[phrase] += 1
                phrase_contexts[phrase].append(ctx)
                seen.add(phrase)

    stable_phrases = [
        {"phrase": p, "frequency": c, "contexts": phrase_contexts[p][:5]}
        for p, c in phrase_counter.most_common(30) if c >= 3
    ]

    # 2. 语气词汇总
    particle_counter = Counter()
    for a in all_analyses:
        seen = set()
        tps = a.get("tone_particles", [])
        for tp in (tps if isinstance(tps, list) else []):
            if isinstance(tp, str):
                p = tp
            elif isinstance(tp, dict):
                p = tp.get("particle", "")
            else:
                continue
            if p and p not in seen:
                particle_counter[p] += 1
                seen.add(p)

    stable_particles = [
        {"particle": p, "frequency": c}
        for p, c in particle_counter.most_common(15) if c >= 3
    ]

    # 3. 称呼汇总
    self_refs = Counter()
    audience_refs = Counter()
    for a in all_analyses:
        addr = a.get("addressing", {})
        for s in addr.get("self", []):
            self_refs[s] += 1
        for au in addr.get("audience", []):
            audience_refs[au] += 1

    # 4. 互动模式汇总
    interaction_summary = []
    for a in all_analyses:
        inter = a.get("interaction", {})
        if inter:
            interaction_summary.append(inter)

    # 5. 下头梗汇总
    all_xia_tou = []
    for a in all_analyses:
        for x in a.get("xia_tou", []):
            if isinstance(x, dict):
                if x.get("is_real"):
                    all_xia_tou.append(x)
            elif isinstance(x, str) and x.strip():
                all_xia_tou.append({"text": x, "explanation": ""})

    # 6. 矛盾汇总
    all_contradictions = []
    for a in all_analyses:
        cons = a.get("contradictions", [])
        if isinstance(cons, list):
            for c in cons:
                if isinstance(c, str) and c.strip():
                    all_contradictions.append(c)

    # 7. 情绪切换模式
    switch_patterns = Counter()
    for a in all_analyses:
        for es in a.get("emotion_switches", []):
            pattern = f"{es.get('from','')}→{es.get('to','')}"
            switch_patterns[pattern] += 1
    stable_switches = [
        {"pattern": p, "count": c}
        for p, c in switch_patterns.most_common(10) if c >= 2
    ]

    result = {
        "videos_analyzed": len(all_analyses),
        "stable_phrases": stable_phrases,
        "stable_particles": stable_particles,
        "addressing": {
            "self": [s for s, c in self_refs.most_common(10)],
            "audience": [a for a, c in audience_refs.most_common(10)],
        },
        "interaction_profiles": interaction_summary,
        "xia_tou_patterns": all_xia_tou,
        "contradictions": list(set(all_contradictions)),
        "emotion_switches": stable_switches,
        "unique_expressions": [],
    }

    # 保存
    out_path = OUTPUT_DIR / "style_profile.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n  口头禅(≥3场): {len(stable_phrases)} 个", flush=True)
    for sp in stable_phrases[:10]:
        print(f"    {sp['phrase']}: {sp['frequency']}场", flush=True)

    print(f"\n  语气词(≥3场): {len(stable_particles)} 个", flush=True)
    for sp in stable_particles[:10]:
        print(f"    {sp['particle']}: {sp['frequency']}场", flush=True)

    print(f"\n  自称: {self_refs.most_common(5)}", flush=True)
    print(f"  称呼观众: {audience_refs.most_common(5)}", flush=True)
    print(f"\n  下头梗: {len(all_xia_tou)} 条", flush=True)
    print(f"  矛盾点: {len(result['contradictions'])} 条", flush=True)
    print(f"\n  输出: {out_path}", flush=True)

    return result


# ── CLI ────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Stage 4: 风格分析")
    parser.add_argument("--step", type=int, default=1, choices=[1, 2, 3],
                        help="1=关键词标注 2=LLM分析 3=汇总")
    parser.add_argument("--limit", type=int, default=0, help="限制处理数量")
    parser.add_argument("--bvid", help="只处理指定 BV(LIVE 文件)")
    args = parser.parse_args()

    if args.step == 1:
        analyze_keywords(CLEANED_DIR, args.limit)
    elif args.step == 2:
        run_llm_analysis(args.limit)
    elif args.step == 3:
        cross_video_synthesis()


if __name__ == "__main__":
    main()

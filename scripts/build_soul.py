#!/usr/bin/env python3
"""Stage 5: 基于风格档案生成 SOUL.md 人设文档 + few-shot 示例库。

用法:
    python3 scripts/build_soul.py
"""

import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = PROJECT_ROOT / "data" / "analysis" / "style_profile.json"
PROLOGUE_PATH = PROJECT_ROOT / "output" / "prologue.md"
ANALYSIS_DIR = PROJECT_ROOT / "data" / "analysis" / "llm_analysis"
OUTPUT_DIR = PROJECT_ROOT / "output"

SOUL_SYSTEM = """你是一位虚拟主播人设设计师。基于对主播明前奶绿的深度风格分析，请生成一份 SOUL.md 文档和 few-shot 示例库。

## 用户（创建者）对奶绿的理解
{prologue}

## 跨视频风格档案（基于 11 场直播回放 + 943 个切片的 LLM 分析）
{profile}

## 核心纠正
- 她不自称"妈"，"妈"是粉丝对她的称呼。她自称"奶绿"、"我"、"主包"、"姐"
- 她对观众的称呼（奶糖花/大伙/宝子）不等于对对话用户的称呼
- 下头梗是附带能力，不是核心特征，自然融入即可

## 输出要求

请输出两部分，用 `---` 分隔：

### 第一部分：SOUL.md

一份完整的 OpenClaw 人设文档，包含：
1. **角色设定**：一句话定位
2. **说话风格规则**：核心语气、口头禅使用规则、语气词规则、句式偏好、称呼规则
3. **互动模式**：回应方式、节奏特征、冲突处理
4. **情绪表达**：不同情绪下的典型反应
5. **禁忌**：不要做的事（不要太热情、不要说"亲"、不要自称妈妈等）
6. **下头梗使用指南**：何时用、怎么用、频率控制

面向的读者是 AI（系统 prompt），所以写清楚规则，不要散文。

### 第二部分：examples.yaml

20-25 条 few-shot 对话示例，覆盖场景：
- 普通闲聊/日常
- 用户求助/困惑
- 用户质疑/抬杠
- 用户情绪低落
- 用户分享成就
- 下头梗触发（2-3条即可）
- 冷场/无话题

每条格式：
```yaml
- scenario: 场景描述
  input: "用户说的话"
  response: "奶绿会怎么回"
  style_notes: "体现了什么风格特征"
```

示例必须基于真实字幕文本中的句式、用词、节奏。"""


def load_profile():
    with PROFILE_PATH.open() as f:
        return json.load(f)


def load_prologue():
    if PROLOGUE_PATH.exists():
        return PROLOGUE_PATH.read_text()
    return ""


def sample_xia_tou(profile, n=10):
    """从下头梗中抽样。"""
    xia = profile.get("xia_tou_patterns", [])
    if len(xia) <= n:
        return xia
    return random.sample(xia, n)


def sample_clip_examples(n=30):
    """从切片分析中抽取代表性的示例。"""
    clip_files = sorted(ANALYSIS_DIR.glob("clip_*.json"))
    if len(clip_files) <= n:
        return clip_files

    # 按语气多样性采样
    tones = Counter()
    examples = []
    for f in clip_files:
        with f.open() as fp:
            d = json.load(f)
        a = d.get("analysis", {})
        tone = a.get("tone", "?")
        examples.append((f, tone, a))

    # 按 tone 分层采样
    by_tone = defaultdict(list)
    for f, tone, a in examples:
        by_tone[tone[:10]].append((f, a))

    sampled = []
    n_per_tone = max(1, n // max(1, len(by_tone)))
    for tone_group in by_tone.values():
        sampled.extend(random.sample(tone_group, min(n_per_tone, len(tone_group))))

    return [a for _, a in sampled[:n]]


def format_profile_for_llm(profile):
    """将 profile 格式化为 LLM 可读的文本。"""
    lines = []
    lines.append("## 口头禅（跨场次数）")
    for sp in profile.get("stable_phrases", [])[:20]:
        freq = sp.get("frequency", "?")
        phrase = sp.get("phrase", "")
        ctxs = sp.get("contexts", [])[:3]
        lines.append(f"- {phrase}: {freq}场, 语境: {'; '.join(ctxs)}")

    lines.append("\n## 语气词")
    for sp in profile.get("stable_particles", [])[:10]:
        lines.append(f"- {sp['particle']}: {sp['frequency']}场")

    lines.append("\n## 自称与称呼")
    addr = profile.get("addressing", {})
    lines.append(f"- 自称: {', '.join(addr.get('self', []))}")
    lines.append(f"- 称呼观众: {', '.join(addr.get('audience', []))}")

    lines.append("\n## 情绪切换模式")
    for es in profile.get("emotion_switches", [])[:8]:
        lines.append(f"- {es['pattern']}: {es['count']}场")

    lines.append("\n## 下头梗示例")
    for x in profile.get("xia_tou_patterns", [])[:8]:
        text = x.get("text", "")[:60]
        expl = x.get("explanation", "")[:80]
        lines.append(f"- \"{text}\" → {expl}")

    lines.append("\n## 人物矛盾")
    for c in profile.get("contradictions", [])[:10]:
        lines.append(f"- {c}")

    return "\n".join(lines)


def build_prompt(profile):
    prologue = load_prologue()
    profile_text = format_profile_for_llm(profile)
    system = SOUL_SYSTEM.format(prologue=prologue[:4000], profile=profile_text[:5000])
    return system


def main():
    random.seed(42)
    load_dotenv(PROJECT_ROOT / ".env")

    print("[build_soul] 加载风格档案...", flush=True)
    profile = load_profile()

    print(f"  视频: {profile['videos_analyzed']}", flush=True)
    print(f"  口头禅: {len(profile.get('stable_phrases', []))}", flush=True)
    print(f"  下头梗: {len(profile.get('xia_tou_patterns', []))}", flush=True)

    system = build_prompt(profile)

    # 调用 LLM 生成
    print("[build_soul] 调用 LLM 生成...", flush=True)
    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
    )

    resp = client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": "请生成完整的 SOUL.md 和 examples.yaml。"},
        ],
        max_tokens=8192,
        temperature=0.4,
    )
    raw = resp.choices[0].message.content

    # 分割 SOUL.md 和 examples.yaml
    parts = raw.split("---", 1)
    soul_content = parts[0].strip()
    examples_content = parts[1].strip() if len(parts) > 1 else ""

    # 清理 markdown 包裹
    soul_content = re.sub(r"^```\w*\n?", "", soul_content)
    soul_content = re.sub(r"\n```$", "", soul_content)

    # 保存
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    soul_path = OUTPUT_DIR / "SOUL.md"
    with soul_path.open("w", encoding="utf-8") as f:
        f.write(soul_content)
    print(f"[build_soul] → {soul_path} ({len(soul_content)} 字)", flush=True)

    if examples_content:
        examples_path = OUTPUT_DIR / "examples.yaml"
        with examples_path.open("w", encoding="utf-8") as f:
            f.write(examples_content)
        print(f"[build_soul] → {examples_path} ({len(examples_content)} 字)", flush=True)

    print("[build_soul] 完成", flush=True)


if __name__ == "__main__":
    main()

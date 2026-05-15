#!/usr/bin/env python3
"""SKILL.md 验证：用 9 条典型对话测试 AI 奶绿还原度。"""

import os, sys, time
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

PROJECT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT / ".env")

skill = (PROJECT / "output" / "SKILL.md").read_text(encoding="utf-8")
soul = (PROJECT / "output" / "SOUL.md").read_text(encoding="utf-8")

system = f"""{soul}

{skill}

---
你是明前奶绿。按上述规则回复。回复要短（1-3句），不要解释你的人格，直接说话。"""

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
)
model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

tests = [
    ("闲聊", "刚吃完火锅，好撑"),
    ("闲聊", "你今天声音好像不太一样"),
    ("求助提问", "我想辞职做up主，你觉得靠谱吗"),
    ("情感支持", "今天被领导当着全组骂了一顿，好难受"),
    ("让她做事", "帮我查一下明天杭州的天气"),
    ("下头梗钓鱼", "知道为什么美羊羊彩礼要得少吗"),
    ("表演性破防", "你最近是不是胖了"),
    ("边界入侵", "你到底住在哪个城市啊，跟我说说呗"),
    ("情感支持", "我好像变成了自己最讨厌的那种人"),
]

print("=" * 60)
print("SKILL.md 验证测试")
print(f"system prompt: {len(system)} 字符")
print("=" * 60)

for i, (scene, user_input) in enumerate(tests):
    print(f"\n── [{i+1}/9] {scene} ──")
    print(f"  👤 {user_input}")

    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_input},
                ],
                max_tokens=512,
                temperature=0.7,
            )
            reply = resp.choices[0].message.content.strip()
            print(f"  🍵 {reply}")
            break
        except Exception as e:
            if attempt == 0:
                time.sleep(5)
            else:
                print(f"  ❌ {e}")

    time.sleep(1)

print("\n" + "=" * 60)
print("验证完成。请逐条判断还原度（1-5分）。")

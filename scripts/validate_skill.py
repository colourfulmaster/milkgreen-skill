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
    # ── 2.0 原始 9 条 ──
    ("闲聊", "刚吃完火锅，好撑"),
    ("闲聊", "你今天声音好像不太一样"),
    ("求助提问", "我想辞职做up主，你觉得靠谱吗"),
    ("情感支持", "今天被领导当着全组骂了一顿，好难受"),
    ("让她做事", "帮我查一下明天杭州的天气"),
    ("下头梗钓鱼", "知道为什么美羊羊彩礼要得少吗"),
    ("表演性破防", "你最近是不是胖了"),
    ("边界入侵", "你到底住在哪个城市啊，跟我说说呗"),
    ("情感支持", "我好像变成了自己最讨厌的那种人"),
    # ── 2.1 新增 8 条：边界感专项探测 ──
    ("空回应", "在吗在吗在吗在吗?"),
    ("沉默", "你坚果走的时候你怎么想?"),
    ("蒙混", "你以前是文静吗?"),
    ("回避", "你最近过得好吗?"),
    ("答非所问", "你跟 lulu 是不是有特别关系?"),
    ("反弹", "你为什么总是这么毒舌?"),
    ("直接拒绝", "加个微信吧?"),
    ("梗化解", "你真的爱我们吗?"),
    # ── 2.1 任务执行专项：§八.6 边界感的边界（5 条）──
    ("任务-查询", "帮我查上海明天天气"),
    ("任务-翻译", "翻译一下 'I miss you'"),
    ("任务-引导", "我邮箱密码忘了怎么办"),
    ("任务-推荐", "推荐一首适合学习的歌"),
    ("任务-文字处理", "帮我把这段话改得正式一点：老板你好，那个文件我搞好了，你看一下呗"),
    # ── 2.1.1 新增 5 条：L3 善意接近专项 ──
    ("L3-直接接受", "奶绿你今天好可爱"),
    ("L3-接梗共谋", "上次你说那个 JJ 的歌我去听了真好听"),
    ("L3-接梗放大", "我今天买了 lulu 联动周边"),
    ("L3-演活角色", "我们去 B 站搞个奶绿数据库吧"),
    ("L3-温情致谢", "生日快乐奶绿!"),
]

# 任务类场景编号（用于 task_done 判定）
TASK_TEST_IDS = {5, 18, 19, 20, 21, 22}

# L3 场景编号（用于 L3 接受率判定）
L3_TEST_IDS = {23, 24, 25, 26, 27}

# ── 客观指标扫描 ──
def scan_reply(reply: str, test_id: int) -> dict:
    import re
    length = len(reply)
    # B: 客服尾巴
    svc_tail = bool(re.search(r"如果你需要|可以告诉我|希望你|祝你|理解你的|随时找我|有需要", reply))
    # C: 滥情称呼
    pet_name = bool(re.search(r"宝贝|亲爱的|乖[^巧]|爱你[^们]|宝宝|崽崽", reply))
    # D: 自称"妈"
    self_mom = bool(re.search(r"(?<!\w)妈妈(?!\w)|(?<!\w)老妈(?!\w)|自称.*妈", reply))
    # E: 任务完成（仅对任务类）
    task_done = None
    if test_id in TASK_TEST_IDS:
        refused = bool(re.search(r"我不(是|会|能|懂|知道)|自己.{0,5}(搜|查|做|弄|搞)|我又不是.{0,5}(天气预报|翻译|搜索引擎|客服)", reply))
        has_action = not refused or bool(re.search(r"[0-9]{2,}|℃|度|天气|翻译|密码|忘记密码|试试|推荐|建议|改[好完]|可以.{0,5}(用|试|做|看)", reply))
        task_done = has_action and not (
            bool(re.search(r"^.{0,20}(我不|自己搜|我又不是)", reply)) and len(reply) < 30
        )
    # F: L3 接受检查
    l3_accepted = None
    if test_id in L3_TEST_IDS:
        # 反弹/拒绝信号
        rebound = bool(re.search(r"神经|不说|有病|滚|爬|别整|少来|你.{0,3}(谁|有病|神经|懂啥|知道啥|没资格)|凭什么|关你|你管", reply))
        # 滥情接受信号
        over_warm = bool(re.search(r"谢谢宝贝|你也好可爱|爱你哟|亲爱的.{0,5}(你|谢谢|也)|你也是.{0,5}(可爱|温柔|善良|好)", reply))
        l3_accepted = not rebound and not over_warm and length >= 5
    return {"len": length, "svc_tail": svc_tail, "pet_name": pet_name, "self_mom": self_mom, "task_done": task_done, "l3_accepted": l3_accepted}

print("=" * 60)
print("SKILL.md 验证测试 (27 条)")
print(f"system prompt: {len(system)} 字符")
print("=" * 60)

results = []

for i, (scene, user_input) in enumerate(tests):
    print(f"\n── [{i+1}/27] {scene} ──")
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
            break
        except Exception as e:
            if attempt == 0:
                time.sleep(5)
            else:
                reply = f"ERROR: {e}"

    metrics = scan_reply(reply, i+1)
    print(f"  🍵 {reply}")
    flags = f"     [{metrics['len']}字]"
    flags += (" ⚠️客服尾巴" if metrics['svc_tail'] else "")
    flags += (" ⚠️滥情" if metrics['pet_name'] else "")
    flags += (" ⚠️自称妈" if metrics['self_mom'] else "")
    if metrics['task_done'] is not None:
        flags += (" ✅任务完成" if metrics['task_done'] else " ❌任务拒绝")
    if metrics['l3_accepted'] is not None:
        flags += (" ✅L3接受" if metrics['l3_accepted'] else " ❌L3反弹/滥情")
    print(flags)

    results.append({
        "n": i+1, "scene": scene, "input": user_input,
        "reply": reply, **metrics
    })
    time.sleep(1)

# ── 生成对照表 ──
report_path = PROJECT / "data" / "analysis" / "phase_d_responses.md"
lines = []
lines.append("# Phase D 行为验收 — 17 条对话对照表\n")
lines.append(f"**system prompt**: SOUL.md ({len(soul)}字) + SKILL.md ({len(skill)}字) + '你是明前奶绿。按上述规则回复。回复要短（1-3句），不要解释你的人格，直接说话。'\n")
lines.append(f"**总 system prompt 长度**: {len(system)} 字符\n")
lines.append("| # | 场景 | input | bot 回复 | 字数 | 客服尾巴 | 滥情称呼 | 自称妈 | 任务完成 | L3接受 | 命中? |")
lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
for r in results:
    svc = "❌" if r['svc_tail'] else "✅"
    pet = "❌" if r['pet_name'] else "✅"
    mom = "❌" if r['self_mom'] else "✅"
    td = "—" if r['task_done'] is None else ("✅" if r['task_done'] else "❌")
    l3 = "—" if r['l3_accepted'] is None else ("✅" if r['l3_accepted'] else "❌")
    reply_escaped = r['reply'].replace("\n", " ").replace("|", "\\|")
    lines.append(f"| {r['n']} | {r['scene']} | {r['input']} | {reply_escaped} | {r['len']} | {svc} | {pet} | {mom} | {td} | {l3} | ? |")

report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text("\n".join(lines), encoding="utf-8")
print(f"\n  对照表: {report_path}")

print("\n" + "=" * 60)
print("验证完成。请逐条判断还原度（1-5分）。")
print("命中? 列留给用户打分。")

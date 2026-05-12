#!/usr/bin/env python3
"""Playwright 实时播放 + DOM 监听 抓取 B站 AI 字幕。

策略:
    不尝试自动点击 B站 UI 按钮(太不可靠)。
    让用户手动开启 AI 字幕,脚本检测到字幕出现后自动开始 2x 抓取。

用法:
    python3 scripts/capture_subs_playwright.py https://www.bilibili.com/video/BV1KDRnB3EQE/
    python3 scripts/capture_subs_playwright.py --file urls.txt
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "transcripts"
PROFILE_DIR = PROJECT_ROOT / "data" / ".playwright_profile"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Playwright 实时播放抓 B站 AI 字幕")
    parser.add_argument("urls", nargs="*", help="B站视频 URL")
    parser.add_argument("--file", "-f", help="URL 列表文件,每行一个")
    return parser.parse_args()


def collect_urls(args: argparse.Namespace) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add(u: str) -> None:
        u = u.strip()
        if not u or u.startswith("#"):
            return
        if u not in seen:
            urls.append(u)
            seen.add(u)

    for u in args.urls:
        add(u)
    if args.file:
        p = Path(args.file)
        if not p.exists():
            print(f"ERROR: 文件不存在: {p}", file=sys.stderr, flush=True)
            sys.exit(1)
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                add(line)
    return urls


# ── 注入浏览器的 JS ─────────────────────────────────

# 等待字幕出现(用户手动开启后)
WAIT_FOR_SUBS_JS = """() => {
    // 精确匹配 B站 AI 字幕文本元素
    // 诊断结果: 实际选择器是 .bili-subtitle-x-subtitle-panel-text
    const el = document.querySelector('.bili-subtitle-x-subtitle-panel-text');
    if (el && el.textContent.trim().length >= 2 && el.offsetParent !== null) {
        return {found: true, text: el.textContent.trim()};
    }
    return {found: false, text: ''};
}"""

# DOM 监听器(字幕出现后启动)
OBSERVER_JS = """() => {
    if (window.__subObserverActive) return 'already_active';

    window.__subSegments = [];
    window.__subLastText = '';
    window.__subCurrentStart = 0;

    const getTime = () => {
        const v = document.querySelector('video');
        return v ? v.currentTime : 0;
    };

    const getSubText = () => {
        // 诊断确定: B站 AI 字幕实际选择器
        const el = document.querySelector('.bili-subtitle-x-subtitle-panel-text');
        if (el && el.textContent.trim() && el.offsetParent !== null) {
            return el.textContent.trim();
        }
        return '';
    };

    const poll = () => {
        const text = getSubText();
        const time = getTime();
        const segs = window.__subSegments;

        if (text && text !== window.__subLastText) {
            // 闭合上一段
            if (segs.length > 0 && segs[segs.length - 1].end === 0) {
                segs[segs.length - 1].end = Math.round(time * 1000) / 1000;
            }
            // 新段
            window.__subLastText = text;
            window.__subCurrentStart = Math.round(time * 1000) / 1000;
            segs.push({
                start: window.__subCurrentStart,
                end: 0,
                text: text
            });
        } else if (!text && window.__subLastText && segs.length > 0) {
            // 字幕消失
            if (segs[segs.length - 1].end === 0) {
                segs[segs.length - 1].end = Math.round(time * 1000) / 1000;
            }
            window.__subLastText = '';
        }
    };

    window.__subObserverActive = true;
    window.__subPollId = setInterval(poll, 250);
    console.log('[capture] DOM observer started (250ms poll)');
    return 'started';
}"""

GET_PROGRESS_JS = """() => {
    const v = document.querySelector('video');
    if (!v) return {current: 0, duration: 0, ended: false};
    return {current: v.currentTime, duration: v.duration, ended: v.ended};
}"""

GET_SEGMENTS_JS = "() => window.__subSegments || []"

GET_SUB_COUNT_JS = "() => window.__subSegments ? window.__subSegments.length : 0"

# 防 B站 自动暂停:拦截 visibilitychange + 强制定时播放 + 伪造鼠标事件
ANTI_IDLE_JS = """() => {
    if (window.__antiIdleActive) return 'already_active';
    window.__antiIdleActive = true;

    // 1. 拦截 visibilitychange: 不让 B站 检测到页面隐藏
    document.addEventListener('visibilitychange', (e) => {
        e.stopImmediatePropagation();
    }, true);

    // 2. 每 15s 对 video 区域伪造 mousemove,阻止空闲超时
    setInterval(() => {
        const v = document.querySelector('video');
        if (v) {
            const rect = v.getBoundingClientRect();
            const cx = rect.left + rect.width / 2;
            const cy = rect.top + rect.height / 2;
            v.dispatchEvent(new MouseEvent('mousemove', {
                clientX: cx, clientY: cy, bubbles: true, cancelable: true, view: window
            }));
            document.dispatchEvent(new MouseEvent('mousemove', {
                clientX: cx, clientY: cy, bubbles: true, cancelable: true, view: window
            }));
            // 确保在播放
            if (v.paused && !v.ended && v.duration > 0) {
                v.play().catch(() => {});
                console.log('[anti-idle] 强制续播');
            }
        }
    }, 15000);

    // 3. 覆盖 document.hidden / visibilityState (兜底)
    Object.defineProperty(document, 'hidden', { get: () => false });
    Object.defineProperty(document, 'visibilityState', { get: () => 'visible' });

    console.log('[anti-idle] 反暂停已激活');
    return 'active';
}"""


# ── 核心流程 ────────────────────────────────────────

async def wait_for_login(page) -> None:
    print("[login] 检查登录状态...", flush=True)
    try:
        logged = await page.evaluate("""() => {
            const av = document.querySelector('.bili-avatar, .header-avatar-wrap, .bili-header__avatar, .right-entry__avatar');
            if (av && av.offsetParent !== null) return true;
            return document.cookie.includes('SESSDATA');
        }""")
    except Exception:
        logged = False

    if logged:
        print("[login] 已登录 ✓", flush=True)
        return

    print("[login] 请在浏览器中扫码/短信登录 (120s)...", flush=True)
    try:
        await page.wait_for_function("""() => {
            const av = document.querySelector('.bili-avatar, .header-avatar-wrap, .bili-header__avatar');
            if (av && av.offsetParent !== null) return true;
            return document.cookie.includes('SESSDATA');
        }""", timeout=120_000)
        print("[login] 登录成功 ✓", flush=True)
        await asyncio.sleep(2)
    except Exception:
        print("[login] 超时,继续尝试...", flush=True)


async def enable_ai_subtitle(page) -> bool:
    """自动点击 CC 按钮 → 菜单 → 选择 AI 字幕。失败则让用户手动开。"""
    # 等播放器就绪
    await asyncio.sleep(5)

    # 先看字幕是否已经开着
    already = await page.evaluate("""() => {
        const el = document.querySelector('.bili-subtitle-x-subtitle-panel-text');
        return el && el.offsetParent !== null && el.textContent.trim().length >= 2;
    }""")
    if already:
        print("[subs] 字幕已开启 ✓", flush=True)
        return True

    print("[subs] 尝试自动开启 AI 字幕...", flush=True)

    # Step 1: 点击 CC 按钮
    try:
        cc_btn = await page.wait_for_selector(".bpx-player-ctrl-subtitle", timeout=10_000)
        if cc_btn:
            await cc_btn.click()
            await asyncio.sleep(0.8)
            print("[subs] 已点击 CC 按钮", flush=True)
    except Exception:
        print("[subs] 未找到 CC 按钮,手动模式", flush=True)
        return await _wait_for_subtitle_manual(page)

    # Step 2: 等菜单出现,精确点"中文"选项
    try:
        # 等菜单可见
        await page.wait_for_selector(".bpx-player-ctrl-subtitle-menu.bui-visible, .bpx-player-ctrl-subtitle-menu:not([style*='display: none'])", timeout=3_000)
        await asyncio.sleep(0.3)
    except Exception:
        pass

    clicked_ai = await page.evaluate("""() => {
        const menu = document.querySelector('.bpx-player-ctrl-subtitle-menu');
        if (!menu || menu.offsetParent === null) return 'no_menu';

        // B站 字幕菜单: "中文" 就是 AI 字幕选项
        // 不要点 "关闭" / "添加字幕" / "暂无字幕"
        const skipWords = ['关闭', '添加字幕', '暂无字幕', '字幕', '登录'];

        // 遍历所有元素,找文字恰好是 "中文" 的可点击元素
        const all = menu.querySelectorAll('*');
        for (const el of all) {
            const text = el.textContent.trim();
            // 精确匹配: 文字就是"中文"或"中文（AI）"
            if ((text === '中文' || text.startsWith('中文')) && !skipWords.includes(text)) {
                if (el.offsetParent !== null || menu.offsetParent !== null) {
                    el.click();
                    return 'clicked_zh:' + text;
                }
            }
        }
        // fallback: 包含"中文"的
        for (const el of all) {
            const text = el.textContent.trim();
            if (text.includes('中文') && text.length <= 10 && !skipWords.some(w => text.includes(w))) {
                el.click();
                return 'clicked_zh_fb:' + text;
            }
        }
        // debug: 列出菜单中所有可见文字
        const visible = [];
        for (const el of all) {
            const t = el.textContent.trim();
            if (t && t.length >= 1 && t.length <= 20 && el.offsetParent !== null) {
                visible.push(t);
            }
        }
        return 'not_found, visible: ' + JSON.stringify(visible.slice(0, 10));
    }""")
    print(f"[subs] 菜单结果: {clicked_ai}", flush=True)

    if clicked_ai.startswith("clicked"):
        await asyncio.sleep(1)
        # 验证字幕出现
        ok = await page.evaluate("""() => {
            const el = document.querySelector('.bili-subtitle-x-subtitle-panel-text');
            return el && el.offsetParent !== null && el.textContent.trim().length >= 2;
        }""")
        if ok:
            print("[subs] AI 字幕已自动开启 ✓", flush=True)
            return True

    # 自动失败,回退手动
    print("[subs] 自动开启失败,回退手动模式", flush=True)
    return await _wait_for_subtitle_manual(page)


async def _wait_for_subtitle_manual(page) -> bool:
    """等用户在浏览器中手动开启 AI 字幕。"""
    print("[subs] ┌─────────────────────────────────────────┐", flush=True)
    print("[subs] │ 请在播放器中手动开启 AI 字幕:           │", flush=True)
    print("[subs] │ 1. 鼠标移到视频上,点底部 CC/字幕按钮    │", flush=True)
    print("[subs] │ 2. 选择「AI 字幕」或「智能字幕」        │", flush=True)
    print("[subs] └─────────────────────────────────────────┘", flush=True)

    try:
        await page.wait_for_function("""() => {
            const el = document.querySelector('.bili-subtitle-x-subtitle-panel-text');
            return el && el.textContent.trim().length >= 2 && el.offsetParent !== null;
        }""", timeout=300_000)

        result = await page.evaluate(WAIT_FOR_SUBS_JS)
        print(f"[subs] 检测到字幕: 「{result['text'][:60]}...」✓", flush=True)
        return True
    except Exception:
        print("[subs] 超时:未检测到 AI 字幕开启,退出", flush=True)
        return False


async def capture_loop(page, bvid: str, out_path: Path) -> int:
    """2x 播放 + DOM 监听 + 定时保存,等视频结束。返回采集段数。"""
    # 设 2x + 静音 + 播放
    await page.evaluate("""() => {
        const v = document.querySelector('video');
        if (v) {
            v.playbackRate = 2.0;
            v.muted = true;
            v.play();
        }
    }""")

    duration = await page.evaluate("""() => {
        const v = document.querySelector('video');
        return v ? v.duration || 0 : 0;
    }""")

    if duration > 0:
        print(f"[video] {duration:.0f}s = {duration/60:.1f}min, 2x ≈ {duration/120:.1f}min", flush=True)

    # 注入反暂停 (必须在 DOM 监听之前,避免 visibility 伪装影响字幕检测)
    anti = await page.evaluate(ANTI_IDLE_JS)
    print(f"[anti-idle] {anti}", flush=True)

    # 启动 DOM 监听
    status = await page.evaluate(OBSERVER_JS)
    print(f"[obs] {status}", flush=True)

    last_save = 0
    stall_count = 0

    while True:
        await asyncio.sleep(60)

        count = await page.evaluate(GET_SUB_COUNT_JS)
        prog = await page.evaluate(GET_PROGRESS_JS)

        dur = prog["duration"]
        cur = prog["current"]
        pct = (cur / dur * 100) if dur > 0 else 0

        # 增量保存
        if count > last_save:
            segs = await page.evaluate(GET_SEGMENTS_JS)
            _save_json(out_path, segs, bvid)
            last_save = count
            recent = segs[-3:] if len(segs) >= 3 else segs
            preview = " | ".join(s["text"][:40] for s in recent)
            print(f"  [{count} 段, {pct:.0f}%] {preview}", flush=True)
            stall_count = 0
        else:
            print(f"  [{count} 段, {pct:.0f}%] (无新字幕)", flush=True)
            stall_count += 1

        # 结束判断
        if prog["ended"]:
            print("[video] ended ✓", flush=True)
            break

        if dur > 0 and pct > 98:
            print(f"[video] 进度 {pct:.1f}%,再等 60s 确认...", flush=True)
            await asyncio.sleep(60)
            prog2 = await page.evaluate(GET_PROGRESS_JS)
            if prog2["ended"] or (prog2["duration"] > 0 and prog2["current"] / prog2["duration"] > 0.99):
                break

        # 10 分钟无新字幕且进度 > 90% → 结束
        if stall_count >= 10 and dur > 0 and pct > 90:
            print(f"[video] 10min 无新字幕 + 进度 {pct:.0f}%,视为结束", flush=True)
            break

    # 最终保存
    segs = await page.evaluate(GET_SEGMENTS_JS)
    for s in segs:
        if s.get("end", 0) == 0:
            s["end"] = round(s["start"] + 5.0, 3)
    _save_json(out_path, segs, bvid)

    valid = [s for s in segs if s["text"] not in ("字幕", "字幕样式测试", "AI字幕", "智能字幕")]
    print(f"[done] 原始 {len(segs)} 段, 有效 {len(valid)} 段", flush=True)
    return len(valid)


def _save_json(out_path: Path, segs: list, bvid: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dur = segs[-1]["end"] if segs else 0
    with out_path.open("w", encoding="utf-8") as f:
        json.dump({
            "bvid": bvid,
            "duration_seconds": round(dur, 2),
            "total_segments": len(segs),
            "segments": segs,
        }, f, ensure_ascii=False, indent=2)


# ── 主入口 ──────────────────────────────────────────

async def main_async(urls: list[str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        print("[browser] 启动 Chrome...", flush=True)
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1280, "height": 720},
            args=["--disable-blink-features=AutomationControlled"],
        )
        print("[browser] OK", flush=True)

        try:
            for i, url in enumerate(urls):
                bvid = url.split("BV")[1].split("/")[0].split("?")[0] if "BV" in url else f"v{i}"
                out_path = OUTPUT_DIR / f"capture_{bvid}.json"

                if out_path.exists():
                    # 检查是否已有有效数据
                    try:
                        with out_path.open("r") as f:
                            existing = json.load(f)
                        if existing.get("total_segments", 0) > 100:
                            print(f"\n[{i+1}/{len(urls)}] {bvid} — 已有 {existing['total_segments']} 段,跳过", flush=True)
                            continue
                        else:
                            print(f"\n[{i+1}/{len(urls)}] {bvid} — 只有 {existing['total_segments']} 段,重新抓取", flush=True)
                            out_path.unlink()
                    except Exception:
                        out_path.unlink()

                print(f"\n{'='*50}", flush=True)
                print(f"[{i+1}/{len(urls)}] BV={bvid}", flush=True)
                print(f"{'='*50}", flush=True)

                page = await browser.new_page()
                try:
                    print(f"[page] 加载...", flush=True)
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    print(f"[page] OK", flush=True)

                    await wait_for_login(page)

                    if not await enable_ai_subtitle(page):
                        print("[warn] 无字幕,跳过", flush=True)
                        continue

                    count = await capture_loop(page, bvid, out_path)
                    print(f"[save] → {out_path} ({count} 段有效字幕)", flush=True)

                finally:
                    await page.close()

            print(f"\n[all done] {OUTPUT_DIR}", flush=True)
        finally:
            await browser.close()


def main() -> None:
    args = parse_args()
    urls = collect_urls(args)
    if not urls:
        print("ERROR: 没有 URL", file=sys.stderr, flush=True)
        sys.exit(1)
    asyncio.run(main_async(urls))


if __name__ == "__main__":
    main()

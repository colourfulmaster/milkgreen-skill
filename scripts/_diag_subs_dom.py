#!/usr/bin/env python3
"""诊断脚本:探查 B站 AI 字幕的实际 DOM 结构。独立终端运行。"""
import asyncio, json, sys
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE = Path(__file__).resolve().parent.parent / "data" / ".playwright_profile"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), channel="chrome",
            headless=False, viewport={"width": 1280, "height": 720},
        )
        page = await browser.new_page()
        await page.goto("https://www.bilibili.com/video/BV1KDRnB3EQE/")

        print("请在浏览器中确保 AI 字幕已开启,然后按回车继续...", flush=True)
        input()

        # Dump subtitle elements
        result = await page.evaluate("""() => {
            const all = document.querySelectorAll('[class*="subtitle"], [class*="Subtitle"]');
            const out = [];
            all.forEach((el, i) => {
                if (i > 30) return;
                const rect = el.getBoundingClientRect();
                out.push({
                    tag: el.tagName,
                    class: el.className,
                    text: el.textContent.trim().substring(0, 100),
                    visible: el.offsetParent !== null,
                    x: Math.round(rect.x), y: Math.round(rect.y),
                    w: Math.round(rect.width), h: Math.round(rect.height),
                });
            });
            return out;
        }""")

        diag_path = Path(__file__).resolve().parent.parent / "data" / "_diag_output.json"
        with diag_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"\n=== {len(result)} 个 subtitle 元素 ===", flush=True)
        for el in result:
            mark = "VISIBLE" if el["visible"] else "hidden"
            print(f"<{el['tag']}> class=\"{el['class']}\" [{mark}]\n  text: \"{el['text']}\"", flush=True)

        html = await page.evaluate("""() => {
            const vp = document.querySelector('.bpx-player-video-wrap, .bpx-player-container');
            return vp ? vp.innerHTML.substring(0, 2000) : 'NOT FOUND';
        }""")
        print(f"\n=== 播放器 HTML 前2000字符 ===", flush=True)
        print(html, flush=True)
        print(f"\n已写入: {diag_path}", flush=True)

        await browser.close()

asyncio.run(main())

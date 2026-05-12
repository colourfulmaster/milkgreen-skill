#!/usr/bin/env python3
"""从 B站 AI字幕接口拉取字幕,输出与 whisper 转录一致的 JSON。

直接走 B站 player API + aisubtitle CDN,无需播放视频。
"""

import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

import browser_cookie3

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "transcripts"

# P1/P2/P3 cid 列表(从 yt-dlp 提前获取)
CID_MAP = {
    "P1": 37373741121,
    "P2": 37373740980,
    "P3": 37373740889,
}
BVID = "BV14KDtBSEnS"
MUSIC_THRESHOLD = 0.5  # music 置信度低于此值视为说话


def get_cookies() -> str:
    """从 Chrome 读取 B站 cookie。"""
    cj = browser_cookie3.chrome(domain_name="bilibili.com")
    return "; ".join(f"{c.name}={c.value}" for c in cj)


def fetch_subtitle_url(cid: int, cookie_str: str) -> Optional[str]:
    """从 player API 获取 AI字幕(a-zh)的 CDN 链接。"""
    url = f"https://api.bilibili.com/x/player/v2?bvid={BVID}&cid={cid}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.bilibili.com",
        "Cookie": cookie_str,
    })
    resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
    data = resp["data"]
    subs = data.get("subtitle", {}).get("subtitles", [])

    for s in subs:
        if s.get("lan", "").startswith("ai-"):
            return "https:" + s["subtitle_url"]

    print(f"  [warn] cid {cid}: 没有 ai-* 字幕 ({len(subs)} 条非AI字幕)")
    return None


def download_subtitle_json(sub_url: str) -> list:
    """下载字幕 JSON,返回 body 列表。"""
    req = urllib.request.Request(sub_url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.bilibili.com",
    })
    data = json.loads(urllib.request.urlopen(req, timeout=15).read())
    return data.get("body", [])


def filter_speech(segments: list) -> list:
    """根据 music 字段过滤:只保留说话,去掉 BGM 歌词。"""
    speech = []
    for seg in segments:
        if seg.get("music", 0) < MUSIC_THRESHOLD:
            speech.append({
                "start": round(seg["from"], 3),
                "end": round(seg["to"], 3),
                "text": seg["content"],
            })
    return speech


def main() -> None:
    cookie_str = get_cookies()
    print(f"[cookie] Chrome 中读取到 B站 cookies")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total_speech = 0
    for label, cid in CID_MAP.items():
        print(f"[{label}] cid={cid}")
        sub_url = fetch_subtitle_url(cid, cookie_str)
        if not sub_url:
            continue

        print(f"  字幕 URL: ...{sub_url[-40:]}")
        body = download_subtitle_json(sub_url)
        all_count = len(body)
        speech = filter_speech(body)
        speech_count = len(speech)

        print(f"  总字幕: {all_count}, 说话: {speech_count} (过滤 {all_count - speech_count} 条歌词)")

        out_path = OUTPUT_DIR / f"bili_ai_{label}.json"
        duration = body[-1]["to"] if body else 0
        with out_path.open("w", encoding="utf-8") as f:
            json.dump({
                "stem": f"bili_ai_{label}",
                "model": "B站 AI字幕 (lan=ai-zh)",
                "duration_seconds": round(duration, 2),
                "total_segments": all_count,
                "speech_segments": speech_count,
                "segments": speech,
            }, f, ensure_ascii=False, indent=2)

        print(f"  → {out_path.name} ({speech_count} 条说话, {duration:.0f}s)")
        total_speech += speech_count

        time.sleep(0.5)  # 谦逊间隔

    print(f"\n[完成] 共 {total_speech} 条说话,输出到 {OUTPUT_DIR}")


if __name__ == "__main__":
    main()

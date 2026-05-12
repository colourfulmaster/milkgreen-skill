#!/usr/bin/env python3
"""批量下载 B站合集/播放列表中有 AI 字幕的视频字幕。

用法:
    python3 scripts/download_collection_subs.py --season-id 722306
    python3 scripts/download_collection_subs.py --season-id 722306 --dry-run

流程:
    1. 获取合集视频列表(分页, API: x/space/fav/season/list)
    2. 逐视频获取 cid (x/player/pagelist)
    3. 查 player API → 有 AI 字幕则下载 SRT
    4. 无 AI 字幕则跳过,继续下一个
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import browser_cookie3

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "srt"

PAGE_SIZE = 30
SLEEP_API = 0.15  # API 间隔


def get_cookies() -> str:
    cj = browser_cookie3.chrome(domain_name="bilibili.com")
    return "; ".join(f"{c.name}={c.value}" for c in cj)


def api_get(url, cookie_str="", referer="https://www.bilibili.com"):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": referer,
    }
    if cookie_str:
        headers["Cookie"] = cookie_str
    req = urllib.request.Request(url, headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def list_collection_videos(season_id, cookie_str):
    """获取合集内所有视频列表(API 不分页,一次返回全部)。"""
    url = f"https://api.bilibili.com/x/space/fav/season/list?season_id={season_id}&pn=1&ps=30"
    resp = api_get(url, cookie_str)
    videos = []
    for a in resp["data"].get("medias", []):
        videos.append({
            "bvid": a["bvid"],
            "title": a["title"],
            "duration": a.get("duration", 0),
        })
    if not videos:
        print(f"ERROR: 合集为空", flush=True)
        sys.exit(1)
    return videos


def get_cid(bvid, cookie_str):
    """获取视频第一个分P的 cid。"""
    url = f"https://api.bilibili.com/x/player/pagelist?bvid={bvid}"
    try:
        resp = api_get(url, cookie_str)
        pages = resp.get("data", [])
        if pages:
            return pages[0].get("cid", 0)
    except Exception:
        pass
    return 0


def check_subtitle(bvid, cid, cookie_str):
    """检查视频是否有 AI 字幕。返回字幕 CDN URL 或 None。"""
    url = f"https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}"
    try:
        resp = api_get(url, cookie_str, referer=f"https://www.bilibili.com/video/{bvid}/")
    except Exception:
        return None

    subs = resp.get("data", {}).get("subtitle", {}).get("subtitles", [])
    for s in subs:
        lan = s.get("lan", "")
        if lan.startswith("ai-"):
            return "https:" + s["subtitle_url"]
    for s in subs:
        if s.get("lan", "") in ("zh-Hans", "zh-CN", "zh"):
            return "https:" + s["subtitle_url"]
    return None


def download_subtitle(sub_url):
    """下载字幕 JSON,返回 segments。"""
    resp = api_get(sub_url)
    return resp.get("body", [])


def subs_to_srt(segments):
    """字幕 segments → SRT 文本。"""
    lines = []
    for i, seg in enumerate(segments, 1):
        t_from = seg.get("from", seg.get("start", 0))
        t_to = seg.get("to", seg.get("end", 0))
        text = seg.get("content", seg.get("text", ""))
        lines.append(str(i))
        lines.append(f"{fmt_time(t_from)} --> {fmt_time(t_to)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def fmt_time(t):
    h, r = divmod(int(t), 3600)
    m, s = divmod(r, 60)
    ms = int((t % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def safe_name(name):
    return re.sub(r'[\\/:*?"<>|]', '_', name)[:80]


def main():
    parser = argparse.ArgumentParser(description="批量下载 B站合集字幕")
    parser.add_argument("--season-id", type=int, required=True, help="合集 season_id")
    parser.add_argument("--dry-run", action="store_true", help="只统计,不下载")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cookie_str = get_cookies()

    # Step 1: 获取视频列表
    videos = list_collection_videos(args.season_id, cookie_str)
    print(f"\n共 {len(videos)} 个视频, 检查字幕中...\n", flush=True)

    # Step 2: 逐视频检查
    has_subs = 0
    no_subs = 0
    total_segs = 0
    total_sec = 0

    for i, v in enumerate(videos):
        bvid = v["bvid"]
        title = v["title"]
        dur = v.get("duration", 0)

        print(f"[{i+1}/{len(videos)}] {bvid} {title[:45]} ", end="", flush=True)

        # 获取 cid
        cid = get_cid(bvid, cookie_str)
        if not cid:
            print("✗ 无cid", flush=True)
            no_subs += 1
            continue

        # 检查字幕
        sub_url = check_subtitle(bvid, cid, cookie_str)
        if not sub_url:
            print("✗ 无字幕", flush=True)
            no_subs += 1
            time.sleep(SLEEP_API)
            continue

        if args.dry_run:
            print(f"✓ 有字幕 ({dur}s)", flush=True)
            has_subs += 1
            total_sec += dur
            time.sleep(SLEEP_API)
            continue

        # 跳过已下载
        fname = f"{bvid}_{safe_name(title)}.srt"
        out_path = OUTPUT_DIR / fname
        if out_path.exists() and out_path.stat().st_size > 100:
            print(f"✓ 已存在", flush=True)
            has_subs += 1
            continue

        # 下载字幕
        try:
            segs = download_subtitle(sub_url)
        except Exception as e:
            print(f"✗ 下载失败", flush=True)
            no_subs += 1
            time.sleep(SLEEP_API)
            continue
        with out_path.open("w", encoding="utf-8") as f:
            f.write(subs_to_srt(segs))

        seg_dur = segs[-1].get("to", segs[-1].get("end", 0)) if segs else 0
        print(f"✓ {len(segs)}段 {seg_dur:.0f}s", flush=True)
        has_subs += 1
        total_segs += len(segs)
        total_sec += seg_dur
        time.sleep(SLEEP_API)

    # 汇总
    print(f"\n{'='*50}", flush=True)
    print(f"有字幕: {has_subs}  无字幕: {no_subs}", flush=True)
    if has_subs > 0:
        print(f"总条目: {total_segs}  总时长: {total_sec/60:.0f}min = {total_sec/3600:.1f}h", flush=True)
        print(f"输出: {OUTPUT_DIR}", flush=True)


if __name__ == "__main__":
    main()

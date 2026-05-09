#!/usr/bin/env python3
"""yt-dlp 批量下载直播录像。

用法:
    python3 scripts/download.py URL1 [URL2 ...]
    python3 scripts/download.py --file urls.txt

输出:
    data/raw_media/{上传日期}_{平台}_{标题}.{ext}
    同名 .info.json(含元信息:标题/上传者/时长 等)

特性:
    - 自动跳过已下载文件(no_overwrites)
    - 断点续传(continuedl)
    - 单个失败不中断整批(ignoreerrors)
"""

import argparse
import sys
from pathlib import Path

import yt_dlp

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "raw_media"


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="批量下载直播录像(yt-dlp)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 scripts/download.py https://www.bilibili.com/video/BV...\n"
            "  python3 scripts/download.py --file urls.txt\n"
            "\n"
            "urls.txt 格式:每行一个 URL,空行和 # 开头的行会被忽略"
        ),
    )
    parser.add_argument("urls", nargs="*", help="要下载的 URL(可传多个)")
    parser.add_argument(
        "--file",
        "-f",
        help="包含 URL 列表的文件,每行一个;# 开头视为注释",
    )
    return parser.parse_args()


def collect_urls(args: argparse.Namespace) -> list:
    """汇总命令行 + 文件里的 URL,去重并保留出现顺序。

    跳过空行和 # 开头的注释行。
    """
    urls: list = []
    seen: set = set()

    def add(url: str) -> None:
        url = url.strip()
        if not url or url.startswith("#"):
            return
        if url not in seen:
            urls.append(url)
            seen.add(url)

    for u in args.urls:
        add(u)

    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"ERROR: 文件不存在: {path}", file=sys.stderr)
            sys.exit(1)
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                add(line)

    return urls


def build_ydl_opts() -> dict:
    """构造 yt-dlp 选项。

    命名模板里 title.80s 是为了限制标题长度,避免某些平台超长标题
    导致文件名过长报错。
    """
    return {
        "outtmpl": str(
            OUTPUT_DIR / "%(upload_date)s_%(extractor)s_%(title).80s.%(ext)s"
        ),
        "continuedl": True,
        "no_overwrites": True,
        "ignoreerrors": True,
        "noplaylist": False,
        "writeinfojson": True,
        "writedescription": False,
        "writethumbnail": False,
        "concurrent_fragment_downloads": 4,
    }


def download(urls: list) -> None:
    """用 yt-dlp 批量下载。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    opts = build_ydl_opts()
    print(f"[download] 输出目录: {OUTPUT_DIR}")
    print(f"[download] 待下载 URL 数: {len(urls)}")
    print("[download] 命名规则: {上传日期}_{平台}_{标题}.{ext}")
    print()

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download(urls)


def main() -> None:
    args = parse_args()
    urls = collect_urls(args)

    if not urls:
        print("ERROR: 没有提供任何 URL,见 --help", file=sys.stderr)
        sys.exit(1)

    download(urls)
    print("[download] 全部任务完成。")


if __name__ == "__main__":
    main()

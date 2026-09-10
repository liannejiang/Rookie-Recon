"""Rookie-Recon 主流程：抓取 → 篩選 → 摘要 → 存檔 → 推送。"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from . import archive, publish
from .collect import check_feeds, collect
from .config import (
    LOOKBACK_DAYS,
    MAX_ITEMS,
    MIN_SCORE,
    SOURCES,
    TIMEZONE,
)
from .rank import select
from .summarize import summarize


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)-18s %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Rookie-Recon 資安週報")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="跑完抓取與篩選就停，不呼叫 API、不推送（測 feed 用）",
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="產生摘要與存檔但不送 Discord（測摘要品質用）",
    )
    parser.add_argument(
        "--check-feeds",
        action="store_true",
        help="只測試每個 RSS 來源是否還活著，不做其他事",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="把 Discord 版面印成純文字預覽（會呼叫 LLM，但不推送）",
    )
    parser.add_argument("--max-items", type=int, default=MAX_ITEMS)
    parser.add_argument("--days", type=int, default=LOOKBACK_DAYS)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)
    log = logging.getLogger("rookie-recon")

    if args.check_feeds:
        return 1 if check_feeds(SOURCES) == len(SOURCES) else 0

    now = datetime.now(ZoneInfo(TIMEZONE))
    date_str = now.strftime("%Y-%m-%d")
    week_label = now.strftime("%Y/%m/%d")

    items = collect(SOURCES, days=args.days)
    if not items:
        log.error("所有來源都沒抓到東西，可能是網路問題或 feed 全數失效")
        return 1

    chosen = select(items, max_items=args.max_items, min_score=MIN_SCORE)

    if args.dry_run:
        print(f"\n=== dry run：{len(chosen)} 則入選 ===\n")
        for item in chosen:
            print(f"[{item.score:6.1f}] {item.title}")
            print(f"         {item.source} · {item.url}")
            print(f"         {'; '.join(item.reasons[:6])}\n")
        return 0

    if not chosen:
        log.warning("沒有達到門檻的項目")
        if not args.no_publish:
            publish.publish_empty(week_label)
        return 0

    summaries = summarize(chosen)
    archive.write(chosen, summaries, date_str)

    if args.preview:
        print()
        print(publish.preview(chosen, summaries, week_label))
        return 0

    if args.no_publish:
        log.info("--no-publish：略過 Discord 推送")
        return 0

    publish.publish(chosen, summaries, week_label)
    log.info("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())

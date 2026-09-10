"""把週報排版成單一 Discord 訊息並透過 webhook 送出。

版面策略：整份週報 = 一個 embed，每則新聞 = 一個 field。
field 會自動加上粗體標題與換行，所以視覺上有清楚分隔，
又不會像「一則一個 embed」那樣把頻道洗成一長串色塊。

Discord 的硬限制（超過會被 400 退回，所以程式主動控管）：
  - 單一 embed 最多 25 個 field
  - field name 256 字、field value 1024 字
  - 一則訊息內所有 embed 的字元總和 6000
"""

from __future__ import annotations

import logging
import os
import time

import requests

from .collect import Item, canonical_url

log = logging.getLogger(__name__)

MAX_FIELDS = 25
FIELD_NAME_LIMIT = 256
FIELD_VALUE_LIMIT = 1024
EMBED_TOTAL_LIMIT = 6000
SAFETY_MARGIN = 400  # 留餘裕給 header、footer 與計算誤差

SEVERITY_ICON = {"high": "🔴", "medium": "🟠", "low": "🟢"}
ACCENT_COLOR = 0x4C6EF5  # 整份週報統一色，嚴重度改用 emoji 表示


def build_field(index: int, item: Item, summary: dict) -> dict:
    """一則新聞 = 一個 field。中英各一行，力求精簡。"""
    icon = SEVERITY_ICON.get(summary.get("severity", "medium"), "⚪")
    name = f"{icon}　{index}. {summary['title_zh']}"

    lines = [
        summary["summary_zh"],
        f"*{summary['summary_en']}*",
    ]

    if summary.get("why_it_matters"):
        lines.append(f"▸ {summary['why_it_matters']}")

    tags = summary.get("tags") or []
    meta = f"[{item.source} ↗]({canonical_url(item.url)})"
    if tags:
        meta += "　" + " ".join(f"`{t}`" for t in tags[:3])
    lines.append(meta)

    if summary.get("_verbatim"):
        lines.append("⚠️ *與原文有較長重複片段，待人工確認*")

    return {
        "name": name[:FIELD_NAME_LIMIT],
        "value": "\n".join(lines)[:FIELD_VALUE_LIMIT],
        "inline": False,
    }


def embed_size(embed: dict) -> int:
    """估算 embed 佔用的字元數，用來判斷要不要分成第二則訊息。"""
    total = len(embed.get("title", "")) + len(embed.get("description", ""))
    total += len(embed.get("footer", {}).get("text", ""))
    for field in embed.get("fields", []):
        total += len(field["name"]) + len(field["value"])
    return total


def build_embeds(items: list[Item], summaries: list[dict], week_label: str) -> list[dict]:
    """組出 embed。字元或 field 數超標時才切成第二個（第二則訊息送）。"""
    fields = [
        build_field(idx, item, summary)
        for idx, (item, summary) in enumerate(zip(items, summaries), start=1)
    ]

    header = {
        "title": f"🛰️  Rookie-Recon 資安週報　{week_label}",
        "description": (
            f"本週彙整 **{len(items)}** 則．中英雙語．點來源可讀原文\n"
            "_摘要由 AI 產生，細節請以原文為準_"
        ),
        "color": ACCENT_COLOR,
        "footer": {"text": f"來源 {len({i.source for i in items})} 家　·　🔴 高　🟠 中　🟢 低"},
    }

    embeds: list[dict] = []
    current = dict(header, fields=[])
    budget = EMBED_TOTAL_LIMIT - SAFETY_MARGIN

    for field in fields:
        too_many = len(current["fields"]) >= MAX_FIELDS
        too_long = embed_size(current) + len(field["name"]) + len(field["value"]) > budget

        if current["fields"] and (too_many or too_long):
            embeds.append(current)
            current = {
                "title": f"🛰️  資安週報（續）　{week_label}",
                "color": ACCENT_COLOR,
                "fields": [],
            }

        current["fields"].append(field)

    embeds.append(current)
    return embeds


def post(webhook_url: str, payload: dict, retries: int = 3) -> None:
    """送一則訊息，遇到 429 依 Discord 給的等待時間重試。"""
    for attempt in range(retries):
        response = requests.post(webhook_url, json=payload, timeout=30)

        if response.status_code == 429:
            wait = response.json().get("retry_after", 5)
            log.warning("觸發 rate limit，等待 %.1f 秒", wait)
            time.sleep(float(wait) + 0.5)
            continue

        if response.status_code >= 400:
            log.error("Discord 回應 %d：%s", response.status_code, response.text[:500])
            response.raise_for_status()

        return

    raise RuntimeError(f"重試 {retries} 次後仍無法送出")


def webhook() -> str:
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        raise RuntimeError("缺少環境變數 DISCORD_WEBHOOK_URL")
    return url


def publish(items: list[Item], summaries: list[dict], week_label: str) -> None:
    """送出整份週報。正常情況是一則訊息，超長才會有第二則。"""
    url = webhook()
    embeds = build_embeds(items, summaries, week_label)

    for idx, embed in enumerate(embeds, start=1):
        post(url, {"embeds": [embed], "allowed_mentions": {"parse": []}})
        log.info(
            "已送出第 %d/%d 則訊息（%d 則新聞、約 %d 字）",
            idx, len(embeds), len(embed.get("fields", [])), embed_size(embed),
        )
        if idx < len(embeds):
            time.sleep(1)


def preview(items: list[Item], summaries: list[dict], week_label: str) -> str:
    """把即將送出的內容印成純文字，本機測版面用，不呼叫 Discord。"""
    out = []
    for embed in build_embeds(items, summaries, week_label):
        out.append(f"┌─ {embed.get('title', '')}")
        for line in embed.get("description", "").split("\n"):
            if line:
                out.append(f"│  {line}")
        for field in embed.get("fields", []):
            out.append("│")
            out.append(f"│  {field['name']}")
            for line in field["value"].split("\n"):
                out.append(f"│    {line}")
        out.append(f"└─ 約 {embed_size(embed)} / {EMBED_TOTAL_LIMIT} 字元\n")
    return "\n".join(out)


def publish_empty(week_label: str) -> None:
    """本週沒有夠格的新聞時也要出聲，否則你會分不清是沒新聞還是壞了。"""
    post(
        webhook(),
        {
            "embeds": [{
                "title": f"🛰️  Rookie-Recon 資安週報　{week_label}",
                "description": (
                    "本週沒有達到篩選門檻的項目。若連續多週如此，"
                    "請檢查 feed 是否失效（`--check-feeds`）或 `MIN_SCORE` 是否設太高。"
                ),
                "color": 0x8899A6,
            }],
            "allowed_mentions": {"parse": []},
        },
    )

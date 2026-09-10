"""把每週結果存成 markdown，方便回頭抽查摘要品質，也是歷史存檔。"""

from __future__ import annotations

import logging
from pathlib import Path

from .collect import Item, canonical_url

log = logging.getLogger(__name__)

ARCHIVE_DIR = Path("archive")


def write(items: list[Item], summaries: list[dict], date_str: str) -> Path:
    lines = [
        f"# Rookie-Recon 資安週報 {date_str}",
        "",
        f"共 {len(items)} 則。摘要由 Claude 產生，細節以原文為準。",
        "",
    ]

    for idx, (item, summary) in enumerate(zip(items, summaries), start=1):
        tags = " ".join(f"`{t}`" for t in (summary.get("tags") or []))
        lines += [
            f"## {idx}. {summary['title_zh']}",
            "",
            f"*{summary['title_en']}*",
            "",
            summary["summary_zh"],
            "",
            summary["summary_en"],
            "",
        ]
        if summary.get("why_it_matters"):
            lines += [f"**為什麼重要**：{summary['why_it_matters']}", ""]
        if summary.get("_verbatim"):
            lines += [
                "> ⚠️ 疑似與原文重複的片段（待人工確認）：",
                "> " + " / ".join(summary["_verbatim"]),
                "",
            ]
        lines += [
            f"來源：[{item.source}]({canonical_url(item.url)})　·　"
            f"嚴重度：{summary.get('severity', 'medium')}　·　"
            f"分數：{item.score}　{tags}",
            "",
            f"<!-- 評分理由：{'; '.join(item.reasons)} -->",
            "",
            "---",
            "",
        ]

    ARCHIVE_DIR.mkdir(exist_ok=True)
    path = ARCHIVE_DIR / f"{date_str}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("已寫入存檔 %s", path)
    return path

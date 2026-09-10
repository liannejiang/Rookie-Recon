"""規則式評分與挑選。刻意不用 LLM：規則穩定、可解釋、零成本。"""

from __future__ import annotations

import logging
import re

from .collect import Item
from .config import (
    CVE_MENTION_BOOST,
    CVSS_HIGH_BOOST,
    CVSS_MED_BOOST,
    KEYWORD_WEIGHTS,
    MAX_PER_SOURCE,
    NEGATIVE_KEYWORDS,
    REGION_BOOST,
)

log = logging.getLogger(__name__)

CVE_RE = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)
CVSS_RE = re.compile(r"CVSS[^\d]{0,20}(\d{1,2}(?:\.\d)?)", re.IGNORECASE)

TITLE_MULTIPLIER = 3.0  # 標題命中比摘要命中重要


def score_item(item: Item) -> Item:
    """算分並記下理由，方便你回頭調權重。"""
    total = 0.0
    reasons: list[str] = []

    title = item.title.lower()
    summary = item.summary.lower()

    for keyword, weight in KEYWORD_WEIGHTS.items():
        hit = 0.0
        if keyword in title:
            hit += weight * TITLE_MULTIPLIER
        if keyword in summary:
            hit += weight
        if hit:
            total += hit
            reasons.append(f"{keyword} +{hit:.1f}")

    for keyword, penalty in NEGATIVE_KEYWORDS.items():
        if keyword in title or keyword in summary:
            total += penalty
            reasons.append(f"{keyword} {penalty:.1f}")

    if CVE_RE.search(item.text):
        total += CVE_MENTION_BOOST
        reasons.append(f"CVE +{CVE_MENTION_BOOST:.1f}")

    cvss_scores = [float(m) for m in CVSS_RE.findall(item.text)]
    cvss_scores = [s for s in cvss_scores if 0 <= s <= 10]
    if cvss_scores:
        top = max(cvss_scores)
        if top >= 9.0:
            total += CVSS_HIGH_BOOST
            reasons.append(f"CVSS {top} +{CVSS_HIGH_BOOST:.1f}")
        elif top >= 7.0:
            total += CVSS_MED_BOOST
            reasons.append(f"CVSS {top} +{CVSS_MED_BOOST:.1f}")

    if item.region == "au":
        total += REGION_BOOST
        reasons.append(f"AU +{REGION_BOOST:.1f}")

    total *= item.trust
    if item.trust != 1.0:
        reasons.append(f"×{item.trust} 來源加權")

    item.score = round(total, 2)
    item.reasons = reasons
    return item


def select(items: list[Item], max_items: int, min_score: float) -> list[Item]:
    """
    依分數排序後挑選，同時限制單一來源的則數，
    避免整份週報被一家媒體佔滿。
    """
    scored = sorted((score_item(i) for i in items), key=lambda i: -i.score)

    chosen: list[Item] = []
    per_source: dict[str, int] = {}

    for item in scored:
        if item.score < min_score:
            break
        if per_source.get(item.source, 0) >= MAX_PER_SOURCE:
            continue
        chosen.append(item)
        per_source[item.source] = per_source.get(item.source, 0) + 1
        if len(chosen) >= max_items:
            break

    log.info("入選 %d 則（候選 %d 則）", len(chosen), len(scored))
    for item in chosen:
        log.debug("  %.1f  %s  [%s]", item.score, item.title[:60], item.source)
    return chosen

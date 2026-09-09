"""產生雙語摘要，並機械檢查有沒有整段照抄原文。

供應商是 OpenAI 相容介面（GitHub Models / Gemini），用 LLM_PROVIDER 切換。
免費層單次請求有 8K in / 4K out 的上限，所以刻意「一則新聞一次請求」，
不整批送——整批送很容易在輸出端被截斷，而且截斷後 JSON 會壞掉。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

import requests

from .collect import Item
from .config import (
    DEFAULT_PROVIDER,
    PROVIDERS,
    REQUEST_INTERVAL,
    REQUEST_TIMEOUT,
)

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是資安週報的編輯，讀者是資安領域的學生與初階從業者，同時使用繁體中文與英文。

針對這一則新聞，用你自己的話撰寫摘要。這是最重要的要求：不得複製原文的句子或片語，必須重新組織成新的句子。

**篇幅要求（讀者在 Discord 上快速掃過，務必精簡）**
- title_zh：繁體中文標題，16 字以內，台灣用語
- title_en：英文標題，10 個單字以內
- summary_zh：繁體中文，1-2 句、40-60 字，只講最關鍵的事實
- summary_en：英文，1 句、25 個單字以內
- why_it_matters：繁體中文一句話，25 字以內，說明誰受影響或該做什麼
- severity：只能是 "high"、"medium"、"low" 之一
- tags：2-3 個英文小寫標籤，例如 ["ransomware", "australia"]

**其他規則**
- 技術名詞保留原文並可加括號，例如「遠端程式碼執行（RCE）」
- CVE 編號、產品名稱、版本號原樣保留
- 只根據提供的內容撰寫，不得補充輸入中沒有出現的細節
- 資訊不足時寧可寫短，絕不推測或編造
- 語氣中性，不要用「震撼」「駭人」這類字眼

只輸出一個 JSON 物件，不要有前言、說明或 markdown 圍籬。"""

REQUIRED_FIELDS = ("title_zh", "title_en", "summary_zh", "summary_en")


def resolve_provider() -> dict:
    """讀環境變數決定供應商，並確認 key 存在。"""
    name = os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower()
    if name not in PROVIDERS:
        raise RuntimeError(
            f"未知的 LLM_PROVIDER：{name}（可用：{', '.join(PROVIDERS)}）"
        )

    provider = dict(PROVIDERS[name], name=name)
    key = os.environ.get(provider["key_env"], "").strip()
    if not key:
        raise RuntimeError(
            f"缺少環境變數 {provider['key_env']}"
            f"（LLM_PROVIDER={name} 需要它）"
        )
    provider["api_key"] = key
    return provider


def build_user_prompt(item: Item) -> str:
    payload = {
        "source": item.source,
        "title": item.title,
        "content": item.summary or "(RSS 未提供摘要，僅有標題)",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def parse_json_object(text: str) -> dict:
    """去掉可能的 markdown 圍籬後解析 JSON 物件。"""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    # 模型偶爾會在物件前後多寫一行字，抓最外層的 {...} 比較穩
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("回傳的不是 JSON 物件")
    return data


def call_model(provider: dict, item: Item, use_json_mode: bool) -> str:
    """呼叫一次 chat completions，回傳純文字內容。"""
    body = {
        "model": provider["model"],
        "temperature": 0.3,
        "max_tokens": 900,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(item)},
        ],
    }
    if use_json_mode:
        body["response_format"] = {"type": "json_object"}

    response = requests.post(
        f"{provider['base_url']}/chat/completions",
        headers={
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=REQUEST_TIMEOUT,
    )

    # 免費層被限流時退讓重試
    if response.status_code == 429:
        wait = float(response.headers.get("retry-after", 30))
        log.warning("觸發速率限制，等待 %.0f 秒後重試", wait)
        time.sleep(wait + 1)
        return call_model(provider, item, use_json_mode)

    # 有些相容端點不支援 response_format，退回純提示模式
    if response.status_code == 400 and use_json_mode:
        log.info("此端點不接受 response_format，改用純提示模式")
        return call_model(provider, item, use_json_mode=False)

    if response.status_code >= 400:
        raise RuntimeError(
            f"{provider['name']} 回應 {response.status_code}：{response.text[:300]}"
        )

    data = response.json()
    return data["choices"][0]["message"]["content"] or ""


def summarize_one(provider: dict, item: Item) -> dict:
    """單則摘要，失敗時回傳保底內容而不是讓整份週報掛掉。"""
    for attempt in (1, 2):
        try:
            raw = call_model(provider, item, provider["json_mode"])
            entry = parse_json_object(raw)
        except (requests.RequestException, RuntimeError) as exc:
            log.warning("第 %d 次呼叫失敗（%s）：%s", attempt, item.title[:40], exc)
            time.sleep(5)
            continue
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("第 %d 次解析失敗（%s）：%s", attempt, item.title[:40], exc)
            continue

        missing = [f for f in REQUIRED_FIELDS if not entry.get(f)]
        if missing:
            log.warning("缺少欄位 %s，重試一次", missing)
            continue

        entry.setdefault("why_it_matters", "")
        entry.setdefault("severity", "medium")
        entry.setdefault("tags", [])
        if entry["severity"] not in ("high", "medium", "low"):
            entry["severity"] = "medium"
        return entry

    log.error("兩次都失敗，改用原標題保底：%s", item.title[:60])
    return fallback(item)


def summarize(items: list[Item]) -> list[dict]:
    """依序處理每一則，中間間隔以符合免費層速率限制。"""
    if not items:
        return []

    provider = resolve_provider()
    log.info(
        "供應商 %s / 模型 %s，共 %d 則，預估耗時約 %.0f 秒",
        provider["name"],
        provider["model"],
        len(items),
        len(items) * REQUEST_INTERVAL,
    )

    results: list[dict] = []
    for idx, item in enumerate(items, start=1):
        log.info("[%d/%d] %s", idx, len(items), item.title[:60])
        results.append(summarize_one(provider, item))
        if idx < len(items):
            time.sleep(REQUEST_INTERVAL)

    failed = sum(1 for r in results if r.get("_fallback"))
    if failed:
        log.warning("%d/%d 則摘要失敗（已用原標題保底）", failed, len(items))

    flag_verbatim(items, results)
    return results


def fallback(item: Item) -> dict:
    """摘要失敗時的保底內容：只放原標題，明確標示未摘要。"""
    return {
        "title_zh": item.title[:80],
        "title_en": item.title[:80],
        "summary_zh": "（本則摘要產生失敗，請點連結閱讀原文）",
        "summary_en": "(Summary generation failed — see original article.)",
        "why_it_matters": "",
        "severity": "medium",
        "tags": [],
        "_fallback": True,
    }


# ------------------------------------------------------- 照抄檢查
WORD_RE = re.compile(r"[a-z0-9']+")


def longest_shared_run_en(summary: str, source: str, window: int = 8) -> str | None:
    """英文以「連續 8 個單字」為單位比對。"""
    s_words = WORD_RE.findall(summary.lower())
    src = " ".join(WORD_RE.findall(source.lower()))
    for i in range(len(s_words) - window + 1):
        chunk = " ".join(s_words[i : i + window])
        if chunk in src:
            return chunk
    return None


def longest_shared_run_zh(summary: str, source: str, window: int = 15) -> str | None:
    """中文以「連續 15 個字」為單位比對（中文沒有空白可切詞）。"""
    clean = re.sub(r"\s+", "", summary)
    src = re.sub(r"\s+", "", source)
    for i in range(len(clean) - window + 1):
        chunk = clean[i : i + window]
        if chunk in src:
            return chunk
    return None


def flag_verbatim(items: list[Item], summaries: list[dict]) -> None:
    """
    標記可能照抄原文的摘要。只記 log 並在 archive 加註，不自動刪除
    ——先累積幾週實際案例，再決定要不要改 prompt 或直接擋掉。
    """
    for item, summary in zip(items, summaries):
        if summary.get("_fallback"):
            continue

        hits = []
        en_hit = longest_shared_run_en(summary.get("summary_en", ""), item.text)
        if en_hit:
            hits.append(f"EN: …{en_hit}…")
        zh_hit = longest_shared_run_zh(summary.get("summary_zh", ""), item.text)
        if zh_hit:
            hits.append(f"ZH: …{zh_hit}…")

        if hits:
            summary["_verbatim"] = hits
            log.warning("疑似照抄原文（%s）：%s", item.title[:40], " | ".join(hits))

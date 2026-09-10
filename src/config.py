"""Rookie-Recon 設定檔：訂閱來源、篩選權重、輸出參數。"""

# ---------------------------------------------------------------- 訂閱來源
# trust: 來源加權（1.0 = 一般，1.3 = 官方通報）
# region: "au" 的來源會額外加分（澳洲在地相關）
SOURCES = [
    # --- 官方通報 ---
    {
        "name": "CISA Advisories",
        "url": "https://www.cisa.gov/cybersecurity-advisories/all.xml",
        "lang": "en",
        "trust": 1.3,
    },
    {
        "name": "ACSC Alerts (AU)",
        "url": "https://www.cyber.gov.au/rss/news",
        "lang": "en",
        "trust": 1.3,
        "region": "au",
    },
    # --- 國際媒體 ---
    {
        "name": "The Hacker News",
        "url": "https://feeds.feedburner.com/TheHackersNews",
        "lang": "en",
        "trust": 1.0,
    },
    {
        "name": "BleepingComputer",
        "url": "https://www.bleepingcomputer.com/feed/",
        "lang": "en",
        "trust": 1.1,
    },
    {
        "name": "Krebs on Security",
        "url": "https://krebsonsecurity.com/feed/",
        "lang": "en",
        "trust": 1.2,
    },
    {
        "name": "The Record",
        "url": "https://therecord.media/feed",
        "lang": "en",
        "trust": 1.1,
    },
    # --- 中文來源（第一版先不納入，之後想加就把註解拿掉）---
    # {
    #     "name": "iThome 資安",
    #     "url": "https://www.ithome.com.tw/rss",
    #     "lang": "zh",
    #     "trust": 1.0,
    # },
    # {
    #     "name": "TWCERT/CC",
    #     "url": "https://www.twcert.org.tw/tw/rss-1.xml",
    #     "lang": "zh",
    #     "trust": 1.2,
    # },
]

# ---------------------------------------------------------------- 篩選權重
# 標題命中權重 3 倍，摘要命中權重 1 倍（見 rank.py）
KEYWORD_WEIGHTS = {
    # 高嚴重度訊號
    "zero-day": 5.0,
    "0-day": 5.0,
    "actively exploited": 5.0,
    "in the wild": 4.0,
    "unauthenticated": 3.5,
    "remote code execution": 3.5,
    "rce": 3.0,
    "privilege escalation": 2.5,
    "supply chain": 3.5,
    "backdoor": 3.0,
    # 事件類型
    "ransomware": 3.0,
    "data breach": 3.0,
    "extortion": 2.0,
    "phishing": 1.5,
    "malware": 1.5,
    "botnet": 1.5,
    "apt": 2.0,
    "state-sponsored": 2.5,
    # 修補與應對
    "patch tuesday": 3.5,
    "emergency patch": 4.0,
    "out-of-band": 3.0,
    "proof-of-concept": 2.0,
    "poc exploit": 3.0,
    # 常見高影響產品
    "fortinet": 2.0,
    "ivanti": 2.0,
    "citrix": 2.0,
    "vmware": 2.0,
    "microsoft exchange": 2.5,
    "active directory": 2.0,
    "windows": 1.0,
    "linux": 1.0,
    "cisco": 1.5,
    "sharepoint": 1.5,
    "openssh": 2.0,
    # 澳洲在地訊號
    "australia": 2.5,
    "australian": 2.5,
    "queensland": 2.0,
    "oaic": 2.0,
    "privacy act": 2.0,
    "essential eight": 2.5,
    "apra": 1.5,
    "soci act": 2.0,
    # 台灣訊號（雙語讀者可能也在意）
    "taiwan": 2.0,
}

# 出現這些字通常是業配、產品發表、募資新聞，直接扣分
NEGATIVE_KEYWORDS = {
    "webinar": -4.0,
    "sponsored": -6.0,
    "press release": -4.0,
    "series a": -3.0,
    "series b": -3.0,
    "funding round": -3.0,
    "acquires": -2.0,
    "announces partnership": -3.0,
    "magic quadrant": -3.0,
    "top 10 tools": -2.0,
}

REGION_BOOST = 3.0        # region == "au" 的來源加分
CVSS_HIGH_BOOST = 3.0     # CVSS >= 9.0
CVSS_MED_BOOST = 1.5      # CVSS 7.0 - 8.9
CVE_MENTION_BOOST = 1.0   # 有明確 CVE 編號

# ---------------------------------------------------------------- 輸出參數
LOOKBACK_DAYS = 7         # 抓取範圍
MAX_ITEMS = 10            # 最終送出的則數
MIN_SCORE = 2.0           # 低於此分數即使不足 MAX_ITEMS 也不送
MAX_PER_SOURCE = 3        # 單一來源最多幾則，避免被某家媒體洗版

# ---------------------------------------------------------------- LLM 供應商
# 用環境變數 LLM_PROVIDER 切換，預設 github。兩家都是 OpenAI 相容介面，
# 所以 summarize.py 只有一份程式碼。
#
#   github —— GitHub Models。跑在 Actions 裡直接用 runner 的 GITHUB_TOKEN，
#             不必申請任何 key。免費層約 10 RPM，單次請求上限 8K in / 4K out，
#             所以本專案採「一則新聞一次請求」而非整批送。
#   gemini —— Google AI Studio 免費層。需要 GEMINI_API_KEY（免信用卡）。
#             注意：免費層的輸入輸出可能被 Google 用於改進模型；
#             且該專案一旦啟用計費，免費額度會整個消失。
PROVIDERS = {
    "github": {
        "base_url": "https://models.github.ai/inference",
        "model": "openai/gpt-4.1-mini",
        "key_env": "GITHUB_TOKEN",
        "json_mode": True,
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-flash-latest",
        "key_env": "GEMINI_API_KEY",
        "json_mode": True,
    },
}

DEFAULT_PROVIDER = "github"

# 免費層速率限制：每則之間等待秒數（10 RPM → 7 秒安全）
REQUEST_INTERVAL = 7.0
REQUEST_TIMEOUT = 90

TIMEZONE = "Australia/Brisbane"

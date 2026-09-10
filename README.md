# Rookie-Recon

Welcome to Rookie Recon, we simply want to receive weekly cyber incidence report from many sites. Since I am from Taiwan, it provides English and Mandarin in one go.
自動彙整每週資安大事，用 AI 產生**中英雙語**摘要，每週一早上 8:00（布里斯本時間）推送到 Discord。

> Recon 取自 reconnaissance（偵察）。這個專案掃描的不是攻擊目標，而是公開的威脅情報來源。

## 運作流程

```
RSS 來源 ──► 規則式篩選 ──► LLM 雙語摘要 ──► Discord 單則訊息
(11 家)      關鍵字加權       一則一次請求        embed + fields
             去重、限量        照抄檢查           ↓
                                              archive/*.md 存檔
```

篩選刻意**不用 LLM**：規則式評分穩定、可解釋、零成本，而且每則入選理由都會記在存檔的 HTML 註解裡，方便你回頭調權重。

## 設定步驟

### 1. Discord Webhook

頻道 → 編輯頻道 → 整合 → Webhook → 建立 Webhook → 複製網址。

### 2. 加到 GitHub Secrets

Repo → Settings → Secrets and variables → Actions → New repository secret：

| Secret | 必要性 | 說明 |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | 必要 | 上一步複製的網址 |
| `GEMINI_API_KEY` | 選用 | 只有改用 Gemini 時才需要 |

**LLM 不需要任何 secret。** 預設用 GitHub Models，Actions runner 內建的 `GITHUB_TOKEN` 已帶 `models:read` 權限，workflow 裡已經宣告好了。

### 3. 檢查 RSS 來源還活著

RSS 網址會變，`config.py` 裡有幾個可能已經過期。先手動觸發一次檢查：

Actions → Weekly Digest → Run workflow → mode: `check-feeds`

把掛掉的來源從 `config.py` 刪掉或換掉。

### 4. 試跑

依序跑這三個模式，確認每一段都正常：

| mode | 做什麼 | 看什麼 |
|---|---|---|
| `dry-run` | 只抓取＋篩選，不呼叫 LLM | 入選的 9 則是不是你想看的新聞 |
| `preview` | 產生摘要並印出版面，不推送 | 摘要品質、中文是否通順、篇幅 |
| `full` | 完整流程並推送 Discord | 實際版面 |

## LLM 供應商

用環境變數 `LLM_PROVIDER` 切換，兩家都是 OpenAI 相容介面，所以只有一份程式碼。

**`github`（預設）** — GitHub Models。不需申請 key，免費層約 10 RPM，單次請求上限 8K in / 4K out。因為這個上限，本專案採「一則新聞一次請求」，每則間隔 7 秒，9 則約跑 1 分鐘。

**`gemini`** — Google AI Studio 免費層，需要 `GEMINI_API_KEY`（免信用卡）。上下文大得多。兩個注意事項：免費層的輸入輸出可能被 Google 用於改進模型；而且該 Google Cloud 專案一旦啟用計費，免費額度會整個消失，不是「超額才計費」。

想換模型或供應商，改 `config.py` 的 `PROVIDERS`。

## 本機測試

```bash
pip install -r requirements.txt
cp .env.example .env      # 填入實際值
set -a && source .env && set +a

python -m src.main --check-feeds   # 測來源
python -m src.main --dry-run -v    # 測篩選（不花額度）
python -m src.main --preview -v    # 測版面與摘要品質
python -m src.main -v              # 完整執行
```

## 調整口味

改 `src/config.py`：

| 參數 | 作用 |
|---|---|
| `SOURCES` | 增減 RSS 來源；`region: "au"` 會加分 |
| `KEYWORD_WEIGHTS` | 你在意什麼就加權重（標題命中算 3 倍） |
| `NEGATIVE_KEYWORDS` | 業配、募資新聞、產品發表扣分 |
| `MAX_ITEMS` / `MIN_SCORE` | 則數與門檻 |
| `MAX_PER_SOURCE` | 避免整份被一家媒體洗版 |

想加中文來源：`SOURCES` 裡的 iThome 與 TWCERT/CC 是註解掉的，取消註解即可（記得同時加回中文關鍵字）。

## 關於摘要與原文

摘要由 LLM 用自己的話重寫，不是轉貼原文，每則都附原始連結。`summarize.py` 另外做了機械檢查：英文連續 8 個單字、中文連續 15 個字與原文重複就標記出來，記在 log 與存檔裡等你人工確認。前幾週建議看一下 `archive/` 裡有沒有這種警示，如果常出現就要加強 prompt。

## 已知限制

- **Actions 排程會延遲**。尖峰時段可能晚幾十分鐘，這是 GitHub 的行為，不是 bug。要準點就得換 Cloudflare Workers Cron 或自架。
- **公開 repo 閒置 60 天排程會停用**。每週的存檔 commit 剛好會維持活躍。
- **免費層額度隨時可能變動**。若 LLM 呼叫開始失敗，先看 log 是 429（限流，等一下就好）還是 quota（當日額度用盡）。
- **來源全是英文媒體**，中文摘要是翻譯而非原生中文報導，台灣本地事件的覆蓋率會偏低。

## 專案結構

```
src/
  config.py     ← 幾乎所有調整都在這裡
  collect.py    RSS 抓取、去重、來源健康檢查
  rank.py       規則式評分與挑選
  summarize.py  LLM 雙語摘要 + 照抄檢查
  publish.py    Discord 版面與推送
  archive.py    markdown 存檔
  main.py       主流程與 CLI
archive/        每週存檔（自動 commit）
```

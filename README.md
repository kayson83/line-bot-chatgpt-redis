# LINE ChatGPT Redis Bot

這是一個使用 Flask 架設的 LINE Bot，整合 OpenAI GPT-4 與 Redis 對話記憶功能，並支援 Railway 快速部署。

## ✨ 功能特點

- 支援 GPT-3.5 / GPT-4 切換
- Redis 記憶每位用戶對話上下文
- 指令支援：`!reset`, `!help`
- 每位使用者每日 Token 使用上限控制
- Railway 一鍵部署

## 🚀 快速啟動

### 1. 設定環境變數 `.env`
請參考 `.env.example`

### 2. 安裝套件
```bash
pip install -r requirements.txt
```

### 3. 執行
```bash
python app.py
```

## 🏗️ Railway 部署

1. Fork 本 Repo
2. 登入 [Railway](https://railway.app/)
3. 新增專案 → Deploy from GitHub
4. 設定環境變數
5. 確認 `webhook` URL 貼到 LINE Bot 後台
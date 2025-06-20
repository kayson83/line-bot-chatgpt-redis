# line-bot-chatgpt-redis (LINE SDK v3 compatible)
# Flask + LINE Messaging API v3 + OpenAI GPT + Redis memory + Command support

import os
import openai
import redis
import json
from flask import Flask, request, abort
from datetime import datetime

from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import MessageEvent, TextMessage
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import MessagingApi, ApiClient
from linebot.v3.messaging.models import TextMessage as ReplyTextMessage, ReplyMessageRequest

# === Config ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
USE_GPT4 = os.getenv("USE_GPT4", "True") == "True"
MAX_TOKENS_PER_USER_PER_DAY = int(os.getenv("MAX_TOKENS_PER_USER_PER_DAY", 2000))
ENABLE_COMMANDS = os.getenv("ENABLE_COMMANDS", "True") == "True"

# Debug 環境變數載入（可移除）
#print("📦 DEBUG: LINE_CHANNEL_SECRET =", LINE_CHANNEL_SECRET)
#if not LINE_CHANNEL_SECRET:
#    raise RuntimeError("❌ 環境變數 LINE_CHANNEL_SECRET 未設定，請在 Railway 上加上！")

openai.api_key = OPENAI_API_KEY
redis_client = redis.from_url(REDIS_URL)

app = Flask(__name__)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# === Helper functions ===
def get_user_context(user_id):
    context = redis_client.get(f"context:{user_id}")
    return json.loads(context) if context else []

def update_user_context(user_id, messages):
    redis_client.setex(f"context:{user_id}", 3600, json.dumps(messages))

def reset_user_context(user_id):
    redis_client.delete(f"context:{user_id}")

def increment_token_usage(user_id, tokens):
    key = f"tokens:{user_id}:{get_date()}"
    redis_client.incrby(key, tokens)
    redis_client.expire(key, 86400)

def get_token_usage(user_id):
    return int(redis_client.get(f"tokens:{user_id}:{get_date()}") or 0)

def get_date():
    return datetime.utcnow().strftime("%Y-%m-%d")

# === Main ChatGPT handler ===
def chat_with_gpt(user_id, user_input):
    if ENABLE_COMMANDS and user_input.strip() == "!reset":
        reset_user_context(user_id)
        return "✅ 已重置對話歷史"
    if ENABLE_COMMANDS and user_input.strip() == "!help":
        return "🗨️ 請直接輸入問題，我會用 ChatGPT 回覆你！\n\n!reset 重設對話\n!help 顯示幫助"

    messages = get_user_context(user_id)
    messages.append({"role": "user", "content": user_input})

    model = "gpt-4" if USE_GPT4 else "gpt-3.5-turbo"

    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=messages,
            temperature=0.7
        )
        reply = response.choices[0].message.content
        total_tokens = response.usage.total_tokens

        if get_token_usage(user_id) + total_tokens > MAX_TOKENS_PER_USER_PER_DAY:
            return "⚠️ 今天已達使用上限，請明天再試。"

        increment_token_usage(user_id, total_tokens)
        messages.append({"role": "assistant", "content": reply})
        update_user_context(user_id, messages[-10:])
        return reply
    except Exception as e:
        print("OpenAI Error:", e)
        return "❌ 回覆時發生錯誤，請稍後再試。"

# === Flask endpoints ===
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(event=MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_input = event.message.text
    reply = chat_with_gpt(user_id, user_input)

    with ApiClient() as api_client:
        messaging_api = MessagingApi(api_client)
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[ReplyTextMessage(text=reply)]
            )
        )

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

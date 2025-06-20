import os
import openai
import redis
import json
from flask import Flask, request, abort
from datetime import datetime, timezone

from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import MessageEvent
from linebot.v3.messaging.models import TextMessage as IncomingTextMessage
from linebot.v3.messaging import MessagingApi, ApiClient, Configuration
from linebot.v3.messaging.models import TextMessage as ReplyTextMessage, ReplyMessageRequest
from linebot.v3.exceptions import InvalidSignatureError

# === Config ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
USE_GPT4 = os.getenv("USE_GPT4", "True") == "True"
MAX_TOKENS_PER_USER_PER_DAY = int(os.getenv("MAX_TOKENS_PER_USER_PER_DAY", 2000))
ENABLE_COMMANDS = os.getenv("ENABLE_COMMANDS", "True") == "True"

# Debug 環境變數檢查
print("📦 DEBUG: LINE_CHANNEL_SECRET =", LINE_CHANNEL_SECRET)
if not LINE_CHANNEL_SECRET:
    raise RuntimeError("❌ LINE_CHANNEL_SECRET 未設定")
if not LINE_CHANNEL_ACCESS_TOKEN:
    raise RuntimeError("❌ LINE_CHANNEL_ACCESS_TOKEN 未設定")

openai.api_key = OPENAI_API_KEY
redis_client = redis.from_url(REDIS_URL)

app = Flask(__name__)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)

# === Redis / Token 工具 ===
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
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

# === GPT 回覆邏輯 ===
def chat_with_gpt(user_id, user_input):
    print(f"🧠 chat_with_gpt(): user={user_id}, input={user_input}")

    if ENABLE_COMMANDS and user_input.strip() == "!reset":
        reset_user_context(user_id)
        return "✅ 已重置對話歷史"
    if ENABLE_COMMANDS and user_input.strip() == "!help":
        return "🗨️ 請輸入訊息與我聊天！\n!reset 重設\n!help 幫助"

    messages = get_user_context(user_id)
    messages.append({"role": "user", "content": user_input})
    model = "gpt-4" if USE_GPT4 else "gpt-3.5-turbo"

    try:
        response = openai.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7
        )
        reply = response.choices[0].message.content
        total_tokens = response.usage.total_tokens

        print(f"✅ GPT 回覆成功 (tokens: {total_tokens}) →\n{reply}")

        if get_token_usage(user_id) + total_tokens > MAX_TOKENS_PER_USER_PER_DAY:
            return "⚠️ 今日用量已達上限"

        increment_token_usage(user_id, total_tokens)
        messages.append({"role": "assistant", "content": reply})
        update_user_context(user_id, messages[-10:])
        return reply

    except Exception as e:
        print("❌ GPT API 錯誤：", e)
        return "❌ 無法取得回覆，請稍後再試"

# === LINE Webhook ===
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    print("📩 收到 LINE Webhook：", body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("❌ 簽章驗證失敗")
        abort(400)
    except Exception as e:
        import traceback
        print("❌ 處理訊息錯誤：", e)
        traceback.print_exc()
        abort(400)
    return 'OK'

@handler.add(event=MessageEvent, message=IncomingTextMessage)
def handle_message(event):
    print("📨 使用者訊息：", event.message.text)
    user_id = event.source.user_id
    user_input = event.message.text
    reply = chat_with_gpt(user_id, user_input)

    with ApiClient(configuration) as api_client:
        messaging_api = MessagingApi(api_client)
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[ReplyTextMessage(text=reply)]
            )
        )

# === Fallback handler（處理其他型別訊息）===
@handler.add(MessageEvent)
def fallback_message(event):
    print(f"⚠️ 未處理類型：{event.message.__class__.__name__}")

# === 健康檢查 ===
@app.route("/", methods=["GET"])
def index():
    return "✅ LINE Bot 正常運作中"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

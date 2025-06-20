# line-bot-chatgpt-redis (LINE SDK v3 compatible)
# Flask + LINE Messaging API v3 + OpenAI GPT + Redis memory + Command support

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

# Debug 環境變數載入（可移除）
print("\ud83d\udce6 DEBUG: LINE_CHANNEL_SECRET =", LINE_CHANNEL_SECRET)
if not LINE_CHANNEL_SECRET:
    raise RuntimeError("\u274c LINE_CHANNEL_SECRET \u672a\u8a2d\u5b9a\uff0c\u8acb\u5728 Railway \u4e0a\u52a0\u4e0a\uff01")
if not LINE_CHANNEL_ACCESS_TOKEN:
    raise RuntimeError("\u274c LINE_CHANNEL_ACCESS_TOKEN \u672a\u8a2d\u5b9a")

openai.api_key = OPENAI_API_KEY
redis_client = redis.from_url(REDIS_URL)

app = Flask(__name__)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)

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
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

# === Main ChatGPT handler ===
def chat_with_gpt(user_id, user_input):
    print(f"\ud83e\uddd0 chat_with_gpt(): user={user_id}, input={user_input}")

    if ENABLE_COMMANDS and user_input.strip() == "!reset":
        reset_user_context(user_id)
        return "\u2705 \u5df2\u91cd\u7f6e\u5c0d\u8a71\u6b77\u53f2"
    if ENABLE_COMMANDS and user_input.strip() == "!help":
        return "\ud83d\udd28 \u8acb\u76f4\u63a5\u8f38\u5165\u554f\u984c\uff0c\u6211\u6703\u7528 ChatGPT \u56de\u8986\u4f60\uff01\n\n!reset \u91cd\u8a2d\u5c0d\u8a71\n!help \u986f\u793a\u5e6b\u52a9"

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

        print(f"\u2705 GPT \u56de\u8986\u6210\u529f (tokens: {total_tokens}) \u2192\n{reply}")

        if get_token_usage(user_id) + total_tokens > MAX_TOKENS_PER_USER_PER_DAY:
            return "\u26a0\ufe0f \u4eca\u5929\u5df2\u9054\u4f7f\u7528\u4e0a\u9650\uff0c\u8acb\u660e\u5929\u518d\u8a66\u3002"

        increment_token_usage(user_id, total_tokens)
        messages.append({"role": "assistant", "content": reply})
        update_user_context(user_id, messages[-10:])
        return reply
    except Exception as e:
        print("\u274c OpenAI API \u767c\u751f\u932f\u8aa4:", e)
        return "\u274c \u56de\u8986\u6642\u767c\u751f\u932f\u8aa4\uff0c\u8acb\u7a0d\u5f8c\u518d\u8a66\u3002"

# === Flask endpoints ===
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    print("\ud83d\udce9 \u6536\u5230 LINE Webhook\uff1a", body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("\u274c InvalidSignatureError\uff1a\u7c3d\u7ae0\u9a57\u8b49\u5931\u6557")
        abort(400)
    except Exception as e:
        import traceback
        print("\u274c Webhook \u8655\u7406\u932f\u8aa4\uff1a", e)
        traceback.print_exc()
        abort(400)
    return 'OK'

@handler.add(MessageEvent)
def handle_all_messages(event):
    user_id = event.source.user_id
    message = getattr(event, "message", None)
    message_type = message.__class__.__name__ if message else "Unknown"

    print(f"\ud83d\udce5 \u6536\u5230\u8a0a\u606f\u985e\u578b\uff1a{message_type}")

    text = getattr(message, "text", None)
    reply = None

    if text:
        print("\ud83d\udce8 \u8655\u7406\u6587\u5b57\u8a0a\u606f\uff1a", text)
        reply = chat_with_gpt(user_id, text)
    elif message_type == "StickerMessage":
        reply = "\ud83d\ude04 \u6211\u9084\u4e0d\u6703\u7406\u89e3\u8cbc\u5716\uff0c\u4f46\u6211\u77e5\u9053\u4f60\u5f88\u6709\u8da3\uff01"
    elif message_type == "ImageMessage":
        reply = "\ud83d\uddbc\ufe0f \u6211\u73fe\u5728\u9084\u7121\u6cd5\u770b\u5716\uff0c\u4e5f\u8a31\u4ee5\u5f8c\u53ef\u4ee5\u5e6b\u4f60\u5206\u6790\uff01"
    else:
        reply = f"\u26a0\ufe0f \u672a\u652f\u63f4\u7684\u8a0a\u606f\u985e\u578b\uff1a{message_type}"

    with ApiClient(configuration) as api_client:
        messaging_api = MessagingApi(api_client)
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[ReplyTextMessage(text=reply)]
            )
        )

@app.route("/", methods=["GET"])
def index():
    return "\u2705 LINE Bot \u5df2\u90e8\u7f72\u6210\u529f\uff0c\u8acb\u901a\u904e LINE \u50b3\u8a0a\u6e2c\u8a66\u3002"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

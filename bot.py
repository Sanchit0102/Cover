import re
from io import BytesIO
from typing import Dict, Literal, TypedDict, Optional

import requests
from PIL import Image
from telegram import Update, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = "7016777070:AAFlFW1ELdwUP36MV0zCyy43Dlv9iHSz5HI"  

# ---------- TYPES / STATE ----------

class Cover(TypedDict):
    kind: Literal["file_id", "url"]
    value: str


# per-user saved cover (used for all upcoming videos)
cover_store: Dict[int, Cover] = {}

# per-user pending video waiting for a cover
pending_video: Dict[int, str] = {}

URL_RE = re.compile(r"https?://\S+")


# ---------- HELPERS ----------

def build_thumb_from_url(url: str) -> InputFile:
    """Download URL image in memory and convert to valid Telegram thumbnail."""
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    img = Image.open(BytesIO(resp.content)).convert("RGB")
    img.thumbnail((320, 320))
    bio = BytesIO()
    img.save(bio, format="JPEG", quality=85, optimize=True)
    bio.seek(0)
    return InputFile(bio, filename="thumb.jpg")


async def send_video_with_cover(
    chat_id: int,
    video_file_id: str,
    cover: Cover,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if cover["kind"] == "file_id":
        thumb = cover["value"]  # reuse telegram file
    else:
        thumb = build_thumb_from_url(cover["value"])

    await context.bot.send_video(
        chat_id=chat_id,
        video=video_file_id,   # same video file_id
        thumbnail=thumb,
        supports_streaming=True,
    )


def set_user_cover(user_id: int, cover: Cover) -> None:
    cover_store[user_id] = cover


def get_user_cover(user_id: int) -> Optional[Cover]:
    return cover_store.get(user_id)


# ---------- COMMAND HANDLERS ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Video Cover Bot\n\n"
        "1) Send a cover image (photo or direct image URL).\n"
        "2) Send any video (or forward one).\n"
        "Bot will re-send that video using your saved cover.\n\n"
        "Commands:\n"
        "/show_cover - show current saved cover\n"
        "/del_cover  - delete saved cover"
    )
    await update.message.reply_text(text)


async def show_cover(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    cover = get_user_cover(user_id)

    if not cover:
        await update.message.reply_text("No cover saved.")
        return

    if cover["kind"] == "file_id":
        await context.bot.send_photo(chat_id=chat_id, photo=cover["value"], caption="Saved cover")
    else:
        await context.bot.send_photo(chat_id=chat_id, photo=cover["value"], caption="Saved cover (URL)")


async def del_cover(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id in cover_store:
        cover_store.pop(user_id, None)
        await update.message.reply_text("Cover deleted.")
    else:
        await update.message.reply_text("No cover to delete.")


# ---------- MESSAGE HANDLERS ----------

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    user_id = msg.from_user.id
    chat_id = msg.chat_id

    video = msg.video
    video_id = video.file_id  # reuse from Telegram

    cover = get_user_cover(user_id)

    if cover:
        await msg.reply_text("Applying saved cover…")
        await send_video_with_cover(chat_id, video_id, cover, context)
    else:
        # wait for a cover for this video
        pending_video[user_id] = video_id
        await msg.reply_text("Video received. Send cover image (photo or direct image URL).")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    user_id = msg.from_user.id
    chat_id = msg.chat_id

    # largest size
    photo = msg.photo[-1]
    file_id = photo.file_id

    set_user_cover(user_id, {"kind": "file_id", "value": file_id})

    if user_id in pending_video:
        video_id = pending_video.pop(user_id)
        await msg.reply_text("Cover saved. Processing pending video…")
        await send_video_with_cover(chat_id, video_id, cover_store[user_id], context)
    else:
        await msg.reply_text("Cover saved. It will be used for your next videos.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    user_id = msg.from_user.id
    chat_id = msg.chat_id
    text = msg.text.strip()

    m = URL_RE.search(text)
    if not m:
        # ignore normal text
        return

    url = m.group(0)
    set_user_cover(user_id, {"kind": "url", "value": url})

    if user_id in pending_video:
        video_id = pending_video.pop(user_id)
        await msg.reply_text("Cover URL saved. Processing pending video…")
        await send_video_with_cover(chat_id, video_id, cover_store[user_id], context)
    else:
        await msg.reply_text("Cover URL saved. It will be used for your next videos.")


# ---------- MAIN ----------

def main() -> None:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("show_cover", show_cover))
    app.add_handler(CommandHandler("del_cover", del_cover))

    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

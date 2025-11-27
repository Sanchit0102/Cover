import os
import re
from typing import Dict, Literal, TypedDict, Optional

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------- CONFIG ----------------

BOT_TOKEN = os.environ["BOT_TOKEN"]          # set in Render env
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", "8000"))   # Render injects PORT


# ---------------- STATE ----------------

class Cover(TypedDict):
    kind: Literal["file_id", "url"]
    value: str


class PendingVideo(TypedDict):
    video_id: str
    caption: Optional[str]


cover_store: Dict[int, Cover] = {}          # user_id -> Cover
pending_video: Dict[int, PendingVideo] = {}  # user_id -> PendingVideo

URL_RE = re.compile(r"https?://\S+")


# ---------------- HELPERS ----------------

async def send_video_with_cover(
    chat_id: int,
    video_file_id: str,
    cover: Cover,
    caption: Optional[str],
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    # Bot API 8.3: use "cover" parameter; must be passed via api_kwargs in PTB
    cover_value = cover["value"]

    await context.bot.send_video(
        chat_id=chat_id,
        video=video_file_id,
        caption=caption,
        supports_streaming=True,
        api_kwargs={"cover": cover_value},
    )


def set_user_cover(user_id: int, cover: Cover) -> None:
    cover_store[user_id] = cover


def get_user_cover(user_id: int) -> Optional[Cover]:
    return cover_store.get(user_id)


# ---------------- COMMANDS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Video Cover Bot\n\n"
        "1) Send a cover image (photo or direct image URL).\n"
        "2) Send or forward any video.\n"
        "Bot will resend it using your saved cover and same caption.\n\n"
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

    await context.bot.send_photo(chat_id=chat_id, photo=cover["value"], caption="Saved cover")


async def del_cover(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id in cover_store:
        cover_store.pop(user_id, None)
        await update.message.reply_text("Cover deleted.")
    else:
        await update.message.reply_text("No cover to delete.")


# ---------------- MESSAGE HANDLERS ----------------

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    user_id = msg.from_user.id
    chat_id = msg.chat_id

    video = msg.video
    video_id = video.file_id
    caption = msg.caption_html or msg.caption  # keep caption (works for forwarded too)

    cover = get_user_cover(user_id)

    if cover:
        await msg.reply_text("Applying saved cover…")
        await send_video_with_cover(chat_id, video_id, cover, caption, context)
    else:
        # store video until user sends cover
        pending_video[user_id] = {"video_id": video_id, "caption": caption}
        await msg.reply_text("Video received. Send cover image (photo or direct image URL).")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    user_id = msg.from_user.id
    chat_id = msg.chat_id

    photo = msg.photo[-1]
    file_id = photo.file_id

    set_user_cover(user_id, {"kind": "file_id", "value": file_id})

    if user_id in pending_video:
        pv = pending_video.pop(user_id)
        await msg.reply_text("Cover saved. Processing pending video…")
        await send_video_with_cover(
            chat_id,
            pv["video_id"],
            cover_store[user_id],
            pv["caption"],
            context,
        )
    else:
        await msg.reply_text("Cover saved. It will be used for your next videos.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    user_id = msg.from_user.id
    chat_id = msg.chat_id
    text = msg.text.strip()

    m = URL_RE.search(text)
    if not m:
        return

    url = m.group(0)
    set_user_cover(user_id, {"kind": "url", "value": url})

    if user_id in pending_video:
        pv = pending_video.pop(user_id)
        await msg.reply_text("Cover URL saved. Processing pending video…")
        await send_video_with_cover(
            chat_id,
            pv["video_id"],
            cover_store[user_id],
            pv["caption"],
            context,
        )
    else:
        await msg.reply_text("Cover URL saved. It will be used for your next videos.")


# ---------------- MAIN / WEBHOOK ----------------

def main() -> None:
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("show_cover", show_cover))
    application.add_handler(CommandHandler("del_cover", del_cover))

    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    if RENDER_EXTERNAL_URL:
        path = BOT_TOKEN  # webhook path segment
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=path,
            webhook_url=f"{RENDER_EXTERNAL_URL}/{path}",
        )
    else:
        application.run_polling()


if __name__ == "__main__":
    main()

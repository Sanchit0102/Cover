import os
import re
from typing import Literal, TypedDict, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# ---------------- CONFIG ----------------

BOT_TOKEN = ""
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", "8000"))
URL_RE = re.compile(r"https?://\S+")
MONGO_URI = os.environ.get(
    "MONGO_URI",
    "",
)

# ---------------- DB ----------------

mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo["poster_change"]
users_col = db.users
pending_col = db.pending_videos

# ---------------- DB HELPERS (ALL ASYNC) ----------------

async def upsert_user(user):
    await users_col.update_one(
        {"_id": user.id},
        {
            "$set": {
                "username": user.username,
                "updated_at": datetime.now(timezone.utc),
            },
            "$setOnInsert": {
                "created_at": datetime.now(timezone.utc),
                "caption_style": "normal",
            },
        },
        upsert=True,
    )


async def set_caption_style(user_id: int, style: str):
    await users_col.update_one(
        {"_id": user_id},
        {"$set": {"caption_style": style}},
    )


async def get_caption_style(user_id: int) -> str:
    u = await users_col.find_one({"_id": user_id})
    return u.get("caption_style", "normal") if u else "normal"


async def set_user_cover(user_id: int, cover: dict):
    await users_col.update_one(
        {"_id": user_id},
        {"$set": {"cover": cover}},
        upsert=True,
    )


async def get_user_cover(user_id: int):
    u = await users_col.find_one({"_id": user_id})
    return u.get("cover") if u else None


async def delete_user_cover(user_id: int):
    await users_col.update_one(
        {"_id": user_id},
        {"$unset": {"cover": ""}},
    )


async def add_pending_video(user_id, chat_id, video_id, caption):
    await pending_col.insert_one(
        {
            "user_id": user_id,
            "chat_id": chat_id,
            "video_id": video_id,
            "caption": caption,
            "created_at": datetime.now(timezone.utc),
        }
    )


async def get_pending_videos(user_id):
    cursor = pending_col.find({"user_id": user_id}).sort("created_at", 1)
    return [doc async for doc in cursor]

# ---------------- TYPES ----------------

class Cover(TypedDict):
    kind: Literal["file_id", "url"]
    value: str

STYLE_WRAPPER = {
    "bold": "<b>{}</b>",
    "italic": "<i>{}</i>",
    "underline": "<u>{}</u>",
    "strike": "<s>{}</s>",
    "mono": "<code>{}</code>",
    "spoiler": "<tg-spoiler>{}</tg-spoiler>",
    "pre": "<pre>{}</pre>",
    "normal": "{}",
}

# ---------------- KEYBOARDS ----------------

HOME_BUTTON = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("Set Caption Style 📝", callback_data="open_style_menu")],
        [InlineKeyboardButton("Developer 👨🏻‍💻", url="https://t.me/THE_DS_OFFICIAL")],
    ]
)

BACK_BTN = InlineKeyboardMarkup(
    [[InlineKeyboardButton("⇽ Back To Caption Style", callback_data="back_caption")]]
)

STYLE_MENU = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("𝗕𝗼𝗹𝗱", callback_data="style:bold"),
            InlineKeyboardButton("𝐼𝑡𝑎𝑙𝑖𝑐", callback_data="style:italic"),
        ],
        [
            InlineKeyboardButton("U̲n̲d̲e̲r̲l̲i̲n̲e̲", callback_data="style:underline"),
            InlineKeyboardButton("S̶t̶r̶i̶k̶e̶", callback_data="style:strike"),
        ],
        [
            InlineKeyboardButton("Ｍｏｎｏ", callback_data="style:mono"),
            InlineKeyboardButton("▌Spoiler▐", callback_data="style:spoiler"),
        ],
        [
            InlineKeyboardButton("⟦ Pre ⟧", callback_data="style:pre"),
            InlineKeyboardButton("Normal", callback_data="style:normal"),
        ],
        [InlineKeyboardButton("⇽ Back To Home", callback_data="back_home")],
    ]
)

START_TEXT = (
    "<b>Hello, I'm Auto Video Thumbnail Change Bot</b>\n\n"
    "<b>📌 How To Use:</b>\n"
    "1) Send a photo or direct URL.\n"
    "2) Send or forward any video.\n\n"
    "<b>📌 Commands:</b>\n"
    "/show_cover - show current saved cover\n"
    "/del_cover  - delete saved cover"
)

# ---------------- HELPERS ----------------

async def send_video_with_cover(
    chat_id: int,
    video_file_id: str,
    cover: Cover,
    caption: Optional[str],
    context: ContextTypes.DEFAULT_TYPE,
):
    await context.bot.send_video(
        chat_id=chat_id,
        video=video_file_id,
        caption=caption,
        parse_mode="HTML",
        supports_streaming=True,
        api_kwargs={"cover": cover["value"]},
    )

# ---------------- COMMANDS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        START_TEXT,
        reply_markup=HOME_BUTTON,
        parse_mode="HTML",
    )


async def show_cover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cover = await get_user_cover(user_id)

    if not cover:
        await update.message.reply_text("No cover saved.")
        return

    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=cover["value"],
        caption="Saved cover",
    )


async def del_cover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_cover(update.effective_user.id)
    await update.message.reply_text("Cover deleted.")

# ---------------- CALLBACKS ----------------

async def style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await upsert_user(user)
    await query.answer()

    if query.data == "back_home":
        await query.message.edit_text(
            START_TEXT,
            reply_markup=HOME_BUTTON,
            parse_mode="HTML",
        )
        return

    if query.data in ("open_style_menu", "back_caption"):
        await query.message.edit_text(
            "<b>✍🏻 Select Caption Style</b>",
            reply_markup=STYLE_MENU,
            parse_mode="HTML",
        )
        return

    if query.data.startswith("style:"):
        style = query.data.split(":")[1]
        await set_caption_style(user.id, style)

        await query.message.edit_text(
            f"✅ Caption style set to <b>{style.upper()}</b>\n\nNow send your video 🎬",
            reply_markup=BACK_BTN,
            parse_mode="HTML",
        )

# ---------------- MESSAGE HANDLERS ----------------

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user
    await upsert_user(user)

    raw_caption = msg.caption_html or msg.caption or ""
    style = await get_caption_style(user.id)
    caption = STYLE_WRAPPER[style].format(raw_caption)

    cover = await get_user_cover(user.id)

    if cover:
        await send_video_with_cover(
            msg.chat_id,
            msg.video.file_id,
            cover,
            caption,
            context,
        )
    else:
        await add_pending_video(
            user.id,
            msg.chat_id,
            msg.video.file_id,
            caption,
        )
        await msg.reply_text("Video received. Send cover image (photo or direct image URL).")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user
    await upsert_user(user)

    cover = {"kind": "file_id", "value": msg.photo[-1].file_id}
    await set_user_cover(user.id, cover)

    pending = await get_pending_videos(user.id)

    if not pending:
        await msg.reply_text("Cover saved. It will be used for your next videos.")
        return

    await msg.reply_text("Cover saved. Processing pending videos...")

    for pv in pending:
        await send_video_with_cover(
            pv["chat_id"],
            pv["video_id"],
            cover,
            pv["caption"],
            context,
        )
        await pending_col.delete_one({"_id": pv["_id"]})


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user
    await upsert_user(user)

    m = URL_RE.search(msg.text or "")
    if not m:
        return

    cover = {"kind": "url", "value": m.group(0)}
    await set_user_cover(user.id, cover)

    pending = await get_pending_videos(user.id)

    if not pending:
        await msg.reply_text("Cover saved. It will be used for your next videos.")
        return

    await msg.reply_text("Cover saved. Processing pending videos...")

    for pv in pending:
        await send_video_with_cover(
            pv["chat_id"],
            pv["video_id"],
            cover,
            pv["caption"],
            context,
        )
        await pending_col.delete_one({"_id": pv["_id"]})

# ---------------- MAIN ----------------

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("show_cover", show_cover))
    application.add_handler(CommandHandler("del_cover", del_cover))

    application.add_handler(CallbackQueryHandler(style_callback))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    if RENDER_EXTERNAL_URL:
        path = BOT_TOKEN
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

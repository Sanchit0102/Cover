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

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", "8000"))
MONGO_URI = os.environ.get("MONGO_URI", "")

URL_RE = re.compile(r"https?://\S+|www\.\S+")
MENTION_RE = re.compile(r"@\w+")

mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo["poster_change"]
users_col = db.users
pending_col = db.pending_videos

# ---------------- DB HELPERS ----------------

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
                "url_filter": "off",
                "waiting_for_cover": False,
            },
        },
        upsert=True,
    )

async def set_url_filter(user_id: int, mode: str):
    await users_col.update_one(
        {"_id": user_id},
        {"$set": {"url_filter": mode}},
        upsert=True,
    )

async def get_url_filter(user_id: int) -> str:
    u = await users_col.find_one({"_id": user_id})
    return u.get("url_filter", "off") if u else "off"

async def is_waiting_for_cover(user_id: int) -> bool:
    u = await users_col.find_one({"_id": user_id})
    return u.get("waiting_for_cover", False) if u else False

async def set_waiting_for_cover(user_id: int, value: bool):
    await users_col.update_one(
        {"_id": user_id},
        {"$set": {"waiting_for_cover": value}},
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
    await pending_col.insert_one({
        "user_id": user_id,
        "chat_id": chat_id,
        "video_id": video_id,
        "caption": caption,
        "created_at": datetime.now(timezone.utc),
    })

async def get_pending_videos(user_id):
    cursor = pending_col.find({"user_id": user_id}).sort("created_at", 1)
    return [doc async for doc in cursor]

# ---------------- SANITIZER ----------------

def sanitize_caption(text: str, mode: str) -> str:
    if mode == "url":
        text = URL_RE.sub("", text)
    elif mode == "url_mention":
        text = URL_RE.sub("", text)
        text = MENTION_RE.sub("", text)
    return text.strip()

# ---------------- STATE ----------------

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
        [
            InlineKeyboardButton("URL & Mention Remover 🔗", callback_data="open_url_remover"),
        ],
        [
            InlineKeyboardButton("Caption Font 📝", callback_data="open_style_menu"),
        ],
        [
            InlineKeyboardButton("Developer 👨🏻‍💻", url="https://t.me/THE_DS_OFFICIAL")
        ]
    ]
)

def url_filter_menu(selected: str):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"Remove URLs Only {'✅' if selected == 'url' else ''}",
                    callback_data="filter:url",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"Remove URL + Mention {'✅' if selected == 'url_mention' else ''}",
                    callback_data="filter:url_mention",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"Disable / OFF {'✅' if selected == 'off' else ''}",
                    callback_data="filter:off",
                ),
            ],
            [
                InlineKeyboardButton("⇽ Back To Home", callback_data="back_home")
            ],
        ]
    )

STYLE_MENU = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("𝗕𝗼𝗹𝗱", callback_data="style:bold"),
            InlineKeyboardButton("𝐼𝑡𝑎𝑙𝑖𝑐", callback_data="style:italic"),
        ],
        [
            InlineKeyboardButton("U̲n̲d̲e̲r̲l̲i̲n̲e̲", callback_data="style:underline"),
            InlineKeyboardButton("S̶t̶r̶i̶k̶e̶" , callback_data="style:strike"),
        ],
        [
            InlineKeyboardButton("Ｍｏｎｏ", callback_data="style:mono"),
            InlineKeyboardButton("▌Spoiler▐", callback_data="style:spoiler"),
        ],
        [
            InlineKeyboardButton("⟦ Pre ⟧", callback_data="style:pre"),
            InlineKeyboardButton("Normal", callback_data="style:normal"),
        ],
        [
            InlineKeyboardButton("⇽ Back To Home", callback_data="back_home"),
        ],
    ]
)


BACK_BTN = InlineKeyboardMarkup(
    [[InlineKeyboardButton("⇽ Back To Caption Style", callback_data="back_caption")]]
)

# ---------------- TEXTS ----------------
START_TEXT = (
    "<b>Hello, I'm Auto Video Thumbnail Changer Bot</b>\n\n"
    "<b>📌 How To Use:</b>\n"
    "1) Send a photo or direct URL.\n"
    "2) Send or forward any video.\n\n"
    "<b>📌 Commands:</b>\n"
    "/show_cover - show current saved cover\n"
    "/del_cover  - delete saved cover"
    )
# ---------------- HELPERS ----------------

async def send_video_with_cover(chat_id, video_id, cover, caption, context):
    await context.bot.send_video(
        chat_id=chat_id,
        video=video_id,
        caption=caption,
        supports_streaming=True,
        parse_mode="HTML",
        api_kwargs={"cover": cover["value"]},
    )

# ---------------- COMMANDS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        START_TEXT, reply_markup=HOME_BUTTON, parse_mode="HTML"
    )

# ---------------- CALLBACKS ----------------

async def style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await upsert_user(query.from_user)
    await query.answer()

    if query.data == "back_home":
        await query.message.edit_text(
            START_TEXT, reply_markup=HOME_BUTTON, parse_mode="HTML"
        )
        return

    if query.data == "open_url_remover":
        mode = await get_url_filter(user_id)
        await query.message.edit_text(
            "<b>🔗 URL & Mention Filter</b>",
            reply_markup=url_filter_menu(mode),
            parse_mode="HTML",
        )
        return

    if query.data.startswith("filter:"):
        mode = query.data.split(":")[1]
        await set_url_filter(user_id, mode)

        await query.answer(
            {
                "url": "Remove URLs Only ✅",
                "url_mention": "Remove URL + Mention ✅",
                "off": "Disabled / OFF ✅",
            }[mode],
            show_alert=True,
        )

        await query.message.edit_reply_markup(
            reply_markup=url_filter_menu(mode)
        )
        return

    if query.data in ("open_style_menu", "back_caption"):
        style = await get_caption_style(user_id)
        await query.message.edit_text(
            "<b>✍🏻 Select Caption Style ✍🏻</b>\n\n"
            "<b>📝 Current Style:</b> <code>{}</code>".format(style.upper()),
            reply_markup=STYLE_MENU,
            parse_mode="HTML",
        )
        return

    if query.data.startswith("style:"):
        style = query.data.split(":")[1]
        await set_caption_style(user_id, style)
        await query.message.edit_text(
            f"✅ Caption style set to <b>{style.upper()}</b>\n\nnow you send your video 🎬", 
            reply_markup=BACK_BTN,
            parse_mode="HTML",
        )

# ---------------- MESSAGE HANDLERS ----------------

async def show_cover(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    cover = await get_user_cover(user_id)

    if not cover:
        await update.message.reply_text("No cover saved.")
        return

    await context.bot.send_photo(
        chat_id=chat_id,
        photo=cover["value"], 
        caption="Saved cover",
        )


async def del_cover(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await delete_user_cover(user_id)
    await update.message.reply_text("Cover deleted.")


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = msg.from_user.id
    await upsert_user(msg.from_user)

    raw = msg.caption_html or msg.caption or ""
    style = await get_caption_style(user_id)
    mode = await get_url_filter(user_id)

    raw = sanitize_caption(raw, mode)
    caption = STYLE_WRAPPER[style].format(raw)

    cover = await get_user_cover(user_id)

    if cover:
        await send_video_with_cover(
            msg.chat_id, msg.video.file_id, cover, caption, context
        )
    else:
        await add_pending_video(
            user_id, msg.chat_id, msg.video.file_id, caption
        )
        if not await is_waiting_for_cover(user_id):
            await msg.reply_text(
                "Video received. Send cover image (photo or direct image URL)."
            )
            await set_waiting_for_cover(user_id, True)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = msg.from_user.id
    await upsert_user(msg.from_user)

    cover = {"kind": "file_id", "value": msg.photo[-1].file_id}
    await set_user_cover(user_id, cover)
    await set_waiting_for_cover(user_id, False)

    pending = await get_pending_videos(user_id)

    if not pending:
        await msg.reply_text("Cover Saved. It will be used for your next videos.")
        return
    
    await msg.reply_text("Cover Saved. Processing pending videos...")

    for pv in pending:
        await send_video_with_cover(
            pv["chat_id"], pv["video_id"], cover, pv["caption"], context
        )
        await pending_col.delete_one({"_id": pv["_id"]})

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = msg.from_user.id
    await upsert_user(msg.from_user)

    m = URL_RE.search(msg.text or "")
    if not m:
        return

    cover = {"kind": "url", "value": m.group(0)}
    await set_user_cover(user_id, cover)
    await set_waiting_for_cover(user_id, False)

    pending = await get_pending_videos(user_id)

    if not pending:
        await msg.reply_text("Cover Saved. It will be used for your next videos.")
        return
    
    await msg.reply_text("Cover Saved. Processing pending videos...")

    for pv in pending:
        await send_video_with_cover(
            pv["chat_id"], pv["video_id"], cover, pv["caption"], context
        )
        await pending_col.delete_one({"_id": pv["_id"]})

# ---------------- MAIN ----------------

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("show_cover", show_cover))
    app.add_handler(CommandHandler("del_cover", del_cover))

    app.add_handler(CallbackQueryHandler(style_callback))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    if RENDER_EXTERNAL_URL:
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="webhook",
            webhook_url=f"{RENDER_EXTERNAL_URL}/webhook",
        )
    else:
        app.run_polling()

if __name__ == "__main__":
    main()

import os
import re
from typing import Dict, Literal, TypedDict, Optional

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

BOT_TOKEN = os.environ["BOT_TOKEN"]
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", "8000"))
URL_RE = re.compile(r"https?://\S+")

# ---------------- STATE ----------------

class Cover(TypedDict):
    kind: Literal["file_id", "url"]
    value: str


class PendingVideo(TypedDict):
    video_id: str
    caption: Optional[str]


cover_store: Dict[int, Cover] = {}
pending_video: Dict[int, PendingVideo] = {}

user_caption_style: Dict[int, str] = {}  # user_id -> style


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
            InlineKeyboardButton("Set Caption Style 📝", callback_data="open_style_menu")
        ],
        [
            InlineKeyboardButton("Developer 👨🏻‍💻", url="https://t.me/THE_DS_OFFICIAL")
        ]
    ]
)

BACK_BTN = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("⇽ Back To Caption Style", callback_data="back_caption")
         ]
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
) -> None:
    
    await context.bot.send_video(
        chat_id=chat_id,
        video=video_file_id,
        caption=caption,
        supports_streaming=True,
        parse_mode="HTML",
        api_kwargs={"cover": cover["value"]},
    )


def set_user_cover(user_id: int, cover: Cover) -> None:
    cover_store[user_id] = cover


def get_user_cover(user_id: int) -> Optional[Cover]:
    return cover_store.get(user_id)

# ---------------- COMMANDS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        START_TEXT, 
        reply_markup=HOME_BUTTON,
        parse_mode="HTML"
        )

# ---------------- CALLBACKS ----------------

async def style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id

    await query.answer()

    if query.data == "back_home":
        await query.message.edit_text(
            START_TEXT,
            reply_markup=HOME_BUTTON,
            parse_mode="HTML"
        )
        return

    if query.data == "open_style_menu" or query.data == "back_caption":
        await query.message.edit_text(
            "<b>✍🏻 Select Caption Style</b>",
            reply_markup=STYLE_MENU,
            parse_mode="HTML",
        )
        return

    if query.data.startswith("style:"):
        style = query.data.split(":")[1]
        user_caption_style[user_id] = style
        
        await query.message.edit_text(
            f"✅ Caption style set to <b>{style.upper()}</b>\n\nnow you send your video 🎬", 
            reply_markup=BACK_BTN,
            parse_mode="HTML"
            )


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

    video_id = msg.video.file_id
    raw_caption = msg.caption_html or msg.caption or ""

    style = user_caption_style.get(user_id, "normal")
    caption = STYLE_WRAPPER[style].format(raw_caption)

    cover = get_user_cover(user_id)

    if cover:
        # await msg.reply_text("Applying saved cover…")
        await send_video_with_cover(chat_id, video_id, cover, caption, context)
    else:
        pending_video[user_id] = {"video_id": video_id, "caption": caption}
        await msg.reply_text("Video received. Send cover image (photo or direct image URL).")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    user_id = msg.from_user.id
    chat_id = msg.chat_id

    file_id = msg.photo[-1].file_id
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

    m = URL_RE.search(msg.text or "")
    if not m:
        return

    set_user_cover(user_id, {"kind": "url", "value": m.group(0)})

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

# ---------------- MAIN ----------------

def main() -> None:
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

import logging
import os
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from PIL import Image

# ── Configuration ─────────────────────────────────────────────────────────────
TOKEN        = os.getenv("BOT_TOKEN")               # Set in your environment
CHANNEL_ID   = "-1004351773019"             # e.g. @mychannel or -1001234567890
CHANNEL_LINK = "https://t.me/+X2PkG878VR5iNDk9" # e.g. https://t.me/mychannel

# ── Conversation States ───────────────────────────────────────────────────────
WAITING_FOR_PHOTO = 1   # FIX: separate state for receiving the photo
WAITING_FOR_NAME  = 2   # state for receiving the desired filename

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ── /start ────────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()   # reset any previous session data
    keyboard = [
        [InlineKeyboardButton("Join Channel", url=CHANNEL_LINK)],
        [InlineKeyboardButton("Verify ✅", callback_data="verify")],
    ]
    await update.message.reply_text(
        "Welcome! Please join our channel first, then click Verify to start.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ConversationHandler.END


# ── Verify callback ───────────────────────────────────────────────────────────
async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()        # FIX: always acknowledge the callback immediately

    user_id = query.from_user.id

    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL_ID, user_id=user_id
        )
        if member.status in ("member", "administrator", "creator"):
            await query.edit_message_text(
                "✅ Verified! Please send me the image you want to convert to PDF."
            )
            return WAITING_FOR_PHOTO   # FIX: go to photo state, not name state

        else:
            # FIX: answer() was already called above — use edit instead of a
            #      second answer() call (which would be ignored or raise an error)
            await query.edit_message_text(
                "❌ You haven't joined the channel yet!\n\n"
                "Please join and then click Verify again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Join Channel", url=CHANNEL_LINK)],
                    [InlineKeyboardButton("Verify ✅", callback_data="verify")],
                ]),
            )
            return ConversationHandler.END

    except Exception as e:
        logger.error("Membership check failed: %s", e)
        await query.edit_message_text(
            "⚠️ Could not verify membership. "
            "Please make sure the bot is an admin in the channel and try again."
        )
        return ConversationHandler.END


# ── Receive photo ─────────────────────────────────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    photo_file = await update.message.photo[-1].get_file()

    image_bytes = io.BytesIO()
    await photo_file.download_to_memory(out=image_bytes)
    image_bytes.seek(0)         # FIX: rewind so PIL can read from the start

    # FIX: validate the image is readable before asking for a filename
    try:
        Image.open(image_bytes).verify()   # verify() checks integrity
        image_bytes.seek(0)                # rewind again after verify()
    except Exception as e:
        logger.error("Invalid image: %s", e)
        await update.message.reply_text(
            "⚠️ Could not read the image. Please send a valid photo and try again."
        )
        return WAITING_FOR_PHOTO

    context.user_data["image_bytes"] = image_bytes
    await update.message.reply_text(
        "✅ Image received! Now reply with the filename (e.g. my_file.pdf)."
    )
    return WAITING_FOR_NAME


# ── Convert & send PDF ────────────────────────────────────────────────────────
async def convert_to_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    filename = update.message.text.strip()

    if not filename.endswith(".pdf"):
        await update.message.reply_text(
            "⚠️ The filename must end with .pdf — please try again."
        )
        return WAITING_FOR_NAME

    # FIX: guard against missing image data
    image_bytes = context.user_data.get("image_bytes")
    if image_bytes is None:
        await update.message.reply_text(
            "⚠️ No image found. Please send /start and try again."
        )
        return ConversationHandler.END

    try:
        image_bytes.seek(0)     # FIX: always rewind before opening with PIL
        image = Image.open(image_bytes)

        pdf_bytes = io.BytesIO()
        image.convert("RGB").save(pdf_bytes, format="PDF")
        pdf_bytes.seek(0)       # FIX: rewind before sending

        await update.message.reply_document(
            document=pdf_bytes,
            filename=filename,
            caption=f"Here is your PDF: {filename}",
        )

    except Exception as e:
        logger.error("PDF conversion failed: %s", e)
        await update.message.reply_text(
            "⚠️ Conversion failed. Please send /start and try again."
        )
        return ConversationHandler.END

    finally:
        context.user_data.clear()   # FIX: always clean up memory

    return ConversationHandler.END


# ── Bot setup ─────────────────────────────────────────────────────────────────
def main() -> None:
    # FIX: guard against missing token at startup
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set.")

    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            # FIX: anchored pattern so "verify_something" won't accidentally match
            CallbackQueryHandler(verify, pattern="^verify$"),
        ],
        states={
            WAITING_FOR_PHOTO: [
                MessageHandler(filters.PHOTO, handle_photo),
            ],
            WAITING_FOR_NAME: [
                # FIX: allow user to re-send a photo if they changed their mind
                MessageHandler(filters.PHOTO, handle_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, convert_to_pdf),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        # FIX: allow the verify button to re-enter the conversation if it ended
        allow_reentry=True,
    )

    app.add_handler(conv_handler)
    app.run_polling()


if __name__ == "__main__":
    main()

# ── Receive photo ─────────────────────────────────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    photo_file = await update.message.photo[-1].get_file()
    path = f"{update.message.from_user.id}.jpg"
    await photo_file.download_to_drive(path)
    context.user_data["photo_path"] = path
    await update.message.reply_text(
        "Image saved! Now send the filename you want (must end in .pdf)."
    )
    return WAITING_FOR_NAME     # FIX: use the correct, distinct state constant


# ── Convert & send PDF ────────────────────────────────────────────────────────
async def convert_to_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    filename = update.message.text.strip()

    if not filename.endswith(".pdf"):
        await update.message.reply_text("Please provide a filename ending in '.pdf'.")
        return WAITING_FOR_NAME

    # FIX: guard against missing photo (e.g. user skipped the photo step)
    photo_path = context.user_data.get("photo_path")
    if not photo_path or not os.path.exists(photo_path):
        await update.message.reply_text(
            "No image found. Please send your image first."
        )
        return WAITING_FOR_NAME

    try:
        image = Image.open(photo_path)
        image.convert("RGB").save(filename)

        with open(filename, "rb") as pdf_file:
            await update.message.reply_document(document=pdf_file)

    except Exception as e:
        logger.error("Conversion error: %s", e)
        await update.message.reply_text(
            "Something went wrong during conversion. Please try again."
        )
        return WAITING_FOR_NAME

    finally:
        # FIX: cleanup runs even if an exception was raised
        for f in (photo_path, filename):
            if f and os.path.exists(f):
                os.remove(f)
        context.user_data.pop("photo_path", None)

    return ConversationHandler.END


# ── Bot setup ─────────────────────────────────────────────────────────────────
def main() -> None:
    token = "YOUR_BOT_TOKEN_HERE"   # Replace with your bot token
    app = Application.builder().token(token).build()

    conv_handler = ConversationHandler(
        # FIX: verify callback is an entry_point so it can start the conversation
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(verify, pattern="^verify$"),
        ],
        states={
            WAITING_FOR_PHOTO: [
                MessageHandler(filters.PHOTO, handle_photo),
            ],
            WAITING_FOR_NAME: [
                MessageHandler(filters.PHOTO, handle_photo),   # allow re-send
                MessageHandler(filters.TEXT & ~filters.COMMAND, convert_to_pdf),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(conv_handler)
    # FIX: removed the stray top-level CallbackQueryHandler(verify) — it is
    #      now correctly handled inside the ConversationHandler above.
    app.run_polling()


if __name__ == "__main__":
    main()
  

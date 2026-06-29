import logging
import os
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from PIL import Image

TOKEN        = os.getenv("BOT_TOKEN")
CHANNEL_ID   = os.getenv("CHANNEL_ID")
CHANNEL_LINK = os.getenv("CHANNEL_LINK")

WAITING_FOR_PHOTO = 1
WAITING_FOR_NAME  = 2

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("📢 Join Updates Channel", url=CHANNEL_LINK)],
        [InlineKeyboardButton("Verify ✅", callback_data="verify")],
    ]
    await update.message.reply_text(
        "👋 *Welcome!*\n\n"
        "To use this bot, you must join our updates channel first.\n\n"
        "1️⃣ Click *Join Updates Channel*\n"
        "2️⃣ Click *Verify ✅* once you've joined",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ConversationHandler.END


async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    try:
        member = await context.bot.get_chat_member(
            chat_id=int(CHANNEL_ID), user_id=user_id
        )

        if member.status in ("member", "administrator", "creator"):
            await query.edit_message_text(
                "✅ *Verified! You're all set.*\n\n"
                "📸 Send me any image you want to convert into a PDF.",
                parse_mode="Markdown",
            )
            return WAITING_FOR_PHOTO

        else:
            keyboard = [
                [InlineKeyboardButton("📢 Join Updates Channel", url=CHANNEL_LINK)],
                [InlineKeyboardButton("Verify ✅", callback_data="verify")],
            ]
            await query.edit_message_text(
                "❌ *You haven't joined the channel yet!*\n\n"
                "Please join first, then click Verify ✅",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return ConversationHandler.END

    except Exception as e:
        logger.error("Membership check error: %s", e)
        await query.edit_message_text(
            "⚠️ *Verification failed.*\n\n"
            "Make sure the bot is added as an *admin* in the channel.\n"
            "Send /start to retry.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    photo_file = await update.message.photo[-1].get_file()

    image_bytes = io.BytesIO()
    await photo_file.download_to_memory(out=image_bytes)
    image_bytes.seek(0)

    try:
        img = Image.open(image_bytes)
        img.verify()
        image_bytes.seek(0)
    except Exception as e:
        logger.error("Invalid image: %s", e)
        await update.message.reply_text(
            "⚠️ Could not read that image. Please send a valid photo."
        )
        return WAITING_FOR_PHOTO

    context.user_data["image_bytes"] = image_bytes
    await update.message.reply_text(
        "✅ *Image received!*\n\n"
        "📝 Now send me the filename for your PDF.\n"
        "Example: `my_document.pdf`\n\n"
        "_(The name must end with `.pdf`)_",
        parse_mode="Markdown",
    )
    return WAITING_FOR_NAME


async def no_photo_yet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📸 Please send an *image* first, then I'll ask for the filename.",
        parse_mode="Markdown",
    )
    return WAITING_FOR_PHOTO


async def convert_to_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    filename = update.message.text.strip()

    if not filename.endswith(".pdf"):
        await update.message.reply_text(
            "⚠️ The filename must end with `.pdf`\n\n"
            "Please try again. Example: `my_photo.pdf`",
            parse_mode="Markdown",
        )
        return WAITING_FOR_NAME

    image_bytes = context.user_data.get("image_bytes")
    if image_bytes is None:
        await update.message.reply_text(
            "⚠️ No image found. Please send /start and try again."
        )
        return ConversationHandler.END

    await update.message.reply_text("⏳ Converting your image to PDF...")

    try:
        image_bytes.seek(0)
        image = Image.open(image_bytes)

        pdf_bytes = io.BytesIO()
        image.convert("RGB").save(pdf_bytes, format="PDF")
        pdf_bytes.seek(0)

        await update.message.reply_document(
            document=pdf_bytes,
            filename=filename,
            caption=f"✅ Here is your PDF: *{filename}*",
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error("PDF conversion failed: %s", e)
        await update.message.reply_text(
            "⚠️ Conversion failed. Please send /start and try again."
        )
        return ConversationHandler.END

    finally:
        context.user_data.clear()

    await update.message.reply_text(
        "🎉 *Done!* Send /start anytime to convert another image.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Cancelled. Send /start whenever you want to convert an image."
    )
    return ConversationHandler.END


def main() -> None:
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set.")
    if not CHANNEL_ID:
        raise RuntimeError("CHANNEL_ID environment variable is not set.")
    if not CHANNEL_LINK:
        raise RuntimeError("CHANNEL_LINK environment variable is not set.")

    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(verify, pattern="^verify$"),
        ],
        states={
            WAITING_FOR_PHOTO: [
                MessageHandler(filters.PHOTO, handle_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, no_photo_yet),
            ],
            WAITING_FOR_NAME: [
                MessageHandler(filters.PHOTO, handle_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, convert_to_pdf),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("cancel", cancel),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)
    logger.info("✅ Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()

import asyncio
import sqlite3
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from logger import get_logger
import db
import db_commercial as db_tma

logger = get_logger("legit_check_bot")

ADMIN_ID = 913862074

# Таблица для отслеживания ответов: admin_msg_id -> user_chat_id
# Чтобы бот знал, кому отвечать, когда админ делает "Reply"
def init_legit_db():
    conn = sqlite3.connect("vinted_notifications.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS legit_check_requests (
            admin_msg_id INTEGER PRIMARY KEY,
            user_chat_id INTEGER NOT NULL,
            timestamp INTEGER
        )
    """)
    conn.commit()
    conn.close()

def get_user_sub_info(chat_id):
    conn = sqlite3.connect("vinted_notifications.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, subscription_expiry, subscription_type FROM users WHERE telegram_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user_sub_info(chat_id)
    
    if not user:
        await update.message.reply_text("❌ Вы не зарегистрированы в основном боте. Пожалуйста, запустите основной бот сначала.")
        return

    status = db_tma.get_user_status(user['id'])
    if "Legit" not in status:
        await update.message.reply_text("❌ У вас нет активной подписки <b>Bot + Legit Check</b>.\n\nПожалуйста, приобретите её в основном боте.", parse_mode='HTML')
        return
        
    if "Expired" in status:
        await update.message.reply_text("❌ Ваша подписка истекла. Пожалуйста, продлите её в основном боте.")
        return

    await update.message.reply_text(
        "👋 <b>Добро пожаловать в сервис Legit Check!</b>\n\n"
        "Присылайте сюда фотографии вещей, которые хотите проверить. "
        "Администратор рассмотрит их и ответит вам прямо в этот чат.", 
        parse_mode='HTML'
    )

async def handle_legit_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # 1. Если пишет админ (ответ на запрос)
    if chat_id == ADMIN_ID and update.message.reply_to_message:
        reply_to = update.message.reply_to_message.message_id
        conn = sqlite3.connect("vinted_notifications.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_chat_id FROM legit_check_requests WHERE admin_msg_id = ?", (reply_to,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            target_user_id = row[0]
            try:
                # Пересылаем ответ админа пользователю
                await context.bot.copy_message(
                    chat_id=target_user_id,
                    from_chat_id=ADMIN_ID,
                    message_id=update.message.message_id
                )
                await update.message.reply_text(f"✅ Ответ отправлен пользователю <code>{target_user_id}</code>.", parse_mode='HTML')
            except Exception as e:
                await update.message.reply_text(f"❌ Не удалось отправить ответ: {e}")
        else:
            await update.message.reply_text("❓ Не могу найти пользователя для этого сообщения (возможно, оно было переслано не через этого бота).")
        return

    # 2. Если пишет обычный пользователь (запрос на легит чек)
    user = get_user_sub_info(chat_id)
    if not user or "Legit" not in db_tma.get_user_status(user['id']):
        await update.message.reply_text("❌ У вас нет активной подписки <b>Bot + Legit Check</b>.", parse_mode='HTML')
        return

    # Пересылаем сообщение админу
    username = f"@{update.effective_user.username}" if update.effective_user.username else "No Username"
    info_msg = await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📥 <b>Новый запрос на Legit Check!</b>\nОт: {username} (<code>{chat_id}</code>)",
        parse_mode='HTML'
    )
    
    # Копируем само сообщение пользователя
    admin_copy = await context.bot.copy_message(
        chat_id=ADMIN_ID,
        from_chat_id=chat_id,
        message_id=update.message.message_id
    )
    
    # Сохраняем связь: ID сообщения у админа -> ID чата пользователя
    conn = sqlite3.connect("vinted_notifications.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO legit_check_requests (admin_msg_id, user_chat_id, timestamp) VALUES (?, ?, ?)", 
                   (admin_copy.message_id, chat_id, int(time.time())))
    conn.commit()
    conn.close()
    
    await update.message.reply_text("✅ Ваши данные отправлены на проверку. Ожидайте ответа администратора.")

def main():
    init_legit_db()
    token = db.get_parameter('legit_check_token')
    
    if not token or token == "ВАШ_ТОКЕН_ЗДЕСЬ":
        print("❌ ОШИБКА: Не установлен токен для Legit Check бота в базе данных (параметр 'legit_check_token')")
        return

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_legit_message))

    print("🚀 Бот Legit Check запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()

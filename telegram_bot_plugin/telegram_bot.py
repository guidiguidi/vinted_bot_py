# telegram_bot_plugin/telegram_bot.py - INTEGRATED LEGIT CHECK VERSION
import asyncio
import telegram
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.error import BadRequest
from logger import get_logger
import db
import core
import db_commercial as db_tma
import multiprocessing
import signal
import os
from datetime import datetime
import time
from proxies import get_dataimpulse_usage_status, reset_proxy_cache

logger = get_logger(__name__)
shutdown_event = asyncio.Event()

ADMIN_ID = 525127130 # Твой ID для легит-чеков

# Состояния FSM
STATE_WAITING_FOR_QUERY = "WAITING_FOR_QUERY"
STATE_ADMIN_EDIT_PARAM = "ADMIN_EDIT_PARAM"
STATE_WAITING_FOR_KEY = "WAITING_FOR_KEY"
STATE_ADMIN_BROADCAST_TEXT = "ADMIN_BROADCAST_TEXT"
STATE_ADMIN_SEARCH_USER = "ADMIN_SEARCH_USER"
STATE_ADMIN_ADD_SUB_DAYS = "ADMIN_ADD_SUB_DAYS"
STATE_WAITING_FOR_QUERY_RENAME = "WAITING_FOR_QUERY_RENAME"
STATE_ADMIN_ADD_COUNTRY = "ADMIN_ADD_COUNTRY"
STATE_ADMIN_REMOVE_COUNTRY = "ADMIN_REMOVE_COUNTRY"

# Новые состояния для прокси
STATE_ADMIN_SET_PROXY_LIST = "ADMIN_SET_PROXY_LIST"
STATE_ADMIN_SET_PROXY_LINK = "ADMIN_SET_PROXY_LINK"

# Состояния Legit Check
STATE_LEGIT_SEND_PHOTOS = "LEGIT_SEND_PHOTOS"

# --- КЛАВИАТУРЫ ---

MAIN_MENU_TEXTS = {
    "➕ Добавить запрос",
    "📄 Мои запросы",
    "📊 Статус",
    "💳 Оплатить подписку",
    "🔍 Legit Check",
    "🆘 Тех. поддержка",
    "🛠 Админ-панель",
}

def main_menu_kb(chat_id: int) -> ReplyKeyboardMarkup:
    user = db_tma.get_or_create_user(chat_id)
    status = db_tma.get_user_status(user['id'])
    is_admin = db_tma.is_admin(chat_id)
    
    buttons = [
        [KeyboardButton(text="➕ Добавить запрос"), KeyboardButton(text="📄 Мои запросы")],
        [KeyboardButton(text="📊 Статус"), KeyboardButton(text="💳 Оплатить подписку")]
    ]
    
    # Кнопка Legit Check только для тех, у кого есть доступ
    if "Legit" in status:
        buttons.append([KeyboardButton(text="🔍 Legit Check")])
        
    buttons.append([KeyboardButton(text="🆘 Тех. поддержка")])
    
    if is_admin:
        buttons.append([KeyboardButton(text="🛠 Админ-панель")])
        
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def legit_brands_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("Balenciaga", callback_data="legit_brand_Balenciaga"),
         InlineKeyboardButton("Vetements", callback_data="legit_brand_Vetements")],
        [InlineKeyboardButton("Chrome Hearts", callback_data="legit_brand_Chrome Hearts"),
         InlineKeyboardButton("Rick Owens", callback_data="legit_brand_Rick Owens")],
        [InlineKeyboardButton("❌ Отмена", callback_data="legit_cancel")]
    ])

def admin_hub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("📊 Статистика", callback_data="adm_stats"),
         InlineKeyboardButton("👥 Пользователи", callback_data="adm_users_menu")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="adm_settings"),
         InlineKeyboardButton("🌍 Страны", callback_data="adm_countries")],
        [InlineKeyboardButton("📢 Рассылка", callback_data="adm_broadcast"),
         InlineKeyboardButton("📜 Логи", callback_data="adm_logs")],
        [InlineKeyboardButton("⬅️ Закрыть", callback_data="adm_close")]
    ])

def admin_settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🤖 Скрейпер", callback_data="set_scraper"),
         InlineKeyboardButton("🌐 Прокси", callback_data="set_proxies")],
        [InlineKeyboardButton("💰 Платежи", callback_data="set_payments"),
         InlineKeyboardButton("🔑 Генерировать ключ", callback_data="adm_gen_key")],
        [InlineKeyboardButton("🧹 Очистить базу товаров", callback_data="adm_clear_items_confirm")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_main")]
    ])

def admin_users_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🔍 Поиск юзера", callback_data="adm_search_user")],
        [InlineKeyboardButton("📜 Список (Топ 10)", callback_data="adm_list_users")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_main")]
    ])


def _mask_token(raw_token: str) -> str:
    if not raw_token:
        return "не задан"
    if len(raw_token) <= 8:
        return "*" * len(raw_token)
    return f"{raw_token[:4]}...{raw_token[-4:]}"


def _build_proxy_settings_text() -> str:
    p_list = db.get_parameter('proxy_list') or "Пусто"
    p_link = db.get_parameter('proxy_list_link') or "Пусто"
    p_check = db.get_parameter('check_proxies') or "False"
    token = db.get_parameter('dataimpulse_api_token') or ""
    plan_mb = db.get_parameter('dataimpulse_plan_mb') or "0"

    usage = get_dataimpulse_usage_status()
    if usage.get("ok"):
        used_mb = usage.get("used_mb", 0)
        remaining_mb = usage.get("remaining_mb")
        plan_value = usage.get("plan_mb")
        if remaining_mb is None:
            usage_line = f"📦 Трафик (месяц): <b>{used_mb} MB</b> использовано"
        elif plan_value:
            usage_line = f"📦 Трафик (месяц): <b>{used_mb} / {plan_value} MB</b> | Осталось: <b>{remaining_mb} MB</b>"
        else:
            usage_line = f"📦 Трафик (месяц): <b>{used_mb} MB</b> | Осталось: <b>{remaining_mb} MB</b>"
    else:
        usage_line = f"📦 Трафик: <i>{usage.get('error', 'нет данных')}</i>"

    return (
        "🌐 <b>Настройки прокси</b>\n\n"
        f"📜 Список: <code>{p_list[:50]}...</code>\n"
        f"🔗 Ссылка: <code>{p_link}</code>\n"
        f"✅ Проверка: <b>{p_check}</b>\n"
        f"🔑 DataImpulse token: <code>{_mask_token(token)}</code>\n"
        f"📏 Лимит плана (MB): <b>{plan_mb}</b>\n"
        f"{usage_line}"
    )


def _build_proxy_settings_kb(p_check: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Установить список", callback_data="adm_proxy_set_list")],
        [InlineKeyboardButton("🔗 Установить ссылку", callback_data="adm_proxy_set_link")],
        [InlineKeyboardButton("🔑 DataImpulse token", callback_data="edt_param_dataimpulse_api_token")],
        [InlineKeyboardButton("📏 Лимит MB", callback_data="edt_param_dataimpulse_plan_mb")],
        [InlineKeyboardButton(f"🔄 Проверка: {p_check}", callback_data="adm_proxy_toggle_check")],
        [InlineKeyboardButton("🛑 Выключить прокси", callback_data="adm_proxy_disable")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="adm_settings")]
    ])


def _build_countries_text() -> str:
    countries = db.get_allowlist()
    if countries == 0:
        countries_text = "Пусто"
    else:
        countries_text = ", ".join(sorted(countries))
    return (
        "🌍 <b>Управление странами</b>\n\n"
        "Фильтр работает по стране продавца.\n"
        f"Текущий allowlist: <code>{countries_text}</code>"
    )


def _build_countries_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить страну", callback_data="adm_country_add")],
        [InlineKeyboardButton("➖ Удалить страну", callback_data="adm_country_remove")],
        [InlineKeyboardButton("🧹 Очистить список", callback_data="adm_country_clear")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin_main")]
    ])


def _build_payments_text() -> str:
    crypto_price = db_tma.get_setting('crypto_price_usdt') or "5.0"
    legit_price = db_tma.get_setting('crypto_price_bot_legit_usdt') or "10.0"
    referral_days = db_tma.get_setting('referral_reward_days') or "5"
    token = db_tma.get_setting('crypto_token') or ""
    token_masked = _mask_token(token)
    return (
        "💰 <b>Настройки платежей</b>\n\n"
        f"🤖 Цена Basic (USDT): <b>{crypto_price}</b>\n"
        f"🧷 Цена Bot+Legit (USDT): <b>{legit_price}</b>\n"
        f"🎁 Referral reward (days): <b>{referral_days}</b>\n"
        f"🔑 Crypto token: <code>{token_masked}</code>"
    )


def _build_payments_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Цена Basic", callback_data="edt_cparam_crypto_price_usdt")],
        [InlineKeyboardButton("🧷 Цена Bot+Legit", callback_data="edt_cparam_crypto_price_bot_legit_usdt")],
        [InlineKeyboardButton("🎁 Referral days", callback_data="edt_cparam_referral_reward_days")],
        [InlineKeyboardButton("🔑 Crypto token", callback_data="edt_cparam_crypto_token")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="adm_settings")]
    ])


async def safe_edit_message(query, text, reply_markup=None, parse_mode='HTML'):
    """
    Telegram raises BadRequest when edit payload is identical.
    Ignore that case to keep callback flow stable.
    """
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            await query.answer("Без изменений")
            return
        raise


def _validate_admin_param_value(param_key: str, raw_value: str):
    int_positive_keys = {"query_refresh_delay", "items_per_query", "referral_reward_days"}
    number_non_negative_keys = {"dataimpulse_plan_mb"}
    float_positive_keys = {"crypto_price_usdt", "crypto_price_bot_legit_usdt"}

    value = raw_value.strip()
    if not value:
        return False, "Значение не может быть пустым."

    if param_key in int_positive_keys:
        try:
            parsed = int(value)
            if parsed <= 0:
                return False, "Нужно число больше 0."
            return True, str(parsed)
        except ValueError:
            return False, "Нужно целое число."

    if param_key in number_non_negative_keys:
        try:
            parsed = float(value.replace(",", "."))
            if parsed < 0:
                return False, "Значение не может быть отрицательным."
            normalized = str(int(parsed)) if parsed.is_integer() else str(parsed)
            return True, normalized
        except ValueError:
            return False, "Нужно число (например: 51200)."

    if param_key in float_positive_keys:
        try:
            parsed = float(value.replace(",", "."))
            if parsed <= 0:
                return False, "Нужно число больше 0."
            return True, str(parsed)
        except ValueError:
            return False, "Нужно число (например: 5.0)."

    return True, value

# --- ОБРАБОТЧИКИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE, authorized_chat_ids: set):
    chat_id = update.effective_chat.id
    authorized_chat_ids.add(chat_id)
    db_tma.get_or_create_user(chat_id, update.effective_user.username)
    await update.message.reply_text("👋 <b>Vinted Monitoring PRO</b>", 
                                   reply_markup=main_menu_kb(chat_id), parse_mode='HTML')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id
    user_data = context.user_data
    is_admin = db_tma.is_admin(chat_id)

    # --- ПРОВЕРКА БАНА ---
    if db_tma.is_user_banned(chat_id):
        return

    # --- ОТВЕТ АДМИНА НА ЛЕГИТ ЧЕК (REPLY) ---
    if is_admin and update.message.reply_to_message:
        reply_to_id = update.message.reply_to_message.message_id
        target_user_id = db_tma.get_user_by_admin_msg(reply_to_id)
        if target_user_id:
            try:
                await context.bot.copy_message(
                    chat_id=target_user_id,
                    from_chat_id=chat_id,
                    message_id=update.message.message_id
                )
                await update.message.reply_text(f"✅ Ответ отправлен пользователю <code>{target_user_id}</code>.", parse_mode='HTML')
            except Exception as e:
                await update.message.reply_text(f"❌ Не удалось отправить ответ: {e}")
            return

    # --- FSM АДМИНА ---
    if user_data.get('state') == STATE_ADMIN_EDIT_PARAM:
        p_type, key = user_data.get('edit_target')
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Редактирование отменено.", reply_markup=main_menu_kb(chat_id))
            return
        if text in MAIN_MENU_TEXTS:
            await update.message.reply_text(
                f"⚠️ Сейчас редактируется <b>{key}</b>.\nОтправьте новое значение или нажмите <b>❌ Отмена</b>.",
                parse_mode='HTML',
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True)
            )
            return

        is_valid, validated_value = _validate_admin_param_value(key, text)
        if not is_valid:
            await update.message.reply_text(
                f"❌ {validated_value}\nПопробуйте еще раз для <b>{key}</b> или нажмите <b>❌ Отмена</b>.",
                parse_mode='HTML',
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True)
            )
            return

        try:
            if p_type == "param":
                db.set_parameter(key, validated_value)
            else:
                import sqlite3
                conn = sqlite3.connect("vinted_notifications.db")
                conn.execute("UPDATE commercial_settings SET value=? WHERE key=?", (validated_value, key))
                conn.commit()
                conn.close()
            await update.message.reply_text(f"✅ Параметр <b>{key}</b> обновлен: <code>{validated_value}</code>", parse_mode='HTML', reply_markup=main_menu_kb(chat_id))
        except Exception as e:
            logger.error(f"Error updating parameter {key}: {e}", exc_info=True)
            await update.message.reply_text("❌ Ошибка обновления.", reply_markup=main_menu_kb(chat_id))
        user_data['state'] = None
        return

    if user_data.get('state') == STATE_ADMIN_SET_PROXY_LIST:
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(chat_id))
            return
        db.set_parameter('proxy_list', text)
        await update.message.reply_text(f"✅ Список прокси обновлен!", reply_markup=main_menu_kb(chat_id))
        user_data['state'] = None
        return

    if user_data.get('state') == STATE_ADMIN_SET_PROXY_LINK:
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(chat_id))
            return
        db.set_parameter('proxy_list_link', text)
        await update.message.reply_text(f"✅ Ссылка на прокси обновлена!", reply_markup=main_menu_kb(chat_id))
        user_data['state'] = None
        return

    if user_data.get('state') == STATE_ADMIN_BROADCAST_TEXT:
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Рассылка отменена.", reply_markup=main_menu_kb(chat_id))
            return
        
        await update.message.reply_text("🚀 Начинаю рассылку...", reply_markup=main_menu_kb(chat_id))
        ids = db_tma.get_all_telegram_ids()
        count = 0
        blocked = 0
        for uid in ids:
            try:
                await context.bot.send_message(chat_id=uid, text=text, parse_mode='HTML')
                count += 1
                await asyncio.sleep(0.05)
            except Exception:
                blocked += 1
        
        await update.message.reply_text(f"✅ <b>Рассылка завершена!</b>\n\nОтправлено: {count}\nНедоставлено (блок): {blocked}", parse_mode='HTML')
        user_data['state'] = None
        return

    if user_data.get('state') == STATE_ADMIN_SEARCH_USER:
        results = db_tma.search_users(text)
        if not results:
            await update.message.reply_text("❌ Пользователи не найдены.", reply_markup=main_menu_kb(chat_id))
        else:
            msg = "🔍 <b>Результаты поиска:</b>\n"
            kb_buttons = []
            for u in results[:5]:
                u_status = "🟢" if db_tma.get_user_status(u['id']) != "No subscription" else "🔴"
                btn_text = f"{u_status} {u['username'] or u['telegram_id']}"
                kb_buttons.append([InlineKeyboardButton(btn_text, callback_data=f"adm_uinfo_{u['telegram_id']}")])
            
            kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="adm_users_menu")])
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb_buttons), parse_mode='HTML')
        user_data['state'] = None
        return

    if user_data.get('state') == STATE_ADMIN_ADD_SUB_DAYS:
        try:
            days = int(text.strip())
            if days <= 0:
                raise ValueError
            target_id = user_data.get('target_user_id')
            ok = db_tma.add_user_subscription_days(target_id, days)
            if ok:
                await update.message.reply_text(f"✅ Пользователю <code>{target_id}</code> добавлено <b>+{days}</b> дней.", parse_mode='HTML', reply_markup=main_menu_kb(chat_id))
            else:
                await update.message.reply_text("❌ Пользователь не найден.", reply_markup=main_menu_kb(chat_id))
        except ValueError:
            await update.message.reply_text("❌ Введите целое число дней больше 0.", reply_markup=main_menu_kb(chat_id))
        user_data['state'] = None
        return

    if user_data.get('state') == STATE_ADMIN_ADD_COUNTRY:
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(chat_id))
            return
        msg, countries = core.process_add_country(text.upper())
        countries_text = "Пусто" if countries == 0 else ", ".join(sorted(countries))
        await update.message.reply_text(
            f"✅ {msg}\nТекущий список: <code>{countries_text}</code>",
            parse_mode='HTML',
            reply_markup=main_menu_kb(chat_id)
        )
        user_data['state'] = None
        return

    if user_data.get('state') == STATE_ADMIN_REMOVE_COUNTRY:
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(chat_id))
            return
        msg, countries = core.process_remove_country(text.upper())
        countries_text = "Пусто" if countries == 0 else ", ".join(sorted(countries))
        await update.message.reply_text(
            f"✅ {msg}\nТекущий список: <code>{countries_text}</code>",
            parse_mode='HTML',
            reply_markup=main_menu_kb(chat_id)
        )
        user_data['state'] = None
        return

    # --- FSM LEGIT CHECK ---
    if user_data.get('state') == STATE_LEGIT_SEND_PHOTOS:
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(chat_id))
            return
            
        brand = user_data.get('legit_brand')
        username = f"@{update.effective_user.username}" if update.effective_user.username else "No Username"
        
        admins = db_tma.get_all_admin_ids()
        if not admins:
            # Fallback to hardcoded admin if no admins in DB
            admins = [ADMIN_ID]

        for aid in admins:
            try:
                # Пересылаем сообщение админу
                info_msg = await context.bot.send_message(
                    chat_id=aid,
                    text=f"📥 <b>Новый запрос на Legit Check!</b>\n\n👕 Бренд: <b>{brand}</b>\nОт: {username} (<code>{chat_id}</code>)",
                    parse_mode='HTML'
                )
                
                # Копируем само сообщение (фото/текст) админу
                admin_copy = await context.bot.copy_message(
                    chat_id=aid,
                    from_chat_id=chat_id,
                    message_id=update.message.message_id
                )
                
                # Сохраняем в БД, чтобы знать кому отвечать
                # Теперь любой админ сможет ответить на свою копию сообщения
                db_tma.save_legit_request(admin_copy.message_id, chat_id, brand)
            except Exception as e:
                logger.error(f"Failed to send legit request to admin {aid}: {e}")
        
        await update.message.reply_text("✅ Ваши данные отправлены на проверку. <b>Ожидайте ответа администратора!</b>", parse_mode='HTML', reply_markup=main_menu_kb(chat_id))
        user_data['state'] = None
        return

    # --- FSM ПОЛЬЗОВАТЕЛЯ ---
    if user_data.get('state') == STATE_WAITING_FOR_QUERY:
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(chat_id))
            return
        
        try:
            user = db_tma.get_or_create_user(chat_id)
            status = db_tma.get_user_status(user['id'])
            if "No subscription" in status or "Expired" in status:
                await update.message.reply_text("❌ Нет активной подписки!", reply_markup=main_menu_kb(chat_id))
            else:
                msg, success = core.process_query(text, user_id=chat_id)
                await update.message.reply_text(f"Результат: {msg}", reply_markup=main_menu_kb(chat_id))
        except Exception as e:
            logger.error(f"Error processing query: {e}", exc_info=True)
            await update.message.reply_text("❌ Ошибка.", reply_markup=main_menu_kb(chat_id))
        user_data['state'] = None
        return

    if user_data.get('state') == STATE_WAITING_FOR_KEY:
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(chat_id))
            return
        
        user = db_tma.get_or_create_user(chat_id)
        success, msg = db_tma.activate_key(user['id'], text)
        if success:
            await update.message.reply_text(f"✅ <b>Подписка активирована!</b>\n\n{msg}", parse_mode='HTML', reply_markup=main_menu_kb(chat_id))
        else:
            await update.message.reply_text(f"❌ <b>Ошибка:</b> {msg}", parse_mode='HTML', reply_markup=main_menu_kb(chat_id))
        user_data['state'] = None
        return

    if user_data.get('state') == STATE_WAITING_FOR_QUERY_RENAME:
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(chat_id))
            return
        
        q_id = user_data.get('rename_query_id')
        success = db.update_query_name(q_id, chat_id, text)
        if success:
            await update.message.reply_text(f"✅ Название запроса обновлено на: <b>{text}</b>", parse_mode='HTML', reply_markup=main_menu_kb(chat_id))
        else:
            await update.message.reply_text("❌ Ошибка при обновлении названия.", reply_markup=main_menu_kb(chat_id))
        
        user_data['state'] = None
        return

    # --- МЕНЮ ---
    if text == "➕ Добавить запрос":
        user_data['state'] = STATE_WAITING_FOR_QUERY
        await update.message.reply_text("🔗 Отправьте ссылку Vinted:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True))
    
    elif text == "📄 Мои запросы":
        try:
            queries = db.get_queries(user_id=chat_id)
            if not queries:
                await update.message.reply_text("📋 <b>Ваши запросы:</b>\n\nПусто", parse_mode='HTML')
                return

            from urllib.parse import urlparse, parse_qs
            kb_buttons = []
            msg = "📋 <b>Ваши запросы:</b>\n\nНажмите на ❌, чтобы удалить запрос."
            
            for q in queries:
                q_id, q_url, _, q_name = q
                
                # Safety check: Telegram only allows http/https URLs for InlineKeyboardButton
                if not q_url.startswith("http"):
                    continue
                
                if not q_name:
                    parsed = urlparse(q_url)
                    params = parse_qs(parsed.query)
                    q_name = params.get('search_text', ['Без названия'])[0]
                
                kb_buttons.append([
                    InlineKeyboardButton(f"🔍 {q_name}", url=q_url),
                    InlineKeyboardButton("✏️", callback_data=f"ren_q_{q_id}"),
                    InlineKeyboardButton("❌", callback_data=f"del_q_{q_id}")
                ])
                
            if not kb_buttons:
                await update.message.reply_text("📋 <b>Ваши запросы:</b>\n\nПусто (все ссылки некорректны)", parse_mode='HTML')
                return

            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb_buttons), parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error displaying queries for user {chat_id}: {e}", exc_info=True)
            await update.message.reply_text("❌ <b>Произошла ошибка при загрузке ваших запросов.</b>", parse_mode='HTML', reply_markup=main_menu_kb(chat_id))

    elif text == "📊 Статус":
        user = db_tma.get_or_create_user(chat_id)
        await update.message.reply_text(f"📊 Статус подписки: <b>{db_tma.get_user_status(user['id'])}</b>", parse_mode='HTML')

    elif text == "💳 Оплатить подписку":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🤖 CryptoBot", callback_data="pay_crypto_select")],
                                   [InlineKeyboardButton("🔑 Активировать код", callback_data="pay_activate_key")],
                                   [InlineKeyboardButton("💳 Карта (Менеджер)", url="https://t.me/goshaebashitshmot")]])
        await update.message.reply_text("Выберите способ оплаты:", reply_markup=kb)

    elif text == "🔍 Legit Check":
        user = db_tma.get_or_create_user(chat_id)
        if "Legit" in db_tma.get_user_status(user['id']):
            await update.message.reply_text("🏷 <b>Выберите бренд для проверки:</b>", reply_markup=legit_brands_kb(), parse_mode='HTML')
        else:
            await update.message.reply_text("❌ У вас нет активной подписки <b>Legit Check</b>.")

    elif text == "🆘 Тех. поддержка":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("👨‍💻 Написать администратору", url="tg://user?id=525127130")]])
        await update.message.reply_text("Если у вас возникли вопросы или проблемы, нажмите кнопку ниже:", reply_markup=kb)

    elif text == "🛠 Админ-панель" and is_admin:
        await update.message.reply_text("🛠 <b>Панель администратора</b>", reply_markup=admin_hub_kb(), parse_mode='HTML')

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.from_user.id
    user_data = context.user_data
    
    # --- ПРОВЕРКА БАНА ---
    if db_tma.is_user_banned(chat_id):
        await query.answer("Вы забанены.", show_alert=True)
        return

    admin_actions = (
        data.startswith("adm_")
        or data.startswith("edt_")
        or data.startswith("gen_key_")
        or data in ("set_scraper", "set_proxies", "set_payments", "admin_main")
    )
    if admin_actions and not db_tma.is_admin(chat_id):
        await query.answer("Недостаточно прав.", show_alert=True)
        return

    await query.answer()

    # --- LEGIT CHECK CALLBACKS ---
    if data.startswith("legit_brand_"):
        brand = data.split("_")[2]
        user_data['state'] = STATE_LEGIT_SEND_PHOTOS
        user_data['legit_brand'] = brand
        await query.edit_message_text(f"📸 <b>Вы выбрали {brand}</b>\n\nПришлите фотографии вещи (бирки, швы, общий вид) одним сообщением или альбомом.", parse_mode='HTML')

    elif data == "legit_cancel":
        user_data['state'] = None
        await query.edit_message_text("❌ Проверка отменена.", reply_markup=None)

    # --- НАВИГАЦИЯ ---
    elif data == "admin_main":
        await query.edit_message_text("🛠 <b>Панель администратора</b>", reply_markup=admin_hub_kb(), parse_mode='HTML')
    # ... (Остальной код админки без изменений) ...
    elif data == "adm_close": await query.message.delete()
    elif data == "adm_stats":
        stats = db_tma.admin_get_stats()
        msg = f"📊 <b>Статистика бота</b>\n\n👤 Пользователей: <b>{stats.get('total_users', 0)}</b>\n🟢 Активных: <b>{stats.get('active_users', 0)}</b>\n💵 Доход: <b>${stats.get('total_revenue', 0)}</b>"
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_main")]]), parse_mode='HTML')
    elif data == "adm_countries":
        await query.edit_message_text(_build_countries_text(), reply_markup=_build_countries_kb(), parse_mode='HTML')
    elif data == "adm_users_menu": await query.edit_message_text("👥 <b>Управление пользователями</b>", reply_markup=admin_users_kb(), parse_mode='HTML')
    elif data == "adm_list_users":
        users = db_tma.admin_get_users(limit=10)
        kb_buttons = [[InlineKeyboardButton(f"{'🟢' if db_tma.has_active_subscription(u['id']) else '🔴'} {u['username'] or u['telegram_id']}", callback_data=f"adm_uinfo_{u['telegram_id']}")] for u in users]
        kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="adm_users_menu")])
        await query.edit_message_text("👥 <b>Последние 10 пользователей:</b>", reply_markup=InlineKeyboardMarkup(kb_buttons), parse_mode='HTML')
    elif data == "adm_search_user":
        user_data['state'] = STATE_ADMIN_SEARCH_USER
        await query.message.reply_text("🔍 Введите ID или Username:")
    elif data.startswith("adm_uinfo_"):
        uid = int(data.split("_")[2]); user_list = db_tma.search_users(str(uid))
        if not user_list: await query.edit_message_text("❌ Не найден."); return
        user = user_list[0]; status = db_tma.get_user_status(user['id'])
        is_user_admin = bool(user['is_admin'])
        is_user_banned = bool(user['is_banned'])
        admin_btn_text = "❌ Снять админа" if is_user_admin else "👑 Сделать админом"
        ban_btn_text = "✅ Разбанить" if is_user_banned else "🚫 Забанить"
        
        msg = f"👤 <b>Инфо о пользователе</b>\n\n🆔 ID: <code>{user['telegram_id']}</code>\n👤 User: @{user['username']}\n📊 Подписка: <b>{status}</b>\n🛡 Админ: <b>{'Да' if is_user_admin else 'Нет'}</b>\n🚫 Бан: <b>{'Да' if is_user_banned else 'Нет'}</b>"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Добавить дни", callback_data=f"adm_add_days_{uid}")],
            [InlineKeyboardButton(admin_btn_text, callback_data=f"adm_toggle_admin_{uid}_{'0' if is_user_admin else '1'}")],
            [InlineKeyboardButton(ban_btn_text, callback_data=f"adm_toggle_ban_{uid}_{'0' if is_user_banned else '1'}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="adm_users_menu")]
        ])
        await query.edit_message_text(msg, reply_markup=kb, parse_mode='HTML')

    elif data.startswith("adm_toggle_admin_"):
        parts = data.split("_")
        uid = int(parts[3])
        new_status = bool(int(parts[4]))
        db_tma.set_admin_status(uid, new_status)
        # Re-display user info to show changes
        user_list = db_tma.search_users(str(uid))
        user = user_list[0]
        status = db_tma.get_user_status(user['id'])
        admin_btn_text = "❌ Снять админа" if new_status else "👑 Сделать админом"
        msg = f"✅ Статус обновлен!\n\n👤 <b>Инфо</b>\n🆔 ID: <code>{user['telegram_id']}</code>\n👤 User: @{user['username']}\n📊 Sub: <b>{status}</b>\n🛡 Admin: <b>{'Да' if new_status else 'Нет'}</b>"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Добавить дни", callback_data=f"adm_add_days_{uid}")], [InlineKeyboardButton(admin_btn_text, callback_data=f"adm_toggle_admin_{uid}_{'0' if new_status else '1'}")], [InlineKeyboardButton("⬅️ Назад", callback_data="adm_users_menu")]])
        await query.edit_message_text(msg, reply_markup=kb, parse_mode='HTML')

    elif data.startswith("adm_toggle_ban_"):
        parts = data.split("_")
        uid = int(parts[3])
        new_status = bool(int(parts[4]))
        db_tma.ban_user(uid, new_status)
        # Re-display user info
        user_list = db_tma.search_users(str(uid))
        user = user_list[0]; status = db_tma.get_user_status(user['id'])
        is_user_admin = bool(user['is_admin'])
        admin_btn_text = "❌ Снять админа" if is_user_admin else "👑 Сделать админом"
        ban_btn_text = "✅ Разбанить" if new_status else "🚫 Забанить"
        msg = f"✅ Статус обновлен!\n\n👤 <b>Инфо</b>\n🆔 ID: <code>{user['telegram_id']}</code>\n👤 User: @{user['username']}\n📊 Sub: <b>{status}</b>\n🛡 Admin: <b>{'Да' if is_user_admin else 'Нет'}</b>\n🚫 Бан: <b>{'Да' if new_status else 'Нет'}</b>"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Добавить дни", callback_data=f"adm_add_days_{uid}")],
            [InlineKeyboardButton(admin_btn_text, callback_data=f"adm_toggle_admin_{uid}_{'0' if is_user_admin else '1'}")],
            [InlineKeyboardButton(ban_btn_text, callback_data=f"adm_toggle_ban_{uid}_{'0' if new_status else '1'}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="adm_users_menu")]
        ])
        await query.edit_message_text(msg, reply_markup=kb, parse_mode='HTML')
    elif data.startswith("adm_add_days_"):
        user_data['state'] = STATE_ADMIN_ADD_SUB_DAYS; user_data['target_user_id'] = int(data.split("_")[3])
        await query.message.reply_text("📅 Кол-во дней:")
    elif data == "adm_broadcast":
        user_data['state'] = STATE_ADMIN_BROADCAST_TEXT; await query.message.reply_text("📢 Текст рассылки (HTML):")
    elif data == "adm_logs":
        try:
            with open("logs/vinted.log", "r") as f: last_lines = "".join(f.readlines()[-15:])
            await query.message.reply_text(f"📜 <b>Логи:</b>\n<pre>{last_lines}</pre>", parse_mode='HTML')
        except: await query.edit_message_text("❌ Ошибка логов.")
    elif data == "adm_settings":
        await safe_edit_message(query, "⚙️ <b>Настройки</b>", reply_markup=admin_settings_kb(), parse_mode='HTML')
    elif data == "set_payments":
        await safe_edit_message(query, _build_payments_text(), reply_markup=_build_payments_kb(), parse_mode='HTML')
    elif data == "adm_country_add":
        user_data['state'] = STATE_ADMIN_ADD_COUNTRY
        await query.message.reply_text("➕ Введите код страны (например, <code>PL</code>):", parse_mode='HTML')
    elif data == "adm_country_remove":
        user_data['state'] = STATE_ADMIN_REMOVE_COUNTRY
        await query.message.reply_text("➖ Введите код страны для удаления (например, <code>PL</code>):", parse_mode='HTML')
    elif data == "adm_country_clear":
        db.clear_allowlist()
        await safe_edit_message(query, _build_countries_text(), reply_markup=_build_countries_kb(), parse_mode='HTML')
    elif data == "set_scraper":
        delay = db.get_parameter('query_refresh_delay'); items = db.get_parameter('items_per_query')
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"⏱ Задержка: {delay}с", callback_data="edt_param_query_refresh_delay")], [InlineKeyboardButton(f"📦 Кол-во: {items}", callback_data="edt_param_items_per_query")], [InlineKeyboardButton("⬅️ Назад", callback_data="adm_settings")]])
        await safe_edit_message(query, "🤖 <b>Настройки скрейпера</b>", reply_markup=kb, parse_mode='HTML')
    
    # --- ПРОКСИ ---
    elif data == "set_proxies":
        p_check = db.get_parameter('check_proxies') or "False"
        msg = _build_proxy_settings_text()
        kb = _build_proxy_settings_kb(p_check)
        await safe_edit_message(query, msg, reply_markup=kb, parse_mode='HTML')
    
    elif data == "adm_proxy_set_list":
        user_data['state'] = STATE_ADMIN_SET_PROXY_LIST
        await query.message.reply_text("📝 Введите список прокси через точку с запятой (;) \n\nПример: <code>host:port:user:pass;host:port</code> \n\nИли нажмите /start для отмены.", parse_mode='HTML')
    
    elif data == "adm_proxy_set_link":
        user_data['state'] = STATE_ADMIN_SET_PROXY_LINK
        await query.message.reply_text("🔗 Введите прямую ссылку на список прокси (txt):")
    
    elif data == "adm_proxy_toggle_check":
        current = db.get_parameter('check_proxies')
        new_val = "True" if current != "True" else "False"
        db.set_parameter('check_proxies', new_val)
        # Перерисовываем меню прокси
        msg = _build_proxy_settings_text()
        kb = _build_proxy_settings_kb(new_val)
        await safe_edit_message(query, msg, reply_markup=kb, parse_mode='HTML')
    elif data == "adm_proxy_disable":
        db.set_parameter('proxy_list', '')
        db.set_parameter('proxy_list_link', '')
        db.set_parameter('check_proxies', 'False')
        reset_proxy_cache()
        msg = _build_proxy_settings_text()
        kb = _build_proxy_settings_kb("False")
        await safe_edit_message(query, msg, reply_markup=kb, parse_mode='HTML')

    elif data == "adm_clear_items_confirm":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, очистить", callback_data="adm_clear_items_execute")],
            [InlineKeyboardButton("❌ Отмена", callback_data="adm_settings")]
        ])
        await query.edit_message_text("⚠️ <b>Вы уверены?</b>\nЭто удалит все найденные товары из базы (запросы останутся).", reply_markup=kb, parse_mode='HTML')
    
    elif data == "adm_clear_items_execute":
        db.clear_items_only()
        await query.edit_message_text("✅ База товаров очищена!", reply_markup=admin_settings_kb(), parse_mode='HTML')

    elif data.startswith("edt_"):
        parts = data.split("_", 2); user_data['state'] = STATE_ADMIN_EDIT_PARAM; user_data['edit_target'] = (parts[1], parts[2])
        await query.message.reply_text(
            f"📝 Новое значение для {parts[2]}:\n\nДля отмены нажмите <b>❌ Отмена</b>.",
            parse_mode='HTML',
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True)
        )
    elif data == "pay_crypto_select":
        p1 = db_tma.get_setting('crypto_price_usdt') or '5'; p2 = db_tma.get_setting('crypto_price_bot_legit_usdt') or '10'
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"🤖 Bot ({p1}$)", callback_data="pay_crypto_basic")], [InlineKeyboardButton(f"🤖 Bot + Legit ({p2}$)", callback_data="pay_crypto_legit")], [InlineKeyboardButton("⬅️ Назад", callback_data="pay_back")]])
        await query.edit_message_text("Выберите тариф:", reply_markup=kb)
    elif data == "pay_back":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🤖 CryptoBot", callback_data="pay_crypto_select")], [InlineKeyboardButton("🔑 Активировать код", callback_data="pay_activate_key")]])
        await query.edit_message_text("Выберите способ оплаты:", reply_markup=kb)
    elif data == "pay_activate_key": user_data['state'] = STATE_WAITING_FOR_KEY; await query.message.reply_text("🔑 Введите ключ:")
    elif data == "adm_gen_key":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎁 30 дней (Basic)", callback_data="gen_key_30_basic")], [InlineKeyboardButton("🎁 30 дней (Legit)", callback_data="gen_key_30_bot_legit")]])
        await query.edit_message_text("🔑 <b>Выберите ключ</b>", reply_markup=kb, parse_mode='HTML')
    elif data.startswith("gen_key_"):
        parts = data.split("_"); k = db_tma.admin_generate_key(int(parts[2]), "_".join(parts[3:]))
        await query.message.reply_text(f"🔑 <b>Ключ:</b> <code>{k}</code>", parse_mode='HTML')
    elif data == "pay_crypto_basic":
        url, _ = await db_tma.create_crypto_invoice(db_tma.get_or_create_user(chat_id)['id'], amount_usdt=float(db_tma.get_setting('crypto_price_usdt') or 5), sub_type="basic")
        if url: await query.message.reply_text(f"🤖 Оплата (Bot): {url}")
    elif data.startswith("pay_crypto_legit"):
        url, _ = await db_tma.create_crypto_invoice(db_tma.get_or_create_user(chat_id)['id'], amount_usdt=float(db_tma.get_setting('crypto_price_bot_legit_usdt') or 10), sub_type="bot_legit")
        if url: await query.message.reply_text(f"🤖 Оплата (Legit): {url}")

    # --- УДАЛЕНИЕ ЗАПРОСА ---
    elif data.startswith("del_q_"):
        q_id = int(data.split("_")[2])
        success = db.remove_query_by_id(q_id, chat_id)
        if success:
            await query.edit_message_text("✅ Запрос удален.")
        else:
            await query.edit_message_text("❌ Ошибка при удалении запроса.")

    # --- ПЕРЕИМЕНОВАНИЕ ЗАПРОСА ---
    elif data.startswith("ren_q_"):
        q_id = int(data.split("_")[2])
        user_data['state'] = STATE_WAITING_FOR_QUERY_RENAME
        user_data['rename_query_id'] = q_id
        await query.message.reply_text("📝 <b>Введите новое название для этого запроса:</b>", parse_mode='HTML', reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True))

# --- СТАНДАРТНАЯ ЛОГИКА УВЕДОМЛЕНИЙ ---

async def notify_new_items(queue, bot, chat_ids):
    while not shutdown_event.is_set():
        try:
            if not queue.empty():
                content, url, btn_text, photo_url, buy_url, target_user_id = queue.get()
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔎 Открыть на Vinted", url=url)] + ([InlineKeyboardButton("⚡️ Быстрая покупка", url=buy_url)] if buy_url else [])])
                
                if target_user_id:
                    # Send only to the user who owns the query
                    try:
                        # Optional: check if user is banned or sub expired
                        if not db_tma.is_user_banned(target_user_id):
                            user_status = db_tma.get_user_status(db_tma.get_or_create_user(target_user_id)['id'])
                            if "No subscription" not in user_status and "Expired" not in user_status:
                                if photo_url: await bot.send_photo(chat_id=target_user_id, photo=photo_url, caption=content, reply_markup=kb, parse_mode='HTML')
                                else: await bot.send_message(chat_id=target_user_id, text=content, reply_markup=kb, parse_mode='HTML')
                        await asyncio.sleep(0.05)
                    except: pass
                else:
                    # Fallback if no target_user_id: send to all active (original behavior)
                    active_ids = db_tma.get_active_subscribers()
                    for cid in active_ids:
                        try:
                            if photo_url: await bot.send_photo(chat_id=cid, photo=photo_url, caption=content, reply_markup=kb, parse_mode='HTML')
                            else: await bot.send_message(chat_id=cid, text=content, reply_markup=kb, parse_mode='HTML')
                            await asyncio.sleep(0.05)
                        except: pass
            await asyncio.sleep(0.1)
        except: await asyncio.sleep(1)

async def check_crypto_invoices_loop():
    while not shutdown_event.is_set():
        try:
            pending = db_tma.get_pending_crypto_invoices()
            for inv_id in pending: await db_tma.check_crypto_invoice(inv_id)
            await asyncio.sleep(60)
        except: await asyncio.sleep(10)

def signal_handler(sig, frame): shutdown_event.set()

def run_bot_in_process(queue: multiprocessing.Queue):
    token = db.get_parameter('telegram_token')
    if not token: return
    db_tma.init_legit_db() # Инициализируем БД
    signal.signal(signal.SIGINT, signal_handler); signal.signal(signal.SIGTERM, signal_handler)
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", lambda u, c: start(u, c, set())))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(callback_handler))
    async def main():
        async with application:
            await application.initialize(); await application.start()
            asyncio.create_task(notify_new_items(queue, application.bot, set()))
            asyncio.create_task(check_crypto_invoices_loop())
            await application.updater.start_polling(); await shutdown_event.wait(); await application.updater.stop()
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop); loop.run_until_complete(main())

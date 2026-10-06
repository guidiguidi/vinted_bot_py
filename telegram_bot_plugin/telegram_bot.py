# telegram_bot_plugin/telegram_bot.py
import asyncio
import os
import multiprocessing
import signal
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.error import BadRequest
from logger import get_logger
import db
import core
import db_commercial as db_tma
from proxies import get_dataimpulse_usage_status, reset_proxy_cache

load_dotenv()

logger = get_logger(__name__)
shutdown_event = asyncio.Event()

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "525127130"))
except Exception:
    ADMIN_ID = 525127130

# Состояния FSM
STATE_WAITING_FOR_QUERY = "WAITING_FOR_QUERY"
STATE_ADMIN_EDIT_PARAM = "ADMIN_EDIT_PARAM"
STATE_ADMIN_BROADCAST_TEXT = "ADMIN_BROADCAST_TEXT"
STATE_ADMIN_SEARCH_USER = "ADMIN_SEARCH_USER"
STATE_WAITING_FOR_QUERY_RENAME = "WAITING_FOR_QUERY_RENAME"
STATE_ADMIN_ADD_COUNTRY = "ADMIN_ADD_COUNTRY"
STATE_ADMIN_REMOVE_COUNTRY = "ADMIN_REMOVE_COUNTRY"

# Новые состояния для прокси
STATE_ADMIN_ADD_PROXY = "ADMIN_ADD_PROXY"
STATE_ADMIN_SET_PROXY_LIST = "ADMIN_SET_PROXY_LIST"
STATE_ADMIN_SET_PROXY_LINK = "ADMIN_SET_PROXY_LINK"

# Состояния для снайпера
STATE_SNIPER_SET_PROXY = "SNIPER_SET_PROXY"
STATE_SNIPER_SET_COOKIE = "SNIPER_SET_COOKIE"
STATE_SNIPER_SET_DOMAIN = "SNIPER_SET_DOMAIN"



# --- КЛАВИАТУРЫ ---

MAIN_MENU_TEXTS = {
    "➕ Добавить запрос",
    "📄 Мои запросы",
    "🎯 Снайпер",
    "🌐 Прокси",
    "⚙️ Настройки",
    "📊 Статус",
    "🛠 Админ-панель",
}

def main_menu_kb(chat_id: int = None) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="➕ Добавить запрос"), KeyboardButton(text="📄 Мои запросы")],
        [KeyboardButton(text="🎯 Снайпер"), KeyboardButton(text="🌐 Прокси")],
        [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="📊 Статус")],
        [KeyboardButton(text="🛠 Админ-панель")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def admin_hub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("📊 Статистика", callback_data="adm_stats"),
         InlineKeyboardButton("👥 Пользователи", callback_data="adm_users_menu")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="adm_settings"),
         InlineKeyboardButton("🌍 Страны", callback_data="adm_countries")],
        [InlineKeyboardButton("📢 Рассылка", callback_data="adm_broadcast"),
         InlineKeyboardButton("📜 Логи", callback_data="adm_logs")],
        [InlineKeyboardButton("🎯 Снайпер", callback_data="adm_sniper_menu")],
        [InlineKeyboardButton("⬅️ Закрыть", callback_data="adm_close")]
    ])

def admin_settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🤖 Скрейпер", callback_data="set_scraper"),
         InlineKeyboardButton("🌐 Прокси", callback_data="set_proxies")],
        [InlineKeyboardButton("🌍 Страны", callback_data="adm_countries"),
         InlineKeyboardButton("📜 Логи", callback_data="adm_logs")],
        [InlineKeyboardButton("🧹 Очистить базу товаров", callback_data="adm_clear_items_confirm")],
        [InlineKeyboardButton("⬅️ Закрыть", callback_data="adm_close")]
    ])

def admin_users_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🔍 Поиск юзера", callback_data="adm_search_user")],
        [InlineKeyboardButton("📜 Список (Топ 10)", callback_data="adm_list_users")],
        [InlineKeyboardButton("⬅️ Закрыть", callback_data="adm_close")]
    ])

def sniper_menu_kb(user_id: int = None) -> InlineKeyboardMarkup:
    """User menu for personal AntiGravity Sniper settings."""
    user_id = user_id or ADMIN_ID
    settings = db_tma.get_user_sniper_settings(user_id)
    enabled = settings.get('enabled')
    toggle_data = "sniper_toggle"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(f"{'🟢' if enabled else '🔴'} Статус: {'ВКЛ' if enabled else 'ВЫКЛ'}", callback_data=toggle_data)],
        [InlineKeyboardButton("🌐 Прокси снайпера", callback_data="sniper_set_proxy"),
         InlineKeyboardButton("🍪 Cookie", callback_data="sniper_set_cookie")],
        [InlineKeyboardButton("🌍 Домен", callback_data="sniper_set_domain"),
         InlineKeyboardButton("📊 Логи (10)", callback_data="sniper_logs")],
        [InlineKeyboardButton("⬅️ Закрыть", callback_data="sniper_close")]
    ])


def _mask_token(raw_token: str) -> str:
    if not raw_token:
        return "не задан"
    if len(raw_token) <= 8:
        return "*" * len(raw_token)
    return f"{raw_token[:4]}...{raw_token[-4:]}"


def _build_proxy_settings_text() -> str:
    from proxies import get_proxies_list
    proxies_list = get_proxies_list()
    count_text = f"<b>{len(proxies_list)} шт.</b>" if proxies_list else "<i>пусто</i>"
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
        f"📊 Прокси в базе: {count_text}\n"
        f"📜 Список: <code>{p_list[:50]}...</code>\n"
        f"🔗 Ссылка: <code>{p_link}</code>\n"
        f"✅ Проверка: <b>{p_check}</b>\n"
        f"🔑 DataImpulse token: <code>{_mask_token(token)}</code>\n"
        f"📏 Лимит плана (MB): <b>{plan_mb}</b>\n"
        f"{usage_line}"
    )


def _build_proxy_settings_kb(p_check: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить прокси", callback_data="adm_proxy_add")],
        [InlineKeyboardButton("📝 Заменить весь список", callback_data="adm_proxy_set_list")],
        [InlineKeyboardButton("🔗 Установить ссылку", callback_data="adm_proxy_set_link")],
        [InlineKeyboardButton("🔑 DataImpulse token", callback_data="edt_param_dataimpulse_api_token")],
        [InlineKeyboardButton("📏 Лимит MB", callback_data="edt_param_dataimpulse_plan_mb")],
        [InlineKeyboardButton(f"🔄 Проверка: {p_check}", callback_data="adm_proxy_toggle_check")],
        [InlineKeyboardButton("🛑 Выключить прокси", callback_data="adm_proxy_disable")],
        [InlineKeyboardButton("⬅️ Закрыть", callback_data="adm_close")]
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
        [InlineKeyboardButton("⬅️ Закрыть", callback_data="adm_close")]
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
    int_positive_keys = {"query_refresh_delay", "items_per_query"}
    number_non_negative_keys = {"dataimpulse_plan_mb"}

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
            db.set_parameter(key, validated_value)
            await update.message.reply_text(f"✅ Параметр <b>{key}</b> обновлен: <code>{validated_value}</code>", parse_mode='HTML', reply_markup=main_menu_kb(chat_id))
        except Exception as e:
            logger.error(f"Error updating parameter {key}: {e}", exc_info=True)
            await update.message.reply_text("❌ Ошибка обновления.", reply_markup=main_menu_kb(chat_id))
        user_data['state'] = None
        return

    if user_data.get('state') == STATE_ADMIN_ADD_PROXY:
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(chat_id))
            return
        msg, _ = core.process_add_proxy(text)
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=main_menu_kb(chat_id))
        user_data['state'] = None
        return

    if user_data.get('state') == STATE_ADMIN_SET_PROXY_LIST:
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(chat_id))
            return
        raw = text.replace("\r", "")
        lines = [line.strip() for line in raw.split("\n") if line.strip()]
        proxies_parsed = []
        for l in lines:
            for p in l.split(";"):
                p = p.strip()
                if p:
                    proxies_parsed.append(p)
        joined_proxies = ";".join(proxies_parsed)
        db.set_parameter('proxy_list', joined_proxies)
        reset_proxy_cache()
        await update.message.reply_text(f"✅ Список прокси скрейпера сохранен (всего: <b>{len(proxies_parsed)}</b> шт.)!", parse_mode='HTML', reply_markup=main_menu_kb(chat_id))
        user_data['state'] = None
        return

    if user_data.get('state') == STATE_ADMIN_SET_PROXY_LINK:
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(chat_id))
            return
        link = text.strip()
        db.set_parameter('proxy_list_link', link)
        reset_proxy_cache()
        await update.message.reply_text(f"✅ Ссылка на прокси обновлена: <code>{link}</code>", parse_mode='HTML', reply_markup=main_menu_kb(chat_id))
        user_data['state'] = None
        return

    # --- Sniper FSM states ---
    if user_data.get('state') == STATE_SNIPER_SET_PROXY:
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(chat_id))
            return
        proxy_val = text.strip()
        if "://" not in proxy_val and proxy_val.count(":") == 3:
            parts = proxy_val.split(":")
            proxy_val = f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
        elif "://" not in proxy_val and proxy_val.count(":") == 1:
            proxy_val = f"http://{proxy_val}"
            
        db_tma.update_user_sniper_setting(chat_id, 'proxy', proxy_val)
        await update.message.reply_text(f"✅ Прокси снайпера сохранен: <code>{proxy_val}</code>", parse_mode='HTML', reply_markup=main_menu_kb(chat_id))
        user_data['state'] = None
        return

    if user_data.get('state') == STATE_SNIPER_SET_COOKIE:
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(chat_id))
            return
        db_tma.update_user_sniper_setting(chat_id, 'session_cookie', text.strip())
        await update.message.reply_text("✅ Session cookie обновлен!", reply_markup=main_menu_kb(chat_id))
        user_data['state'] = None
        return

    if user_data.get('state') == STATE_SNIPER_SET_DOMAIN:
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(chat_id))
            return
        domain = text.strip().lower()
        if not domain.startswith("www.vinted."):
            await update.message.reply_text("❌ Некорректный домен. Используйте формат: www.vinted.fr")
            return
        db_tma.update_user_sniper_setting(chat_id, 'domain', domain)
        await update.message.reply_text(f"✅ Домен установлен: {domain}", reply_markup=main_menu_kb(chat_id))
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
                btn_text = f"{'👑' if u.get('is_admin') else '👤'} {u['username'] or u['telegram_id']}"
                kb_buttons.append([InlineKeyboardButton(btn_text, callback_data=f"adm_uinfo_{u['telegram_id']}")])
            
            kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="adm_users_menu")])
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb_buttons), parse_mode='HTML')
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



    # --- FSM ПОЛЬЗОВАТЕЛЯ ---
    if user_data.get('state') == STATE_WAITING_FOR_QUERY:
        if text == "❌ Отмена":
            user_data['state'] = None
            await update.message.reply_text("Отменено.", reply_markup=main_menu_kb(chat_id))
            return
        
        try:
            msg, success = core.process_query(text, user_id=chat_id)
            await update.message.reply_text(f"Результат: {msg}", reply_markup=main_menu_kb(chat_id), parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error processing query: {e}", exc_info=True)
            await update.message.reply_text("❌ Ошибка при обработке ссылки.", reply_markup=main_menu_kb(chat_id))
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
        await update.message.reply_text(
            "🔗 <b>Отправьте ссылку на поиск Vinted:</b>\n\n"
            "Пример:\n<code>https://www.vinted.fr/catalog?search_text=nike&order=newest_first</code>\n\n"
            "Или нажмите ❌ Отмена.",
            parse_mode='HTML',
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True)
        )
    
    elif text == "📄 Мои запросы":
        try:
            queries = db.get_queries(user_id=chat_id)
            if not queries:
                await update.message.reply_text("📋 <b>Ваши запросы:</b>\n\nСписок пуст. Нажмите «➕ Добавить запрос».", parse_mode='HTML')
                return

            from urllib.parse import urlparse, parse_qs
            kb_buttons = []
            msg = "📋 <b>Ваши запросы:</b>\n\nНажмите ✏️ для переименования или ❌ для удаления:"
            
            for q in queries:
                q_id, q_url, _, q_name = q
                
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
                await update.message.reply_text("📋 <b>Ваши запросы:</b>\n\nСписок пуст.", parse_mode='HTML')
                return

            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb_buttons), parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error displaying queries for user {chat_id}: {e}", exc_info=True)
            await update.message.reply_text("❌ <b>Произошла ошибка при загрузке ваших запросов.</b>", parse_mode='HTML', reply_markup=main_menu_kb(chat_id))

    elif text in ("🎯 Снайпер", "🎯 Мой Снайпер"):
        settings = db_tma.get_user_sniper_settings(chat_id)
        enabled = settings.get('enabled')
        domain = settings.get('domain') or 'www.vinted.fr'
        proxy = settings.get('proxy') or 'не задан'
        cookie = settings.get('session_cookie') or ''
        cookie_display = f"{cookie[:20]}..." if len(cookie) > 20 else (cookie or 'не задан')
        
        text_msg = (
            f"🎯 <b>AntiGravity Sniper</b>\n\n"
            f"Статус: <b>{'🟢 ВКЛ' if enabled else '🔴 ВЫКЛ'}</b>\n"
            f"Домен: <code>{domain}</code>\n"
            f"Прокси: <code>{proxy[:40]}</code>\n"
            f"Cookie: <code>{cookie_display}</code>\n"
        )
        await update.message.reply_text(text_msg, reply_markup=sniper_menu_kb(chat_id), parse_mode='HTML')

    elif text == "🌐 Прокси":
        p_check = db.get_parameter('check_proxies') or "False"
        msg = _build_proxy_settings_text()
        kb = _build_proxy_settings_kb(p_check)
        await update.message.reply_text(msg, reply_markup=kb, parse_mode='HTML')

    elif text == "⚙️ Настройки":
        delay = db.get_parameter('query_refresh_delay') or "60"
        items_cnt = db.get_parameter('items_per_query') or "20"
        countries = db.get_allowlist()
        countries_str = "Все страны" if countries == 0 else ", ".join(countries)
        msg = (
            "⚙️ <b>Настройки парсера</b>\n\n"
            f"⏱ Задержка проверки: <b>{delay} сек</b>\n"
            f"📦 Лимит товаров за цикл: <b>{items_cnt}</b>\n"
            f"🌍 Фильтр стран продавца: <code>{countries_str}</code>\n"
        )
        await update.message.reply_text(msg, reply_markup=admin_settings_kb(), parse_mode='HTML')

    elif text == "📊 Статус":
        from sniper.redis_bus import is_redis_available
        user_queries = db.get_queries(user_id=chat_id)
        q_count = len(user_queries) if user_queries else 0
        total_queries = db.get_total_queries_count()
        delay = db.get_parameter("query_refresh_delay") or "60"
        p_check = db.get_parameter("check_proxies") or "False"
        p_list = db.get_parameter("proxy_list") or ""
        p_link = db.get_parameter("proxy_list_link") or ""
        p_count = len([p for p in p_list.replace("\r", "").replace("\n", ";").split(";") if p.strip()]) if p_list else 0
        if p_link:
            proxy_status = f"🔗 По ссылке ({p_count} в списке)"
        elif p_count > 0:
            proxy_status = f"✅ Активно ({p_count} шт.)"
        else:
            proxy_status = "⚠️ Не заданы (прямой IP)"

        s_settings = db_tma.get_user_sniper_settings(chat_id)
        s_enabled = s_settings.get("enabled")
        s_domain = s_settings.get("domain") or "www.vinted.fr"
        s_proxy = "Задан ✅" if s_settings.get("proxy") else "Не задан ⚠️"
        s_cookie = "Задан ✅" if s_settings.get("session_cookie") else "Не задан ⚠️"
        redis_status = "✅ Работает" if is_redis_available() else "⚠️ Не запущен (нужен для снайпера)"

        status_msg = (
            "📊 <b>Статус системы</b>\n\n"
            f"🤖 <b>Скрейпер:</b>\n"
            f"• Моих запросов: <b>{q_count}</b> (всего в базе: {total_queries})\n"
            f"• Интервал проверки: <b>{delay} сек</b>\n"
            f"• Прокси скрейпера: <b>{proxy_status}</b>\n"
            f"• Автопроверка прокси: <b>{'Вкл' if p_check == 'True' else 'Выкл'}</b>\n\n"
            f"🎯 <b>Снайпер (автопокупка):</b>\n"
            f"• Статус: <b>{'🟢 ВКЛ' if s_enabled else '🔴 ВЫКЛ'}</b>\n"
            f"• Домен: <code>{s_domain}</code>\n"
            f"• Прокси снайпера: <b>{s_proxy}</b>\n"
            f"• Session Cookie: <b>{s_cookie}</b>\n"
            f"• Redis IPC: <b>{redis_status}</b>\n"
        )
        await update.message.reply_text(status_msg, reply_markup=main_menu_kb(chat_id), parse_mode='HTML')

    elif text == "🛠 Админ-панель":
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

    await query.answer()



    # --- НАВИГАЦИЯ ---
    if data == "admin_main":
        await query.edit_message_text("🛠 <b>Панель администратора</b>", reply_markup=admin_hub_kb(), parse_mode='HTML')
    elif data == "adm_close": await query.message.delete()
    elif data == "adm_stats":
        stats = db_tma.admin_get_stats()
        msg = f"📊 <b>Статистика бота</b>\n\n👤 Всего пользователей: <b>{stats.get('total_users', 0)}</b>\n🟢 Активных: <b>{stats.get('active_users', 0)}</b>\n🔍 Поисковых запросов: <b>{stats.get('total_queries', 0)}</b>"
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_main")]]), parse_mode='HTML')
    elif data == "adm_countries":
        await query.edit_message_text(_build_countries_text(), reply_markup=_build_countries_kb(), parse_mode='HTML')
    elif data == "adm_users_menu": await query.edit_message_text("👥 <b>Управление пользователями</b>", reply_markup=admin_users_kb(), parse_mode='HTML')
    elif data == "adm_list_users":
        users = db_tma.admin_get_users(limit=10)
        kb_buttons = [[InlineKeyboardButton(f"{'👑' if u.get('is_admin') else '👤'} {u['username'] or u['telegram_id']}", callback_data=f"adm_uinfo_{u['telegram_id']}")] for u in users]
        kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="adm_users_menu")])
        await query.edit_message_text("👥 <b>Последние 10 пользователей:</b>", reply_markup=InlineKeyboardMarkup(kb_buttons), parse_mode='HTML')
    elif data == "adm_search_user":
        user_data['state'] = STATE_ADMIN_SEARCH_USER
        await query.message.reply_text("🔍 Введите ID или Username:")
    elif data.startswith("adm_uinfo_"):
        uid = int(data.split("_")[2]); user_list = db_tma.search_users(str(uid))
        if not user_list: await query.edit_message_text("❌ Не найден."); return
        user = user_list[0]
        is_user_admin = bool(user['is_admin'])
        is_user_banned = bool(user['is_banned'])
        admin_btn_text = "❌ Снять админа" if is_user_admin else "👑 Сделать админом"
        ban_btn_text = "✅ Разбанить" if is_user_banned else "🚫 Забанить"
        
        msg = f"👤 <b>Инфо о пользователе</b>\n\n🆔 ID: <code>{user['telegram_id']}</code>\n👤 User: @{user['username'] or 'N/A'}\n🛡 Админ: <b>{'Да' if is_user_admin else 'Нет'}</b>\n🚫 Бан: <b>{'Да' if is_user_banned else 'Нет'}</b>"
        
        kb = InlineKeyboardMarkup([
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
        user_list = db_tma.search_users(str(uid))
        user = user_list[0]
        is_user_banned = bool(user['is_banned'])
        admin_btn_text = "❌ Снять админа" if new_status else "👑 Сделать админом"
        ban_btn_text = "✅ Разбанить" if is_user_banned else "🚫 Забанить"
        msg = f"✅ Статус обновлен!\n\n👤 <b>Инфо</b>\n🆔 ID: <code>{user['telegram_id']}</code>\n👤 User: @{user['username'] or 'N/A'}\n🛡 Admin: <b>{'Да' if new_status else 'Нет'}</b>\n🚫 Бан: <b>{'Да' if is_user_banned else 'Нет'}</b>"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(admin_btn_text, callback_data=f"adm_toggle_admin_{uid}_{'0' if new_status else '1'}")],
            [InlineKeyboardButton(ban_btn_text, callback_data=f"adm_toggle_ban_{uid}_{'0' if is_user_banned else '1'}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="adm_users_menu")]
        ])
        await query.edit_message_text(msg, reply_markup=kb, parse_mode='HTML')

    elif data.startswith("adm_toggle_ban_"):
        parts = data.split("_")
        uid = int(parts[3])
        new_status = bool(int(parts[4]))
        db_tma.ban_user(uid, new_status)
        user_list = db_tma.search_users(str(uid))
        user = user_list[0]
        is_user_admin = bool(user['is_admin'])
        admin_btn_text = "❌ Снять админа" if is_user_admin else "👑 Сделать админом"
        ban_btn_text = "✅ Разбанить" if new_status else "🚫 Забанить"
        msg = f"✅ Статус обновлен!\n\n👤 <b>Инфо</b>\n🆔 ID: <code>{user['telegram_id']}</code>\n👤 User: @{user['username'] or 'N/A'}\n🛡 Admin: <b>{'Да' if is_user_admin else 'Нет'}</b>\n🚫 Бан: <b>{'Да' if new_status else 'Нет'}</b>"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(admin_btn_text, callback_data=f"adm_toggle_admin_{uid}_{'0' if is_user_admin else '1'}")],
            [InlineKeyboardButton(ban_btn_text, callback_data=f"adm_toggle_ban_{uid}_{'0' if new_status else '1'}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="adm_users_menu")]
        ])
        await query.edit_message_text(msg, reply_markup=kb, parse_mode='HTML')
    elif data == "adm_broadcast":
        user_data['state'] = STATE_ADMIN_BROADCAST_TEXT; await query.message.reply_text("📢 Текст рассылки (HTML):")
    elif data == "adm_logs":
        try:
            with open("logs/vinted.log", "r") as f: last_lines = "".join(f.readlines()[-15:])
            await query.message.reply_text(f"📜 <b>Логи:</b>\n<pre>{last_lines}</pre>", parse_mode='HTML')
        except: await query.edit_message_text("❌ Ошибка логов.")
    elif data == "adm_settings":
        await safe_edit_message(query, "⚙️ <b>Настройки</b>", reply_markup=admin_settings_kb(), parse_mode='HTML')
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
    
    elif data == "adm_proxy_add":
        user_data['state'] = STATE_ADMIN_ADD_PROXY
        await query.message.reply_text(
            "➕ <b>Добавление прокси</b>\n\n"
            "Отправьте прокси (один или несколько, разделяя новой строкой или <code>;</code>):\n\n"
            "<b>Поддерживаемые форматы:</b>\n"
            "• <code>ip:port:user:pass</code>\n"
            "• <code>user:pass@ip:port</code>\n"
            "• <code>http://user:pass@ip:port</code>\n"
            "• <code>ip:port</code>\n\n"
            "Для отмены нажмите <b>❌ Отмена</b>.",
            parse_mode='HTML',
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True)
        )
    
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

    # --- SNIPER MENU ---
    elif data == "adm_sniper_menu":
        enabled = db.get_parameter('sniper_enabled') == 'True'
        domain = db.get_parameter('sniper_vinted_domain') or 'www.vinted.fr'
        proxy = db.get_parameter('sniper_proxy') or 'не задан'
        cookie = db.get_parameter('sniper_session_cookie') or ''
        cookie_display = f"{cookie[:20]}..." if len(cookie) > 20 else (cookie or 'не задан')
        text = (
            f"🎯 <b>AntiGravity Sniper</b>\n\n"
            f"Статус: <b>{'🟢 ВКЛ' if enabled else '🔴 ВЫКЛ'}</b>\n"
            f"Домен: <code>{domain}</code>\n"
            f"Прокси: <code>{proxy[:40]}</code>\n"
            f"Cookie: <code>{cookie_display}</code>\n"
        )
        await safe_edit_message(query, text, reply_markup=sniper_menu_kb(chat_id), parse_mode='HTML')

    elif data == "sniper_toggle":
        settings = db_tma.get_user_sniper_settings(chat_id)
        current = settings.get('enabled')
        new_val = not current
        db_tma.update_user_sniper_setting(chat_id, 'enabled', new_val)
        db.set_parameter('sniper_enabled', 'True' if new_val else 'False')
        await query.answer(f"Снайпер {'включен ✅' if new_val else 'выключен ❌'}")
        
        # Re-render menu
        settings = db_tma.get_user_sniper_settings(chat_id)
        enabled = settings.get('enabled')
        domain = settings.get('domain') or 'www.vinted.fr'
        proxy = settings.get('proxy') or 'не задан'
        cookie = settings.get('session_cookie') or ''
        cookie_display = f"{cookie[:20]}..." if len(cookie) > 20 else (cookie or 'не задан')
        
        text = (
            f"🎯 <b>AntiGravity Sniper</b>\n\n"
            f"Статус: <b>{'🟢 ВКЛ' if enabled else '🔴 ВЫКЛ'}</b>\n"
            f"Домен: <code>{domain}</code>\n"
            f"Прокси: <code>{proxy[:40]}</code>\n"
            f"Cookie: <code>{cookie_display}</code>\n\n"
            f"⚠️ Требуется до 3 минут для применения."
        )
        await safe_edit_message(query, text, reply_markup=sniper_menu_kb(chat_id), parse_mode='HTML')

    elif data == "sniper_set_proxy":
        user_data['state'] = STATE_SNIPER_SET_PROXY
        await query.message.reply_text(
            "🌐 Введите прокси для снайпера (формат: protocol://user:pass@host:port):\n\n"
            "⚠️ Используйте <b>статический ISP-прокси</b> страны аккаунта!",
            parse_mode='HTML',
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True)
        )

    elif data == "sniper_set_cookie":
        user_data['state'] = STATE_SNIPER_SET_COOKIE
        await query.message.reply_text(
            "🍪 Введите <code>_vinted_fr_session</code> cookie:\n\n"
            "Получите его из DevTools браузера (Application → Cookies).",
            parse_mode='HTML',
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True)
        )

    elif data == "sniper_set_domain":
        user_data['state'] = STATE_SNIPER_SET_DOMAIN
        await query.message.reply_text(
            "🌍 Введите домен Vinted (например: www.vinted.fr, www.vinted.de, www.vinted.pl):",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True)
        )

    elif data == "sniper_logs":
        try:
            import sqlite3
            conn = sqlite3.connect('vinted_notifications.db')
            cursor = conn.cursor()
            cursor.execute(
                "SELECT item_id, item_title, status, latency_ms, created_at "
                "FROM snipe_log WHERE target_user_id = ? ORDER BY id DESC LIMIT 10",
                (chat_id,)
            )
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                await query.edit_message_text(
                    "📊 <b>Ваши логи снайпера пусты</b>",
                    reply_markup=sniper_menu_kb(chat_id), parse_mode='HTML'
                )
            else:
                from datetime import datetime
                lines = []
                for item_id, title, status, lat, ts in rows:
                    emoji = {'reserved': '🎯', 'sold': '❌', 'error': '⚠️', 'rate_limited': '🐌', 'session_dead': '💀'}.get(status, '❓')
                    t = datetime.fromtimestamp(ts).strftime('%H:%M:%S') if ts else '??:??:??'
                    lines.append(f"{emoji} <code>{t}</code> {(title or 'N/A')[:25]} | {lat:.0f}ms")
                text = "📊 <b>Последние снайпы:</b>\n\n" + "\n".join(lines)
                await query.edit_message_text(
                    text, reply_markup=sniper_menu_kb(chat_id), parse_mode='HTML'
                )
        except Exception as e:
            await query.edit_message_text(
                f"❌ Ошибка чтения логов: {e}",
                reply_markup=sniper_menu_kb(chat_id), parse_mode='HTML'
            )

    elif data == "sniper_close":
        try:
            await query.message.delete()
        except:
            await query.edit_message_text("Закрыто.")

    elif data.startswith("edt_"):
        parts = data.split("_", 2); user_data['state'] = STATE_ADMIN_EDIT_PARAM; user_data['edit_target'] = (parts[1], parts[2])
        await query.message.reply_text(
            f"📝 Новое значение для {parts[2]}:\n\nДля отмены нажмите <b>❌ Отмена</b>.",
            parse_mode='HTML',
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True)
        )
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

# --- ЛОГИКА УВЕДОМЛЕНИЙ ---

async def notify_new_items(queue, bot, chat_ids):
    while not shutdown_event.is_set():
        try:
            if not queue.empty():
                content, url, btn_text, photo_url, buy_url, target_user_id = queue.get()
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔎 Открыть на Vinted", url=url)] + ([InlineKeyboardButton("⚡️ Быстрая покупка", url=buy_url)] if buy_url else [])])
                
                if target_user_id:
                    # Send to the user who owns the query
                    try:
                        if not db_tma.is_user_banned(target_user_id):
                            if photo_url:
                                await bot.send_photo(chat_id=target_user_id, photo=photo_url, caption=content, reply_markup=kb, parse_mode='HTML')
                            else:
                                await bot.send_message(chat_id=target_user_id, text=content, reply_markup=kb, parse_mode='HTML')
                        await asyncio.sleep(0.05)
                    except Exception as e:
                        logger.error(f"Error sending item notification to {target_user_id}: {e}")
                else:
                    # Fallback: send to all registered users
                    active_ids = db_tma.get_active_subscribers()
                    for cid in active_ids:
                        try:
                            if photo_url:
                                await bot.send_photo(chat_id=cid, photo=photo_url, caption=content, reply_markup=kb, parse_mode='HTML')
                            else:
                                await bot.send_message(chat_id=cid, text=content, reply_markup=kb, parse_mode='HTML')
                            await asyncio.sleep(0.05)
                        except Exception as e:
                            logger.error(f"Error broadcasting item to {cid}: {e}")
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error in notify_new_items: {e}")
            await asyncio.sleep(1)

def signal_handler(sig, frame): shutdown_event.set()

def run_bot_in_process(queue: multiprocessing.Queue):
    load_dotenv()
    token = os.getenv('TELEGRAM_TOKEN') or db.get_parameter('telegram_token')
    if not token:
        logger.error("TELEGRAM_TOKEN is not configured! Please set it in .env")
        return
    db.set_parameter('telegram_token', token)
    signal.signal(signal.SIGINT, signal_handler); signal.signal(signal.SIGTERM, signal_handler)
    application = Application.builder().token(token).build()

    async def admin_cmd(u, c):
        await u.message.reply_text("🛠 <b>Панель администратора</b>", reply_markup=admin_hub_kb(), parse_mode='HTML')

    async def add_proxy_cmd(u, c):
        cid = u.effective_chat.id
        if c.args:
            raw_input = " ".join(c.args)
            msg, _ = core.process_add_proxy(raw_input)
            await u.message.reply_text(msg, parse_mode='HTML')
        else:
            c.user_data['state'] = STATE_ADMIN_ADD_PROXY
            await u.message.reply_text(
                "➕ Отправьте прокси для добавления (или нажмите ❌ Отмена):",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True)
            )

    application.add_handler(CommandHandler("start", lambda u, c: start(u, c, set())))
    application.add_handler(CommandHandler("admin", admin_cmd))
    application.add_handler(CommandHandler("addproxy", add_proxy_cmd))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(callback_handler))
    async def main():
        async with application:
            await application.initialize()
            await application.start()
            asyncio.create_task(notify_new_items(queue, application.bot, set()))
            await application.updater.start_polling(drop_pending_updates=True)
            await shutdown_event.wait()
            await application.updater.stop()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())

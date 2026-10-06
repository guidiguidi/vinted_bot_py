"""
sniper/notifier.py — Telegram-уведомления для AntiGravity Sniper.

Отправляет результаты снайпа напрямую через Telegram Bot API
(минуя очередь бота для минимальной задержки).
"""

import asyncio
from typing import Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

import db
from logger import get_logger
from sniper.sniper_core import SnipeResult, SnipeStatus

logger = get_logger(__name__)


class SniperNotifier:
    """Sends snipe results to Telegram users and admins."""

    def __init__(self):
        self._bot: Optional[Bot] = None
        self._admin_ids: list = []

    async def initialize(self):
        """Initialize the Telegram bot instance."""
        token = db.get_parameter("telegram_token")
        if not token:
            logger.error("[Notifier] No telegram_token in database")
            return False

        self._bot = Bot(token=token)
        logger.info("[Notifier] Telegram bot initialized")
        return True

    def _get_admin_ids(self) -> list:
        """Get admin IDs from db_commercial."""
        try:
            import db_commercial as db_tma

            return db_tma.get_all_admin_ids()
        except Exception:
            return []

    async def notify_snipe_result(self, result: SnipeResult):
        """
        Send notification about a snipe result.

        - RESERVED → send checkout link to target user
        - SOLD → send "missed" notification to target user
        - SESSION_DEAD → alert all admins
        - ERROR/RATE_LIMITED → log only (optional admin alert)
        """
        if not self._bot:
            logger.warning("[Notifier] Bot not initialized, skipping notification")
            return

        if result.status == SnipeStatus.RESERVED:
            await self._notify_reserved(result)
        elif result.status == SnipeStatus.SOLD:
            await self._notify_missed(result)
        elif result.status == SnipeStatus.SESSION_DEAD:
            await self._alert_session_dead(result)
        elif result.status == SnipeStatus.RATE_LIMITED:
            await self._alert_admins(
                f"⚠️ <b>Sniper Rate Limited</b>\n\n"
                f"Товар: {result.title}\n"
                f"ID: <code>{result.item_id}</code>\n"
                f"Время: {result.latency_ms:.0f}ms"
            )

    async def _notify_reserved(self, result: SnipeResult):
        """Send success notification with checkout link."""
        if not result.target_user_id:
            logger.warning("[Notifier] No target_user_id for reserved item")
            return

        text = (
            f"🎯 <b>Товар забронирован!</b>\n\n"
            f"📦 <b>{result.title}</b>\n"
            f"💶 Цена: <b>{result.price} {result.currency}</b>\n"
            f"⏱ Время реакции: <b>{result.latency_ms:.0f}ms</b>\n\n"
            f"⚠️ У вас ~10 минут на оплату!"
        )

        kb = None
        if result.checkout_url:
            kb = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "💳 Оплатить сейчас", url=result.checkout_url
                        )
                    ]
                ]
            )

        try:
            await self._bot.send_message(
                chat_id=result.target_user_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML",
            )
            logger.info(
                f"[Notifier] ✅ Sent reservation link to user {result.target_user_id}"
            )
        except Exception as e:
            logger.error(
                f"[Notifier] Failed to send to user {result.target_user_id}: {e}"
            )

        # Also notify admins
        await self._alert_admins(
            f"🎯 <b>SNIPE HIT!</b>\n\n"
            f"📦 {result.title}\n"
            f"💶 {result.price} {result.currency}\n"
            f"⏱ {result.latency_ms:.0f}ms\n"
            f"👤 User: <code>{result.target_user_id}</code>\n"
            f"🔗 {result.checkout_url or 'N/A'}"
        )

    async def _notify_missed(self, result: SnipeResult):
        """Send 'missed' notification to user."""
        if not result.target_user_id:
            return

        text = (
            f"❌ <b>Не успели</b>\n\n"
            f"📦 {result.title}\n"
            f"💶 Цена: {result.price} {result.currency}\n"
            f"⏱ Время: {result.latency_ms:.0f}ms\n"
            f"Причина: {result.error_detail or 'Товар уже продан'}"
        )

        try:
            await self._bot.send_message(
                chat_id=result.target_user_id,
                text=text,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"[Notifier] Failed to send miss to {result.target_user_id}: {e}")

    async def _alert_session_dead(self, result: SnipeResult):
        """Alert the user that their sniper session is dead."""
        text = (
            f"🚨 <b>ВАШ SNIPER SESSION УМЕР!</b>\n\n"
            f"Сессия вашего Vinted-аккаунта истекла.\n"
            f"Снайпер остановлен.\n\n"
            f"Последний запрос: item {result.item_id}\n"
            f"Ошибка: {result.error_detail}\n\n"
            f"🔧 Зайдите в меню '🎯 Мой Снайпер', обновите <code>cookie</code> и включите его заново."
        )
        if result.target_user_id:
            try:
                await self._bot.send_message(
                    chat_id=result.target_user_id, text=text, parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"[Notifier] Failed to alert user {result.target_user_id} of session death: {e}")
        else:
            await self._alert_admins(text)

    async def _alert_admins(self, text: str):
        """Send a message to all admin users."""
        if not self._bot:
            return

        admin_ids = self._get_admin_ids()
        for aid in admin_ids:
            try:
                await self._bot.send_message(
                    chat_id=aid, text=text, parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"[Notifier] Failed to alert admin {aid}: {e}")
            await asyncio.sleep(0.05)

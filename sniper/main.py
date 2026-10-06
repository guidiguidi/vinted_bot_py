"""
sniper/main.py — Точка входа AntiGravity Sniper.

Запускает все компоненты снайпера:
1. SessionManager — горячая сессия Vinted
2. Keep-alive loop — поддержание сессии
3. Redis subscriber — приём триггеров от парсера
4. SniperCore — резервация товаров
5. SniperNotifier — уведомления в Telegram
"""

import asyncio
import time

import db
from logger import get_logger
from sniper.notifier import SniperNotifier
from sniper.redis_bus import is_redis_available, subscribe_snipe_triggers
from sniper.session_manager import MultiSessionManager
from sniper.sniper_core import SniperCore, SnipeStatus

logger = get_logger(__name__)


async def run_sniper():
    """
    Main async entry point for the AntiGravity Multi-Account Sniper.
    Blocks until shutdown or fatal error.
    """
    logger.info("=" * 50)
    logger.info("[AntiGravity] 🚀 Multi-Account Sniper starting...")
    logger.info("=" * 50)

    # ----- 1. Check Redis -----
    if not is_redis_available():
        logger.error(
            "[AntiGravity] Redis is not available! "
            "Sniper requires Redis for IPC. Exiting."
        )
        return

    logger.info("[AntiGravity] Redis connection: OK ✅")

    # ----- 2. Initialize Session Manager -----
    sm = MultiSessionManager()
    await sm.initialize()

    # ----- 3. Start keep-alive loop -----
    await sm.start_keep_alive()

    # ----- 4. Initialize Sniper Core -----
    sniper = SniperCore(sm)

    # ----- 5. Initialize Notifier -----
    notifier = SniperNotifier()
    notifier_ok = await notifier.initialize()
    if not notifier_ok:
        logger.warning(
            "[AntiGravity] Notifier init failed. "
            "Sniper will work but won't send Telegram messages."
        )

    # ----- 6. Main loop: listen to Redis triggers -----
    logger.info("[AntiGravity] 🎯 Sniper armed and listening for triggers...")

    try:
        async for payload in subscribe_snipe_triggers():
            # The master global switch can still disable ALL sniping
            if db.get_parameter("sniper_enabled") != "True":
                logger.debug("[AntiGravity] Master Sniper switch is OFF. Ignoring trigger.")
                continue

            # Execute snipe (SniperCore will check if user's personal sniper is enabled)
            try:
                # We do this asynchronously to avoid blocking the trigger loop for other users
                asyncio.create_task(_process_snipe(sniper, notifier, payload, notifier_ok))

            except Exception as e:
                logger.error(f"[AntiGravity] Error scheduling snipe: {e}", exc_info=True)

    except asyncio.CancelledError:
        logger.info("[AntiGravity] Sniper cancelled")
    except Exception as e:
        logger.error(f"[AntiGravity] Fatal error: {e}", exc_info=True)
    finally:
        await sm.stop_keep_alive()
        logger.info("[AntiGravity] 🛑 Sniper stopped")

async def _process_snipe(sniper, notifier, payload, notifier_ok):
    try:
        result = await sniper.snipe(payload)
        # Send notification
        if notifier_ok and result:
            await notifier.notify_snipe_result(result)
            
        # Rate limits only affect the specific user now, we don't globally sleep.
    except Exception as e:
        logger.error(f"[AntiGravity] Snipe task error: {e}", exc_info=True)

def sniper_entry():
    """
    Synchronous entry point for multiprocessing.Process.
    Called from vinted_notifications.py.
    """
    # Check if global master switch is enabled
    enabled = db.get_parameter("sniper_enabled")
    if enabled != "True":
        logger.info("[AntiGravity] Sniper master switch is disabled (sniper_enabled != True). Exiting.")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_sniper())
    except KeyboardInterrupt:
        logger.info("[AntiGravity] Sniper interrupted by keyboard")
    finally:
        loop.close()

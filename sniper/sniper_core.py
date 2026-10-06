"""
sniper/sniper_core.py — Ядро резервации AntiGravity Sniper.

Получает триггер (item_id) от Redis, отправляет POST-запрос на резервацию
товара через авторизованную сессию Vinted, обрабатывает ответ.
"""

import asyncio
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from logger import get_logger
from sniper.session_manager import MultiSessionManager

logger = get_logger(__name__)

DB_PATH = "vinted_notifications.db"


class SnipeStatus(Enum):
    RESERVED = "reserved"
    SOLD = "sold"
    RATE_LIMITED = "rate_limited"
    SESSION_DEAD = "session_dead"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class SnipeResult:
    """Result of a snipe attempt."""

    item_id: str
    status: SnipeStatus
    latency_ms: float = 0.0
    checkout_url: Optional[str] = None
    transaction_id: Optional[str] = None
    error_detail: Optional[str] = None
    # Original payload data for notifications
    title: str = ""
    price: str = ""
    currency: str = "EUR"
    photo_url: str = ""
    target_user_id: Optional[int] = None


class SniperCore:
    """
    Core sniper logic. Receives item triggers, sends reservation requests,
    processes responses.
    """

    def __init__(self, session_manager: MultiSessionManager):
        self._sm = session_manager

    async def snipe(self, payload: dict) -> Optional[SnipeResult]:
        """
        Execute a snipe attempt for the given item payload.

        Args:
            payload: Dict with item_id, price, currency, title, url, photo_url,
                     target_user_id, query_id, ts_found

        Returns:
            SnipeResult with status and details, or None if skipped.
        """
        item_id = str(payload.get("item_id", ""))
        title = payload.get("title", "")
        price = payload.get("price", "0")
        currency = payload.get("currency", "EUR")
        photo_url = payload.get("photo_url", "")
        target_user_id = payload.get("target_user_id")
        ts_found = payload.get("ts_found", 0)

        if not target_user_id:
            logger.debug(f"[Sniper] Missing target_user_id for item {item_id}, skipping")
            return None

        # Calculate time since parser found the item
        pipeline_delay = (time.time() - ts_found) * 1000 if ts_found else 0

        # Get user session
        user_session = await self._sm.get_user_session(target_user_id)
        if not user_session:
            # User doesn't have sniper enabled or configured
            return None

        logger.info(
            f"[Sniper] ⚡ Trigger received: item_id={item_id} | "
            f"user={target_user_id} | delay: {pipeline_delay:.0f}ms"
        )

        # Check session is alive
        session, csrf_token = await user_session.get_session_data()
        if session is None or not user_session.is_alive:
            logger.error(f"[Sniper] Session dead for user {target_user_id}, cannot snipe")
            return SnipeResult(
                item_id=item_id,
                status=SnipeStatus.SESSION_DEAD,
                error_detail="Session not initialized or dead",
                title=title,
                price=price,
                currency=currency,
                photo_url=photo_url,
                target_user_id=target_user_id,
            )

        domain = user_session.domain

        # ---- BUILD REQUEST ----
        url = f"https://{domain}/api/v2/transactions"
        headers = {
            "X-CSRF-Token": csrf_token or "",
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        }
        body = {
            "item_id": int(item_id),
            "source_screen": "item",
        }

        # ---- FIRE ----
        ts_start = time.perf_counter()
        try:
            response = await asyncio.to_thread(
                session.post,
                url,
                json=body,
                headers=headers,
            )
            ts_end = time.perf_counter()
            latency_ms = (ts_end - ts_start) * 1000

        except Exception as e:
            ts_end = time.perf_counter()
            latency_ms = (ts_end - ts_start) * 1000
            logger.error(f"[Sniper] Network error after {latency_ms:.0f}ms: {e}")
            result = SnipeResult(
                item_id=item_id,
                status=SnipeStatus.ERROR,
                latency_ms=latency_ms,
                error_detail=str(e),
                title=title,
                price=price,
                currency=currency,
                photo_url=photo_url,
                target_user_id=target_user_id,
            )
            self._log_to_db(result)
            return result

        # ---- PROCESS RESPONSE ----
        status_code = response.status_code
        logger.info(
            f"[Sniper] Response: HTTP {status_code} | {latency_ms:.0f}ms | "
            f"item_id={item_id}"
        )

        if status_code in (200, 201):
            # SUCCESS — item reserved
            result = await self._handle_success(
                response, item_id, latency_ms, title, price, currency,
                photo_url, target_user_id, domain
            )
        elif status_code == 422:
            # Item already sold or unavailable
            result = self._handle_sold(
                response, item_id, latency_ms, title, price, currency,
                photo_url, target_user_id
            )
        elif status_code == 429:
            # Rate limited
            result = SnipeResult(
                item_id=item_id,
                status=SnipeStatus.RATE_LIMITED,
                latency_ms=latency_ms,
                error_detail="Rate limited by Vinted",
                title=title,
                price=price,
                currency=currency,
                photo_url=photo_url,
                target_user_id=target_user_id,
            )
            logger.warning(f"[Sniper] RATE LIMITED on item {item_id}")
        elif status_code in (401, 403):
            # Session dead
            result = SnipeResult(
                item_id=item_id,
                status=SnipeStatus.SESSION_DEAD,
                latency_ms=latency_ms,
                error_detail=f"HTTP {status_code} — session expired",
                title=title,
                price=price,
                currency=currency,
                photo_url=photo_url,
                target_user_id=target_user_id,
            )
            logger.error(f"[Sniper] SESSION DEAD: HTTP {status_code}")
        else:
            # Unknown error
            body_text = ""
            try:
                body_text = response.text[:500]
            except Exception:
                pass
            result = SnipeResult(
                item_id=item_id,
                status=SnipeStatus.ERROR,
                latency_ms=latency_ms,
                error_detail=f"HTTP {status_code}: {body_text}",
                title=title,
                price=price,
                currency=currency,
                photo_url=photo_url,
                target_user_id=target_user_id,
            )
            logger.error(
                f"[Sniper] Unexpected HTTP {status_code} for item {item_id}: "
                f"{body_text[:200]}"
            )

        self._log_to_db(result)
        return result

    async def _handle_success(
        self, response, item_id, latency_ms, title, price, currency,
        photo_url, target_user_id, domain
    ) -> SnipeResult:
        """Parse successful reservation response."""
        checkout_url = None
        transaction_id = None

        try:
            data = response.json()

            # Try to extract transaction/checkout info from response
            # Vinted API response structure may vary
            transaction = data.get("transaction", data)
            transaction_id = str(
                transaction.get("id")
                or transaction.get("transaction_id")
                or transaction.get("checkout_id")
                or ""
            )

            # Build checkout URL
            if transaction_id:
                checkout_url = f"https://{domain}/transaction/pay/{transaction_id}"
            else:
                # Fallback: generic buy URL
                checkout_url = (
                    f"https://{domain}/transaction/buy/new"
                    f"?source_screen=item&transaction%5Bitem_id%5D={item_id}"
                )

        except Exception as e:
            logger.warning(f"[Sniper] Could not parse success response: {e}")
            # Still a success, just build fallback URL
            checkout_url = (
                f"https://{domain}/transaction/buy/new"
                f"?source_screen=item&transaction%5Bitem_id%5D={item_id}"
            )

        logger.info(
            f"[Sniper] 🎯 RESERVED item {item_id} in {latency_ms:.0f}ms! "
            f"Checkout: {checkout_url}"
        )

        return SnipeResult(
            item_id=item_id,
            status=SnipeStatus.RESERVED,
            latency_ms=latency_ms,
            checkout_url=checkout_url,
            transaction_id=transaction_id,
            title=title,
            price=price,
            currency=currency,
            photo_url=photo_url,
            target_user_id=target_user_id,
        )

    def _handle_sold(
        self, response, item_id, latency_ms, title, price, currency,
        photo_url, target_user_id
    ) -> SnipeResult:
        """Handle 422 — item already sold or unavailable."""
        detail = ""
        try:
            data = response.json()
            detail = str(data.get("message") or data.get("error") or data)[:200]
        except Exception:
            try:
                detail = response.text[:200]
            except Exception:
                detail = "Unknown 422 error"

        logger.info(f"[Sniper] ❌ MISS item {item_id} ({latency_ms:.0f}ms): {detail}")

        return SnipeResult(
            item_id=item_id,
            status=SnipeStatus.SOLD,
            latency_ms=latency_ms,
            error_detail=detail,
            title=title,
            price=price,
            currency=currency,
            photo_url=photo_url,
            target_user_id=target_user_id,
        )

    def _log_to_db(self, result: SnipeResult):
        """Write snipe result to snipe_log table."""
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO snipe_log
                    (item_id, item_title, price, currency, status,
                     latency_ms, checkout_url, target_user_id, error_detail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.item_id,
                    result.title,
                    float(result.price) if result.price else 0,
                    result.currency,
                    result.status.value,
                    result.latency_ms,
                    result.checkout_url,
                    result.target_user_id,
                    result.error_detail,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"[Sniper] DB log failed (non-fatal): {e}")

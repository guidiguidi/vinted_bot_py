"""
sniper/session_manager.py — Менеджер сессий Vinted для AntiGravity Sniper.

Держит «горячие» авторизованные сессии через tls_client с JA3-мимикрией
под Chrome для каждого пользователя с включенным снайпером.
Периодически обновляет cookies и CSRF-токен через keep-alive запросы.
"""

import asyncio
import re
import time
from typing import Optional, Tuple, Dict

import tls_client

import db_commercial as db_tma
from logger import get_logger

logger = get_logger(__name__)

# Keep-alive interval in seconds
KEEP_ALIVE_INTERVAL = 180  # 3 minutes

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

class UserSession:
    """Represents a single user's authenticated Vinted session."""
    def __init__(self, user_id: int, settings: dict):
        self.user_id = user_id
        self._session: Optional[tls_client.Session] = None
        self._csrf_token: Optional[str] = None
        self._cookies: dict = {}
        self._lock = asyncio.Lock()
        self._alive = False
        
        self.domain = settings.get("domain", "www.vinted.fr")
        self.proxy = settings.get("proxy")
        self.session_cookie = settings.get("session_cookie")

    async def initialize(self) -> bool:
        async with self._lock:
            if not self.session_cookie:
                logger.error(f"[SessionManager] No session cookie for user {self.user_id}")
                return False

            self._session = tls_client.Session(
                client_identifier="chrome_124",
                random_tls_extension_order=True,
            )

            if self.proxy:
                self._session.proxies = {"http": self.proxy, "https": self.proxy}

            self._session.headers.update({
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Host": self.domain,
                "Origin": f"https://{self.domain}",
                "Referer": f"https://{self.domain}/",
            })

            self._session.cookies.set(
                "_vinted_fr_session",
                self.session_cookie,
                domain=f".{self.domain.replace('www.', '')}",
            )

            is_valid = await self._validate_session()
            if is_valid:
                self._alive = True
                logger.info(f"[SessionManager] Session OK for user {self.user_id}")
            else:
                logger.error(f"[SessionManager] Validation failed for user {self.user_id}")

            return is_valid

    async def _validate_session(self) -> bool:
        try:
            url = f"https://{self.domain}/api/v2/users/current"
            response = await asyncio.to_thread(self._session.get, url)

            if response.status_code == 200:
                self._update_csrf(response)
                self._update_cookies_from_response(response)
                return True
            return False
        except Exception as e:
            logger.error(f"[SessionManager] Validation error for user {self.user_id}: {e}")
            return False

    def _update_csrf(self, response):
        for cookie in self._session.cookies:
            if "csrf" in cookie.name.lower():
                self._csrf_token = cookie.value
                return
        try:
            match = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', response.text)
            if match:
                self._csrf_token = match.group(1)
        except Exception:
            pass

    def _update_cookies_from_response(self, response):
        for cookie in self._session.cookies:
            self._cookies[cookie.name] = cookie.value
            if cookie.name == "_vinted_fr_session":
                if cookie.value != self.session_cookie:
                    self.session_cookie = cookie.value
                    db_tma.update_user_sniper_setting(self.user_id, "session_cookie", cookie.value)
                    logger.info(f"[SessionManager] Auto-updated _vinted_fr_session for user {self.user_id}")

    async def keep_alive(self) -> bool:
        async with self._lock:
            if not self._session or not self._alive:
                return False
            try:
                url = f"https://{self.domain}/api/v2/users/current"
                response = await asyncio.to_thread(self._session.get, url)
                if response.status_code == 200:
                    self._update_csrf(response)
                    self._update_cookies_from_response(response)
                    return True
                elif response.status_code in (401, 403):
                    self._alive = False
                    # Disable in DB
                    db_tma.update_user_sniper_setting(self.user_id, "enabled", False)
                    logger.error(f"[SessionManager] Session DEAD for user {self.user_id}. Disabled.")
                    return False
            except Exception as e:
                logger.warning(f"[SessionManager] Keep-alive error user {self.user_id}: {e}")
            return self._alive

    async def get_session_data(self) -> Tuple[Optional[tls_client.Session], Optional[str]]:
        async with self._lock:
            if not self._alive:
                return None, None
            return self._session, self._csrf_token

    @property
    def is_alive(self) -> bool:
        return self._alive

class MultiSessionManager:
    """Manages multiple UserSessions."""
    def __init__(self):
        self.sessions: Dict[int, UserSession] = {}
        self._keep_alive_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """Initial sync."""
        await self.sync_users()

    async def get_user_session(self, user_id: int) -> Optional[UserSession]:
        """Get or initialize a user session on demand."""
        if user_id in self.sessions and self.sessions[user_id].is_alive:
            return self.sessions[user_id]
        
        # Check if enabled
        settings = db_tma.get_user_sniper_settings(user_id)
        if not settings.get("enabled"):
            return None

        # Initialize
        us = UserSession(user_id, settings)
        ok = await us.initialize()
        if ok:
            self.sessions[user_id] = us
            return us
        else:
            # If init fails, disable them
            db_tma.update_user_sniper_setting(user_id, "enabled", False)
            return None

    async def sync_users(self):
        """Synchronize active sessions with DB."""
        enabled_ids = db_tma.get_all_enabled_snipers()
        
        # Remove disabled
        for uid in list(self.sessions.keys()):
            if uid not in enabled_ids:
                del self.sessions[uid]
                logger.info(f"[SessionManager] Removed session for user {uid}")

        # Add new
        for uid in enabled_ids:
            if uid not in self.sessions or not self.sessions[uid].is_alive:
                settings = db_tma.get_user_sniper_settings(uid)
                us = UserSession(uid, settings)
                ok = await us.initialize()
                if ok:
                    self.sessions[uid] = us
                else:
                    db_tma.update_user_sniper_setting(uid, "enabled", False)

    async def start_keep_alive(self):
        if self._keep_alive_task is None:
            self._keep_alive_task = asyncio.create_task(self._keep_alive_loop())
            logger.info("[SessionManager] Global keep-alive loop started")

    async def stop_keep_alive(self):
        if self._keep_alive_task:
            self._keep_alive_task.cancel()
            try:
                await self._keep_alive_task
            except asyncio.CancelledError:
                pass
            self._keep_alive_task = None

    async def _keep_alive_loop(self):
        while True:
            try:
                await asyncio.sleep(KEEP_ALIVE_INTERVAL)
                await self.sync_users()
                
                # Keep alive all active
                for uid, session in list(self.sessions.items()):
                    alive = await session.keep_alive()
                    if not alive:
                        del self.sessions[uid]
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[SessionManager] Loop error: {e}")
                await asyncio.sleep(10)

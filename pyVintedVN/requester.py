import os
import sys
import json
import random
import re
import time
import urllib.parse
from typing import Optional, Dict, Any, Union

import tls_client
from requests.exceptions import HTTPError, ProxyError, RequestException

import configuration_values
import proxies

# Add the parent directory to sys.path to import logger
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import get_logger

logger = get_logger(__name__)


class VintedResponse:
    """
    Wrapper around HTTP responses ensuring compatibility with requests.Response
    (status_code, json(), text, content, headers, cookies, url, raise_for_status()).
    """
    def __init__(
        self,
        raw_resp: Any = None,
        status_code: int = 200,
        json_data: Any = None,
        text: str = "",
        url: str = "",
        headers: Optional[Dict[str, str]] = None,
        cookies: Optional[Dict[str, str]] = None,
    ):
        self.raw = raw_resp
        self.status_code = raw_resp.status_code if raw_resp is not None else status_code
        self.url = getattr(raw_resp, "url", url)
        self.headers = getattr(raw_resp, "headers", headers or {})
        self.cookies = getattr(raw_resp, "cookies", cookies or {})
        self._json_data = json_data

        if raw_resp is not None:
            self.text = raw_resp.text
            self.content = raw_resp.content
        else:
            self.text = text or (json.dumps(json_data, ensure_ascii=False) if json_data is not None else "")
            self.content = self.text.encode("utf-8")

    def json(self) -> Any:
        if self._json_data is not None:
            return self._json_data
        if self.raw is not None:
            return self.raw.json()
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 500:
            raise HTTPError(f"{self.status_code} Client Error for url: {self.url}", response=self)
        elif 500 <= self.status_code < 600:
            raise HTTPError(f"{self.status_code} Server Error for url: {self.url}", response=self)


class Requester:
    """
    A class for handling HTTP requests to Vinted with TLS fingerprint spoofing,
    session warmup, sticky proxies, and automatic re-authentication.
    """

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    CLIENT_IDENTIFIER = "chrome_120"

    def __init__(self, debug: bool = False):
        self.debug = debug
        self.locale = "www.vinted.fr"
        self.VINTED_AUTH_URL = f"https://{self.locale}/"
        self.MAX_RETRIES = 3

        # Proxies
        self.proxies: Optional[Union[dict, str]] = None  # Manual override
        self.current_proxy: Optional[dict] = None  # Sticky proxy currently bound

        # Session warmup tracking per domain
        self._warmed_locales = set()

        # Browser headers
        self.user_agent = self.DEFAULT_USER_AGENT
        self.HEADER = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        self._session = None
        self._session_pid = None

    @property
    def session(self) -> tls_client.Session:
        current_pid = os.getpid()
        if getattr(self, "_session_pid", None) != current_pid or getattr(self, "_session", None) is None:
            self._init_session(rotate_proxy=False)
        return self._session

    @session.setter
    def session(self, value):
        self._session = value
        self._session_pid = os.getpid()

    def _resolve_proxy(self) -> Optional[dict]:
        """Dynamically resolve sticky proxy from manual setting or proxy list."""
        if self.proxies:
            if isinstance(self.proxies, str):
                return proxies.convert_proxy_string_to_dict(self.proxies)
            return self.proxies
        new_p = proxies.get_random_proxy()
        return proxies.convert_proxy_string_to_dict(new_p) if new_p else None

    def _init_session(self, rotate_proxy: bool = False) -> None:
        """
        Initialize or reset the underlying tls-client session, binding to a sticky proxy.
        """
        self._session_pid = os.getpid()
        if rotate_proxy or self.current_proxy is None:
            self.current_proxy = self._resolve_proxy()
            if self.current_proxy:
                logger.info(f"[Requester (PID {self._session_pid})] Bound to sticky proxy: {self.current_proxy}")

        self._session = tls_client.Session(
            client_identifier=self.CLIENT_IDENTIFIER,
            random_tls_extension_order=True,
        )

        if self.current_proxy:
            self._session.proxies = self.current_proxy
        else:
            self._session.proxies = {}

        self._session.headers.update(self.HEADER)
        self._warmed_locales.clear()

    def set_locale(self, locale: str) -> None:
        """
        Update locale and authentication URL.
        """
        if not locale:
            locale = "www.vinted.fr"
        self.locale = locale
        self.VINTED_AUTH_URL = f"https://{locale}/"
        if self.debug:
            logger.debug(f"[Requester] Locale updated to {locale}")

    def _get_lang_for_domain(self, domain: str) -> str:
        d = domain.lower()
        if d.endswith(".fr"):
            return "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"
        elif d.endswith(".de"):
            return "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
        elif d.endswith(".pl"):
            return "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7"
        elif d.endswith(".it"):
            return "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"
        elif d.endswith(".be"):
            return "fr-BE,nl-BE,fr;q=0.9,en-US;q=0.8,en;q=0.7"
        elif d.endswith(".at"):
            return "de-AT,de;q=0.9,en-US;q=0.8,en;q=0.7"
        elif d.endswith(".co.uk"):
            return "en-GB,en;q=0.9,en-US;q=0.8"
        return "en-US,en;q=0.9"

    def _get_warmup_headers(self, domain: Optional[str] = None) -> Dict[str, str]:
        domain = domain or self.locale
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": self._get_lang_for_domain(domain),
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }

    def _get_api_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": self._get_lang_for_domain(self.locale),
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Referer": referer or f"https://{self.locale}/catalog",
        }
        token = self.session.cookies.get("access_token_web")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _get_rsc_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/x-component",
            "Accept-Language": self._get_lang_for_domain(self.locale),
            "RSC": "1",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Referer": referer or f"https://{self.locale}/catalog",
        }

    def warmup_domain(self, domain: Optional[str] = None, force: bool = False) -> None:
        """
        Execute session warmup GET request to Vinted domain homepage,
        extracting and persisting domain session cookies.
        """
        domain = domain or self.locale
        if not domain:
            domain = "www.vinted.fr"

        if domain in self._warmed_locales and not force:
            return

        headers = self._get_warmup_headers(domain)
        auth_url = f"https://{domain}/"
        try:
            resp = self.session.get(auth_url, headers=headers, allow_redirects=True, timeout_seconds=15)
            self._warmed_locales.add(domain)
            cookie_names = list(self.session.cookies.keys())
            logger.info(f"[Requester] Domain {domain} warmed up (HTTP {resp.status_code}), cookies: {cookie_names}")
        except Exception as e:
            logger.warning(f"[Requester] Error during session warmup GET to {auth_url}: {e}")

    def set_cookies(self, force: bool = False) -> None:
        """
        Execute session warmup for current locale.
        """
        self.warmup_domain(self.locale, force=force)

    def _fetch_catalog_items(self, target_url: str, params: Optional[dict] = None) -> VintedResponse:
        """
        Fetch catalog items using Next.js App Router (RSC / catalog) endpoint,
        extracting the items JSON payload.
        """
        parsed = urllib.parse.urlparse(target_url)
        netloc = parsed.netloc or self.locale
        query_dict = dict(urllib.parse.parse_qsl(parsed.query))
        if params:
            query_dict.update({k: v for k, v in params.items() if v is not None and v != ""})

        # Remove internal api params that are not query filters
        query_dict.pop("time", None)

        query_str = urllib.parse.urlencode(query_dict, doseq=True)
        catalog_url = f"https://{netloc}/catalog"
        if query_str:
            catalog_url += f"?{query_str}"

        headers = self._get_rsc_headers(referer=catalog_url)
        raw_resp = self.session.get(catalog_url, headers=headers, allow_redirects=True, timeout_seconds=15)

        if raw_resp.status_code in (401, 403):
            return VintedResponse(raw_resp=raw_resp, url=catalog_url)

        if raw_resp.status_code == 200:
            text = raw_resp.text
            # Primary extraction from Next.js payload: "items":{"items":([...]),"pagination"
            m = re.search(r'"items":\{"items":(\[.*?\]),"pagination"', text)
            if m:
                try:
                    items_list = json.loads(m.group(1))
                    return VintedResponse(
                        raw_resp=raw_resp,
                        status_code=200,
                        json_data={"items": items_list},
                        url=catalog_url,
                    )
                except Exception as e:
                    logger.warning(f"[Requester] Failed to json decode extracted items: {e}")

            # Secondary fallback: search for items array
            m2 = re.search(r'"items":(\[\{"id":\d+,"productItem":.*?\}\])', text)
            if m2:
                try:
                    items_list = json.loads(m2.group(1))
                    return VintedResponse(
                        raw_resp=raw_resp,
                        status_code=200,
                        json_data={"items": items_list},
                        url=catalog_url,
                    )
                except Exception:
                    pass

        return VintedResponse(raw_resp=raw_resp, url=catalog_url)

    def get(self, url: str, params: Optional[dict] = None) -> VintedResponse:
        """
        Make a GET request with retry and automatic session re-auth logic.
        """
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc or self.locale
        if netloc and netloc != self.locale:
            self.set_locale(netloc)

        if netloc not in self._warmed_locales:
            self.warmup_domain(netloc)

        is_catalog_request = ("catalog/items" in url) or (parsed.path.rstrip("/") == "/catalog" and "users" not in url)

        tried = 0
        direct_fallback_used = False

        while tried < self.MAX_RETRIES:
            tried += 1
            try:
                if is_catalog_request:
                    response = self._fetch_catalog_items(url, params)
                else:
                    headers = self._get_api_headers()
                    raw = self.session.get(url, params=params, headers=headers, allow_redirects=True, timeout_seconds=15)
                    response = VintedResponse(raw_resp=raw, url=url)

                # Check for 401 or 403 (Cloudflare / Datadome block or expired session)
                if response.status_code in (401, 403):
                    logger.warning(
                        f"[Requester] Received HTTP {response.status_code} on attempt {tried}/{self.MAX_RETRIES} for {netloc}. "
                        f"Refreshing cookies and rotating session..."
                    )
                    if tried < self.MAX_RETRIES:
                        # Reset session, rotate sticky proxy, and execute warmup GET for netloc
                        self._init_session(rotate_proxy=True)
                        self.warmup_domain(netloc, force=True)
                        time.sleep(1)
                        continue
                    else:
                        return response

                if response.status_code == 200:
                    return response

                if tried == self.MAX_RETRIES:
                    return response

            except Exception as e:
                err_text = str(e).upper()
                is_proxy_issue = ("407" in err_text) or ("NO_USER" in err_text) or ("PROXY" in err_text)
                logger.warning(f"[Requester] Request failed (attempt {tried}/{self.MAX_RETRIES}): {e}")

                if is_proxy_issue and not self.proxies and not direct_fallback_used:
                    direct_fallback_used = True
                    logger.warning("[Requester] Proxy error encountered. Retrying with fresh session without broken proxy.")
                    self._init_session(rotate_proxy=True)
                    self.set_cookies(force=True)
                    continue

                if tried == self.MAX_RETRIES:
                    raise HTTPError(f"Request failed after {self.MAX_RETRIES} attempts: {e}")

                time.sleep(1)

        raise HTTPError(f"Failed to get a valid response after {self.MAX_RETRIES} attempts for url: {url}")

    def post(self, url: str, params: Optional[dict] = None) -> VintedResponse:
        """
        Make a POST request with TLS-spoofed headers and proxy.
        """
        if not self._warmed_up:
            self.set_cookies()

        headers = self._get_api_headers()
        raw = self.session.post(url, data=params, headers=headers, allow_redirects=True, timeout_seconds=15)
        resp = VintedResponse(raw_resp=raw, url=url)
        resp.raise_for_status()
        return resp

    def update_cookies(self, cookies: dict) -> None:
        """
        Update session cookies with the provided dictionary.
        """
        self.session.cookies.update(cookies)
        if self.debug:
            logger.debug(f"[Requester] Cookies manually updated ({len(cookies)} cookies received)")

    # Backward compatibility aliases
    setLocale = set_locale
    setCookies = set_cookies


# Global singleton requester instance
requester = Requester()

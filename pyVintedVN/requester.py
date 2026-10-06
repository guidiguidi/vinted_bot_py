import requests
import random
import time
from requests.exceptions import HTTPError, ProxyError, RequestException
import configuration_values
import proxies
import sys
import os

# Add the parent directory to sys.path to import logger
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import get_logger

# Get logger for this module
logger = get_logger(__name__)


class Requester:
    """
    A class for handling HTTP requests to Vinted.

    This class manages session headers, cookies, and provides methods for making
    HTTP requests with retry logic for handling authentication issues.
    """

    def __init__(self, debug=False):
        """
        Initialize the Requester with default headers and session.

        Sets up the request headers with a randomly selected User-Agent,
        initializes the session, and configures default settings.

        Args:
            debug (bool, optional): Whether to print debug messages. Defaults to False.
        """

        self.HEADER = {
            # Grabs a user agent from the configuration values
            "User-Agent": random.choice(configuration_values.USER_AGENTS),
            **configuration_values.DEFAULT_HEADERS,
            "Host": "www.vinted.fr",
            "Accept-Encoding": "gzip, deflate",
        }
        self.VINTED_AUTH_URL = "https://www.vinted.fr/"
        self.MAX_RETRIES = 3
        self.session = requests.Session()
        self.session.headers.update(self.HEADER)
        self.debug = debug
        self.proxies = None # Allow manual proxy override

        if self.debug:
            logger.debug(f"Using User-Agent: {self.HEADER['User-Agent']}")

    def set_locale(self, locale):
        """
        Set the locale of the requester.

        Updates the authentication URL and headers to use the specified locale.

        Args:
            locale (str): The locale domain to use (e.g., 'www.vinted.fr', 'www.vinted.de')
        """
        self.VINTED_AUTH_URL = f"https://{locale}/"
        self.HEADER = {
            "User-Agent": random.choice(configuration_values.USER_AGENTS),
            **configuration_values.DEFAULT_HEADERS,
            "Host": f"{locale}",
            "Accept-Encoding": "gzip, deflate",
        }
        self.session.headers.update(self.HEADER)
        if self.debug:
            logger.debug(f"Locale set to {locale} with User-Agent: {self.HEADER['User-Agent']}")

    def get(self, url, params=None):
        """
        Make a GET request with retry logic.

        If a 401 status code is received, it will attempt to refresh cookies
        and retry the request up to MAX_RETRIES times.

        Args:
            url (str): The URL to request
            params (dict, optional): Query parameters for the request

        Returns:
            requests.Response: The response object if successful

        Raises:
            HTTPError: If the request fails after all retries
        """

        tried = 0
        new_session = False
        direct_fallback_used = False
        while tried < self.MAX_RETRIES:
            tried += 1
            try:
                # Reconfigure proxy on every attempt so we can rotate away from bad proxies.
                if self.proxies:
                    self.session.proxies.clear()
                    self.session.proxies.update(self.proxies)
                else:
                    if direct_fallback_used:
                        self.session.proxies.clear()
                    else:
                        proxy_configured = proxies.configure_proxy(self.session)
                        if self.debug and proxy_configured:
                            logger.debug(f"Using proxy: {self.session.proxies}")

                response = self.session.get(url, params=params)
                
                if response.status_code in (401, 404) and tried < self.MAX_RETRIES:
                    print(f"Cookies invalid, retrying {tried}/{self.MAX_RETRIES}")
                    if self.debug:
                        logger.debug(f"Cookies invalid retrying {tried}/{self.MAX_RETRIES}")
                    self.set_cookies()
                elif response.status_code == 200:
                    return response
                elif tried == self.MAX_RETRIES:
                    # If we've reached max retries, return the last response
                    # even if it's not a 200 status code

                    # New try : if we still get a 401, we reset the session
                    if response.status_code in (401, 403) and not new_session:
                        new_session = True
                        self.session = requests.Session()
                        self.session.headers.update(self.HEADER)
                        # proxy
                        if self.proxies:
                            self.session.proxies.update(self.proxies)
                        else:
                            proxy_configured = proxies.configure_proxy(self.session)
                        
                        if self.debug:
                            logger.debug("Session reset due to 401 error")
                        tried = 0
                        continue
                    return response
            except Exception as e:
                # Proxy auth issues (e.g. "407 NO_USER") should rotate proxy immediately.
                # If auto-proxy mode still fails, do one direct fallback before giving up.
                if isinstance(e, (ProxyError, RequestException)):
                    err_text = str(e).upper()
                    is_proxy_auth_issue = ("407" in err_text) or ("NO_USER" in err_text)
                    if is_proxy_auth_issue and not self.proxies and not direct_fallback_used:
                        direct_fallback_used = True
                        logger.warning("Proxy auth failed (407/NO_USER). Retrying request without proxy.")
                        continue

                if tried == self.MAX_RETRIES:
                    raise e
                logger.warning(f"Request failed (attempt {tried}): {e}")
                time.sleep(1)

        # This should only happen if the loop exits without returning
        raise HTTPError(f"Failed to get a valid response after {self.MAX_RETRIES} attempts")

    def post(self, url, params=None):
        """
        Make a POST request.

        Args:
            url (str): The URL to request
            params (dict, optional): Parameters for the request

        Returns:
            requests.Response: The response object if successful

        Raises:
            HTTPError: If the request fails
        """
        # Set a random proxy for this request
        proxy_configured = proxies.configure_proxy(self.session)
        if self.debug and proxy_configured:
            logger.debug(f"Using proxy: {self.session.proxies}")

        response = self.session.post(url, params)
        response.raise_for_status()
        return response

    def set_cookies(self):
        """
        Reset and fetch new cookies for authentication.

        Clears the current session cookies and makes a GET request to
        the Vinted authentication URL to get new cookies.
        """
        self.session.cookies.clear()
        try:
            # Using GET instead of HEAD because Vinted sometimes doesn't set all cookies on HEAD
            self.session.get(self.VINTED_AUTH_URL, timeout=10)
            if self.debug:
                logger.debug("Cookies set via GET!")
        except Exception:
            if self.debug:
                logger.error("There was an error fetching cookies for vinted", exc_info=True)


    def update_cookies(self, cookies: dict):
        """
        Update the session cookies with the provided dictionary.

        Args:
            cookies (dict): Dictionary of cookies to update
        """
        self.session.cookies.update(cookies)
        if self.debug:
            logger.debug(f"Cookies manually updated ({len(cookies)} cookies received)")

    # Alias for backward compatibility
    setLocale = set_locale
    setCookies = set_cookies

# Singleton instance of the Requester class
requester = Requester()

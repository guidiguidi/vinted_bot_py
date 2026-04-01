import random
import requests
import time
import os
import csv
from requests.exceptions import RequestException
import configuration_values
import concurrent.futures
from datetime import datetime
from io import StringIO
from typing import List, Optional, Tuple, Any
from logger import get_logger

# Get logger for this module
logger = get_logger(__name__)

# Cache for proxy list
_PROXY_CACHE = None
_PROXY_CACHE_INITIALIZED = False
_SINGLE_PROXY = None

# URL to test proxies against
_TEST_URL = "https://www.vinted.fr/"
_TEST_TIMEOUT = 10  # Increased timeout for rotating proxies
# Maximum number of concurrent workers for proxy checking
MAX_PROXY_WORKERS = 10
# Time interval in seconds after which proxies should be rechecked (6 hours)
PROXY_RECHECK_INTERVAL = 6 * 60 * 60
_DATAIMPULSE_USAGE_URL = "https://data.dataimpulse.com/api/details/usage_export_get"


def reset_proxy_cache() -> None:
    """
    Reset in-memory proxy cache so new settings apply immediately.
    """
    global _PROXY_CACHE, _PROXY_CACHE_INITIALIZED, _SINGLE_PROXY
    _PROXY_CACHE = None
    _PROXY_CACHE_INITIALIZED = False
    _SINGLE_PROXY = None


def load_user_agents_from_file(filename: str = "user_agents.txt") -> List[str]:
    """
    Load user agents from a text file.

    Args:
        filename (str): Name of the file containing user agents.

    Returns:
        List[str]: List of user agents.
    """
    user_agents = []
    file_path = os.path.join(os.path.dirname(__file__), filename)

    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as file:
                for line in file:
                    line = line.strip()
                    if line and not line.startswith('#'):  # Skip empty lines and comments
                        user_agents.append(line)
            logger.info(f"Loaded {len(user_agents)} user agents from {filename}")
        else:
            logger.warning(f"User agents file {filename} not found, using default user agents")
            # Fallback to default user agents if file doesn't exist
            user_agents = configuration_values.USER_AGENTS.copy()
    except Exception as e:
        logger.error(f"Error loading user agents from {filename}: {e}")
        user_agents = configuration_values.USER_AGENTS.copy()

    return user_agents


# Load user agents from file
USER_AGENTS = load_user_agents_from_file()


def fetch_proxies_from_link(url: str) -> List[str]:
    """
    Fetch proxies from a URL.

    Args:
        url (str): URL to fetch proxies from.

    Returns:
        List[str]: List of proxies.
    """
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            # Split by newlines and filter out empty lines
            return [line.strip() for line in response.text.splitlines() if line.strip()]
        return []
    except Exception:
        # If there's any error fetching proxies, return an empty list
        return []


def check_proxies_parallel(proxies_list: List[str]) -> List[str]:
    """
    Check multiple proxies in parallel using a thread pool.

    Args:
        proxies_list (List[str]): List of proxy strings to check.

    Returns:
        List[str]: List of working proxies.
    """
    working_proxies = []

    # Use ThreadPoolExecutor to check proxies in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_PROXY_WORKERS) as executor:
        # Submit all proxy checking tasks
        future_to_proxy = {executor.submit(check_proxy, proxy): proxy for proxy in proxies_list}

        # Process results as they complete
        for future in concurrent.futures.as_completed(future_to_proxy):
            proxy = future_to_proxy[future]
            try:
                is_working = future.result()
                if is_working:
                    working_proxies.append(proxy)
            except Exception:
                # If an exception occurred during checking, consider the proxy not working
                pass

    return working_proxies


def get_random_proxy() -> Optional[str]:
    """
    Get a random proxy from the configuration values.

    Uses a cache to minimize I/O operations:
    - If there are no proxies on first check, never checks again
    - If there is only one proxy, always returns that one
    - Otherwise, returns a random proxy from the cached list

    Proxies are checked in parallel to avoid blocking the main thread.
    Proxies are rechecked if they were checked more than PROXY_RECHECK_INTERVAL seconds ago.

    Returns:
        Optional[str]: A randomly selected proxy string or None if no working proxies are found.
    """
    global _PROXY_CACHE, _PROXY_CACHE_INITIALIZED, _SINGLE_PROXY

    # Import db here to avoid circular imports
    import db

    current_time = time.time()

    # Get the last proxy check time from the database
    last_proxy_check_time_str = db.get_parameter("last_proxy_check_time")
    last_proxy_check_time = float(last_proxy_check_time_str) if last_proxy_check_time_str else 0

    # Check if we need to recheck proxies (if more than PROXY_RECHECK_INTERVAL seconds have passed)
    if (_PROXY_CACHE_INITIALIZED and
            last_proxy_check_time > 0 and
            current_time - last_proxy_check_time > PROXY_RECHECK_INTERVAL):
        # Reset cache to force recheck
        _PROXY_CACHE_INITIALIZED = False
        _PROXY_CACHE = None
        _SINGLE_PROXY = None

    # If cache is already initialized
    if _PROXY_CACHE_INITIALIZED:
        # If we determined there are no proxies, always return None
        if _PROXY_CACHE is None:
            return None
        # If we have a single proxy, always return that one
        if _SINGLE_PROXY is not None:
            return _SINGLE_PROXY
        # Otherwise, return a random proxy from the cache
        if _PROXY_CACHE:
            return random.choice(_PROXY_CACHE)
        return None

    # Initialize cache on first call or after recheck interval
    _PROXY_CACHE_INITIALIZED = True

    # Update the last check time in the database
    db.set_parameter("last_proxy_check_time", str(current_time))

    # Initialize all_proxies list
    all_proxies = []

    # Check if PROXY_LIST is configured in the database
    proxy_list = db.get_parameter("proxy_list")
    if proxy_list:
        # If PROXY_LIST is a string with multiple proxies separated by semicolons
        all_proxies = [p.strip() for p in proxy_list.split(';') if p.strip()]

    # Check if PROXY_LIST_LINK is configured in the database
    proxy_list_link = db.get_parameter("proxy_list_link")
    if proxy_list_link:
        # Fetch proxies from the link and add them to all_proxies
        link_proxies = fetch_proxies_from_link(proxy_list_link)
        all_proxies.extend(link_proxies)

    # Check proxies in parallel if we have any and CHECK_PROXIES is True
    if all_proxies:
        check_proxies = db.get_parameter("check_proxies") == "True"
        if check_proxies:
            working_proxies = check_proxies_parallel(all_proxies)
            if working_proxies:
                _PROXY_CACHE = working_proxies
                # If there's only one working proxy, cache it separately
                if len(working_proxies) == 1:
                    _SINGLE_PROXY = working_proxies[0]
                    return _SINGLE_PROXY
                return random.choice(working_proxies)
        else:
            # If CHECK_PROXIES is False, just cache all proxies without checking them
            _PROXY_CACHE = all_proxies
            # If there's only one proxy, cache it separately
            if len(all_proxies) == 1:
                _SINGLE_PROXY = all_proxies[0]
                return _SINGLE_PROXY
            return random.choice(all_proxies)

    # No working proxies found
    _PROXY_CACHE = None
    return None


def check_proxy(proxy: str) -> bool:
    """
    Check if a proxy is working by making a request to the test URL.

    This function is thread-safe as it creates a new session for each check.
    Uses a random user agent to avoid detection.

    Args:
        proxy (str): Proxy string to check.

    Returns:
        bool: True if the proxy is working, False otherwise.
    """
    if proxy is None:
        return False

    # Convert proxy string to dictionary format
    proxy_dict = convert_proxy_string_to_dict(proxy)

    try:
        # Create a new session for testing (ensures thread safety)
        session = requests.Session()

        # Set random user agent and default headers
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            **configuration_values.DEFAULT_HEADERS
        }
        session.headers.update(headers)

        # Make a GET request to the test URL with the proxy (more reliable than HEAD)
        response = session.get(_TEST_URL, proxies=proxy_dict, timeout=_TEST_TIMEOUT)

        # Check if the request was successful
        # We accept 200 (Success), 403 (Vinted block but proxy works), 
        # or 401 (Auth error from Vinted, but proxy works)
        return response.status_code in [200, 403, 401]
    except Exception as e:
        # Any exception means the proxy is not working
        return False
    finally:
        # Ensure the session is closed to prevent resource leaks
        if 'session' in locals():
            session.close()


def get_current_ip(session: requests.Session = None) -> str:
    """
    Get the current public IP address being used for requests

    Returns:
        str: Current IP address or error message
    """
    # Avoid proxy traffic for external IP checks.
    return "IP check disabled"
def convert_proxy_string_to_dict(proxy: Optional[str]) -> dict:
    """
    Convert a proxy string to a dictionary format.
    Supports:
    - protocol://host:port
    - protocol://user:pass@host:port
    - protocol://host:port:user:pass
    - host:port
    - host:port:user:pass
    """
    if proxy is None:
        return {}

    if '://' in proxy:
        # If it already has a protocol, use it as is
        return {"http": proxy, "https": proxy}

    protocol = "http"
    address = proxy

    # Check for host:port:user:pass format
    parts = address.split(':')
    if len(parts) == 4:
        # host:port:user:pass -> user:pass@host:port
        host, port, user, password = parts
        formatted_proxy = f"{protocol}://{user}:{password}@{host}:{port}"
    else:
        # Assume user:pass@host:port or host:port
        formatted_proxy = f"{protocol}://{address}"

    # Requests needs http and https keys to use the proxy for those protocols
    return {"http": formatted_proxy, "https": formatted_proxy}



def configure_proxy(session: requests.Session, proxy: Optional[str] = None) -> bool:
    """
    Configure the proxy settings for a requests session.

    Args:
        session (requests.Session): The session to configure.
        proxy (Optional[str], optional): Proxy to be used. If None, a random proxy will be selected.

    Returns:
        bool: True if proxy was configured, False otherwise.
    """
    # If no proxy is provided, get a random one
    if proxy is None:
        proxy = get_random_proxy()

    if proxy is None:
        session.proxies.clear()
        logger.info("Using direct connection (no proxy)")
        return False

    if isinstance(proxy, str):
        proxy = convert_proxy_string_to_dict(proxy)

    session.proxies.update(proxy)
    logger.info(f"Proxy configured: {proxy}")
    return True


def reload_user_agents():
    """
    Reload user agents from file. Useful if the file has been updated.
    """
    global USER_AGENTS
    USER_AGENTS = load_user_agents_from_file()


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        cleaned = str(value).strip().replace(",", ".")
        if not cleaned:
            return None
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def _parse_dataimpulse_csv(raw_text: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Parse CSV payload similar to DataImpulse usage export.
    Returns total bytes and bytes spent on httpbin rows.
    """
    total_bytes = 0
    httpbin_bytes = 0
    found = False

    reader = csv.reader(StringIO(raw_text))
    for row in reader:
        if len(row) < 8:
            continue
        bytes_raw = str(row[7]).replace(" ", "")
        if not bytes_raw.isdigit():
            continue
        row_bytes = int(bytes_raw)
        total_bytes += row_bytes
        found = True
        host = row[2].lower() if len(row) > 2 else ""
        if "httpbin.org" in host:
            httpbin_bytes += row_bytes

    if not found:
        return None, None
    return total_bytes, httpbin_bytes


def _extract_usage_from_json(payload: Any) -> Tuple[Optional[int], Optional[int], Optional[float]]:
    """
    Extract (used_bytes, httpbin_bytes, remaining_mb) from different JSON schemas.
    """
    remaining_mb = None

    if isinstance(payload, dict):
        for key in ("remaining_mb", "remainingMb", "left_mb", "leftMb", "available_mb", "availableMb"):
            if key in payload:
                remaining_mb = _to_float(payload.get(key))
                break

        for key in ("data", "rows", "result", "items"):
            if key in payload:
                used, httpbin, inner_remaining = _extract_usage_from_json(payload[key])
                return used, httpbin, remaining_mb if remaining_mb is not None else inner_remaining

        if "used_bytes" in payload:
            used_val = payload.get("used_bytes")
            used = int(used_val) if str(used_val).isdigit() else None
            return used, 0, remaining_mb

        return None, None, remaining_mb

    if isinstance(payload, list):
        total_bytes = 0
        httpbin_bytes = 0
        found = False
        for row in payload:
            if isinstance(row, dict):
                host = str(row.get("host") or row.get("target") or "").lower()
                candidate_keys = ("bytes", "used_bytes", "traffic_bytes", "bandwidth_bytes")
                row_bytes = None
                for key in candidate_keys:
                    val = row.get(key)
                    if str(val).isdigit():
                        row_bytes = int(val)
                        break
                if row_bytes is not None:
                    total_bytes += row_bytes
                    found = True
                    if "httpbin.org" in host:
                        httpbin_bytes += row_bytes
            elif isinstance(row, list) and len(row) > 7:
                if str(row[7]).isdigit():
                    row_bytes = int(row[7])
                    total_bytes += row_bytes
                    found = True
                    host = str(row[2]).lower() if len(row) > 2 else ""
                    if "httpbin.org" in host:
                        httpbin_bytes += row_bytes
        if found:
            return total_bytes, httpbin_bytes, remaining_mb

    return None, None, remaining_mb


def get_dataimpulse_usage_status() -> dict:
    """
    Read DataImpulse usage and compute remaining proxy MB.
    Required DB params:
    - dataimpulse_api_token
    Optional:
    - dataimpulse_plan_mb
    - dataimpulse_tz
    """
    import db

    token = (db.get_parameter("dataimpulse_api_token") or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        return {"ok": False, "error": "API token is not configured"}

    tz = (db.get_parameter("dataimpulse_tz") or "Europe/Kyiv").strip() or "Europe/Kyiv"
    plan_mb_raw = db.get_parameter("dataimpulse_plan_mb") or "0"
    plan_mb = _to_float(plan_mb_raw) or 0.0

    now = datetime.utcnow()
    start_of_month = now.replace(day=1).strftime("%Y-%m-%d")
    end_date = now.strftime("%Y-%m-%d")

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Origin": "https://app.dataimpulse.com",
        "Referer": "https://app.dataimpulse.com/",
    }
    payload = {"startDate": start_of_month, "endDate": end_date, "tz": tz}

    try:
        response = requests.post(_DATAIMPULSE_USAGE_URL, headers=headers, json=payload, timeout=20)
    except Exception as e:
        return {"ok": False, "error": f"request failed: {e}"}

    if response.status_code != 200:
        return {"ok": False, "error": f"HTTP {response.status_code}"}

    used_bytes = None
    httpbin_bytes = 0
    remaining_mb = None

    try:
        body = response.json()
        used_bytes, httpbin_bytes, remaining_mb = _extract_usage_from_json(body)
    except ValueError:
        used_bytes, httpbin_bytes = _parse_dataimpulse_csv(response.text)

    if used_bytes is None:
        return {"ok": False, "error": "unable to parse usage payload"}

    used_mb = round(used_bytes / (1024 * 1024), 2)
    httpbin_mb = round((httpbin_bytes or 0) / (1024 * 1024), 2)

    if remaining_mb is None and plan_mb > 0:
        remaining_mb = round(max(plan_mb - used_mb, 0.0), 2)

    return {
        "ok": True,
        "used_mb": used_mb,
        "remaining_mb": remaining_mb,
        "plan_mb": plan_mb if plan_mb > 0 else None,
        "httpbin_mb": httpbin_mb,
        "period_start": start_of_month,
        "period_end": end_date,
        "tz": tz,
    }
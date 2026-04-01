import db, configuration_values, requests
from pyVintedVN import Vinted, requester
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from logger import get_logger
import time
from datetime import datetime
import random
from configuration_values import USER_AGENTS, DEFAULT_HEADERS
from search_manager import SearchManager

# Get logger for this module
logger = get_logger(__name__)


def process_query(query, name=None, user_id=None):
    """
    Process a Vinted query URL by:
    1. Parsing the URL and extracting query parameters
    2. Ensuring the order flag is set to "newest_first"
    3. Removing time and search_id parameters
    4. Rebuilding the query string and URL
    """
    # Parse the URL and extract the query parameters
    parsed_url = urlparse(query)
    
    # Basic validation
    if not parsed_url.netloc or "vinted" not in parsed_url.netloc:
        return "❌ <b>Ошибка:</b> Некорректная ссылка Vinted. Пожалуйста, отправьте прямую ссылку на поиск.", False

    query_params = parse_qs(parsed_url.query)

    # Ensure the order flag is set to newest_first
    query_params['order'] = ['newest_first']
    # Remove time and search_id if provided
    query_params.pop('time', None)
    query_params.pop('search_id', None)
    query_params.pop('disabled_personalization', None)
    query_params.pop('page', None)

    # Rebuild the query string and the entire URL
    new_query = urlencode(query_params, doseq=True)
    processed_query = urlunparse(
        (parsed_url.scheme, parsed_url.netloc, parsed_url.path, parsed_url.params, new_query, parsed_url.fragment))

    if db.is_query_in_db(processed_query) is True:
        return "Query already exists.", False
    else:
        db.add_query_to_db(processed_query, name, user_id)
        return "Query added.", True


def get_formatted_query_list(user_id=None):
    """Get a formatted list of queries, optionally filtered by user_id."""
    all_queries = db.get_queries(user_id=user_id)
    queries_keywords = []
    for query in all_queries:
        parsed_url = urlparse(query[1])
        query_params = parse_qs(parsed_url.query)

        query_name = query[3] if query[3] is not None else query_params.get('search_text', [None])[0]

        if query_name is None: # check if query_name itself is None, not index 0
            queries_keywords.append([query[1]])
        else:
            # Handle both string and list names from parse_qs
            name = query_name[0] if isinstance(query_name, list) else query_name
            queries_keywords.append([name] if name else [query[1]])

    query_list = ("\n").join([str(i + 1) + ". " + j[0] for i, j in enumerate(queries_keywords)])
    return query_list


def process_remove_query(number, user_id=None):
    """Process the removal of a query from the database."""
    if number == "all":
        if user_id:
            # We need a new function in db.py for this
            db.remove_all_user_queries_from_db(user_id)
        else:
            db.remove_all_queries_from_db()
        return "All queries removed.", True

    if not number[0].isdigit():
        return "Invalid number.", False

    db.remove_query_from_db(number)
    return "Query removed.", True


def process_add_country(country):
    """Process the addition of a country to the allowlist."""
    country = country.replace(" ", "")
    country_list = db.get_allowlist()

    if len(country) != 2:
        return "Invalid country code", country_list

    if country_list != 0 and country.upper() in country_list:
        return f'Country "{country.upper()}" already in allowlist.', country_list

    db.add_to_allowlist(country.upper())
    return "Country added.", db.get_allowlist()


def process_remove_country(country):
    """Process the removal of a country from the allowlist."""
    country = country.replace(" ", "")

    if len(country) != 2:
        return "Invalid country code", db.get_allowlist()

    db.remove_from_allowlist(country.upper())
    return "Country removed.", db.get_allowlist()


def get_user_country(profile_id):
    """Get the country code for a Vinted user."""
    url = f"https://www.vinted.fr/api/v2/users/{profile_id}?localize=false"
    response = requester.get(url)

    if response.status_code == 429:
        url = f"https://www.vinted.fr/api/v2/users/{profile_id}/items?page=1&per_page=1"
        response = requester.get(url)
        try:
            user_country = response.json()["items"][0]["user"]["country_iso_code"]
        except (KeyError, IndexError):
            logger.warning("Couldn't get the country due to too many requests. Returning default value.")
            user_country = "XX"
    else:
        try:
            user_country = response.json()["user"]["country_iso_code"]
        except KeyError:
            user_country = "XX"

    return user_country


# Initialize SearchManager as a module-level singleton
vinted_instance = Vinted()

# Fix 1: Set a random proxy for pyVintedVN singleton requester if available
from proxies import get_random_proxy, convert_proxy_string_to_dict
proxy = get_random_proxy()
if proxy:
    # Use the convert_proxy_string_to_dict from proxies.py to format it
    requester.proxies = convert_proxy_string_to_dict(proxy)
    logger.info(f"Fixed proxy set for pyVintedVN: {requester.proxies}")

search_manager = SearchManager(vinted_instance)

def process_items(queue):
    """
    Process all queries from the database using SearchManager for optimization.
    Search for items and put them in the queue.

    Args:
        queue (Queue): The queue to put the items in
    """
    all_queries = db.get_queries()
    
    # Optimization 3 & 4: Consolidation and Local Filtering via SearchManager
    results = search_manager.consolidate_and_search(all_queries)

    for all_items, query_id in results:
        try:
            # Optimization 1 & 8: Incremental loading using item_id
            # Get last maximal item_id from DB
            last_item_id_str = db.get_last_timestamp(query_id) # Column is reused for item_id
            last_item_id = int(last_item_id_str) if last_item_id_str and str(last_item_id_str).isdigit() else 0

            # Filter to only include items with ID > last_item_id
            # AND published within the last 1 minute (60 seconds)
            current_time = int(time.time())
            MAX_AGE = 60 # 1 minute
            
            new_items = [
                item for item in all_items 
                if int(item.id) > last_item_id and (current_time - item.raw_timestamp) < MAX_AGE
            ]

            if new_items:
                # Update max item_id in DB to avoid processing the same items again
                # We use the max ID from all_items to stay up to date, even if we filtered some out
                all_ids = [int(item.id) for item in all_items]
                if all_ids:
                    db.update_last_timestamp(query_id, max(all_ids))
                
                # If last_item_id was 0, it's the first run for this query.
                if last_item_id == 0:
                    logger.info(f"First run for query_id {query_id}. Initialized database. No items sent.")
                    continue

                queue.put((new_items, query_id))
                logger.info(f"Scraped {len(new_items)} FRESH items for query_id: {query_id}")
            else:
                # Even if no fresh items, we should update the last_item_id to the latest seen
                # so we don't keep checking old items in the next iteration
                all_ids = [int(item.id) for item in all_items]
                if all_ids:
                    db.update_last_timestamp(query_id, max(all_ids))
                logger.info(f"No fresh items found for query_id: {query_id}")

        except Exception as e:
            logger.error(f"Error processing results for query_id {query_id}: {e}")
            continue


def clear_item_queue(items_queue, new_items_queue):
    """Process items from the items_queue."""
    if not items_queue.empty():
        data, query_id = items_queue.get()

        # Sort data by ID descending to process newest first
        sorted_items = sorted(data, key=lambda x: int(x.id), reverse=True)

        for item in sorted_items:
            try:
                # We already filtered by ID in process_items, but we keep some checks
                # Check if item already exists in db by ID (for cross-query duplicates)
                if db.is_item_in_db_by_id(item.id) is True:
                    continue

                # Check country allowlist
                if db.get_allowlist() != 0:
                    user_country = get_user_country(item.raw_data["user"]["id"])
                    if user_country not in (db.get_allowlist() + ["XX"]):
                        logger.debug(f"User country {user_country} not in allowlist, skipping item")
                        continue

                # Create message and add to queue
                # Optimization: Beautiful formatting
                sub_type = item.raw_data.get('status', 'N/A')

                # Get query name and user_id
                query_info = db.get_query_by_id(query_id)
                query_name = query_info[3] if query_info and query_info[3] else "Vinted"
                target_user_id = query_info[4] if query_info and len(query_info) > 4 else None

                content = (
                    f"✨ <b>{item.title}</b>\n\n"
                    f"💶 <b>Цена:</b> {item.price} {item.currency}\n"
                    f"🏷 <b>Бренд:</b> {item.brand_title}\n"
                    f"📏 <b>Размер:</b> {item.size_title or 'N/A'}\n"
                    f"🔄 <b>Состояние:</b> {sub_type}\n"
                )

                # photo is handled by telegram_bot if needed, but here we just pass it
                new_items_queue.put((content, item.url, "🔎 Открыть", item.photo, item.buy_url, target_user_id))
                # Add item to database
                db.add_item_to_db(
                    id=item.id,
                    timestamp=item.raw_timestamp,
                    price=item.price,
                    title=item.title,
                    photo_url=item.photo,
                    query_id=query_id,
                    currency=item.currency
                )

                # Log the new item
                item_time = datetime.fromtimestamp(item.raw_timestamp).strftime('%H:%M:%S')
                time_diff = int(time.time()) - item.raw_timestamp

                try:
                    logger.info(f"✅ NEW ({time_diff}s ago): {item.title} | {item_time}")
                except UnicodeEncodeError:
                    safe_title = item.title.encode('ascii', 'ignore').decode('ascii')
                    logger.info(f"✅ NEW ({time_diff}s ago): {safe_title} | {item_time}")

            except Exception as e:
                logger.error(f"Error processing item {item.id}: {str(e)}")
                continue


def check_version():
    """Check if the application is up to date"""
    try:
        github_url = db.get_parameter("github_url")
        ver = db.get_parameter("version")
        url = f"{github_url}/releases/latest"
        response = requests.get(url)

        if response.status_code == 200:
            latest_version = response.url.split('/')[-1]
            is_up_to_date = (ver == latest_version)
            return is_up_to_date, ver, latest_version, github_url
        else:
            return True, ver, ver, github_url
    except Exception as e:
        logger.error(f"Error checking for new version: {str(e)}", exc_info=True)
        return True, ver, ver, github_url
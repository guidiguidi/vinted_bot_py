import db
import requests
from pyVintedVN import Vinted, requester
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from logger import get_logger
import time
from datetime import datetime
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

    if db.is_query_in_db(processed_query, user_id=user_id) is True:
        return "⚠️ Этот запрос уже добавлен в ваш список.", False
    else:
        db.add_query_to_db(processed_query, name, user_id)
        return "✅ Запрос успешно добавлен!", True


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


def process_add_proxy(proxy_input: str, check_immediately: bool = False):
    """Process adding proxies from text input."""
    import proxies
    try:
        added, total = proxies.add_proxies(proxy_input, check_immediately=check_immediately)
        if added > 0:
            return f"✅ Успешно добавлено {added} прокси. Всего в списке: <b>{total}</b>.", True
        elif total > 0:
            return f"ℹ️ Все указанные прокси уже есть в списке (всего: <b>{total}</b>).", False
        else:
            return "❌ Не удалось распознать прокси. Проверьте формат ввода.", False
    except Exception as e:
        logger.error(f"Error adding proxies: {e}", exc_info=True)
        return f"❌ Ошибка при добавлении прокси: {e}", False


def process_get_proxies():
    """Get formatted list of current scraper proxies."""
    import proxies
    return proxies.get_proxies_list()


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


_search_manager = None

def get_search_manager():
    global _search_manager
    if _search_manager is None:
        _search_manager = SearchManager(Vinted())
    return _search_manager


def process_items(queue):
    """
    Process all queries from the database using SearchManager for optimization.
    Search for items and put them in the queue.

    Args:
        queue (Queue): The queue to put the items in
    """
    all_queries = db.get_queries()
    logger.info(f"Processing items for {len(all_queries)} queries...")
    
    # Optimization 3 & 4: Consolidation and Local Filtering via SearchManager
    sm = get_search_manager()
    results = sm.consolidate_and_search(all_queries)

    for all_items, query_id in results:
        try:
            # Optimization 1 & 8: Incremental loading using item_id
            # Get last maximal item_id from DB
            last_item_id_str = db.get_last_timestamp(query_id) # Column is reused for item_id
            last_item_id = int(last_item_id_str) if last_item_id_str and str(last_item_id_str).isdigit() else 0

            current_time = int(time.time())
            MAX_AGE = 1800 # 30 minutes
            
            all_ids = [int(item.id) for item in all_items if hasattr(item, 'id') and item.id and str(item.id).isdigit()]

            # If last_item_id was 0, it's the first run for this query.
            if last_item_id == 0:
                if all_ids:
                    db.update_last_timestamp(query_id, max(all_ids))
                # Send top 3 initial items so user immediately sees that the query is working!
                initial_items = all_items[:3]
                if initial_items:
                    queue.put((initial_items, query_id))
                    logger.info(f"First run for query_id {query_id}. Sent {len(initial_items)} initial items.")
                continue

            new_items = [
                item for item in all_items 
                if hasattr(item, 'id') and item.id and str(item.id).isdigit() and int(item.id) > last_item_id and abs(current_time - item.raw_timestamp) < MAX_AGE
            ]

            if all_ids:
                db.update_last_timestamp(query_id, max(all_ids))

            if new_items:
                queue.put((new_items, query_id))
                logger.info(f"Scraped {len(new_items)} FRESH items for query_id: {query_id}")
            else:
                logger.info(f"No fresh items found for query_id: {query_id}")

        except Exception as e:
            logger.error(f"Error processing results for query_id {query_id}: {e}", exc_info=True)
            continue


def clear_item_queue(items_queue, new_items_queue):
    """Process items from the items_queue with per-user deduplication."""
    while not items_queue.empty():
        try:
            data, query_id = items_queue.get_nowait()
        except Exception:
            break

        # Resolve all subscribed users for this query
        subscribers = db.get_subscribers_for_query(query_id)
        if not subscribers:
            import db_commercial as db_tma
            subscribers = db_tma.get_active_subscribers()

        # Sort data by ID descending to process newest first
        sorted_items = sorted(data, key=lambda x: int(x.id) if str(getattr(x, 'id', '')).isdigit() else 0, reverse=True)

        for item in sorted_items:
            try:
                # Per-user deduplication: only include subscribers who have NOT seen this item yet
                unseen_users = [uid for uid in subscribers if not db.is_item_seen_by_user(item.id, uid)]
                if not unseen_users:
                    continue

                # Check country allowlist safely
                if db.get_allowlist() != 0:
                    user_data_obj = item.raw_data.get("productItem", item.raw_data).get("user") or item.raw_data.get("user")
                    if user_data_obj and isinstance(user_data_obj, dict) and "id" in user_data_obj:
                        user_country = get_user_country(user_data_obj["id"])
                        if user_country not in (db.get_allowlist() + ["XX"]):
                            logger.debug(f"User country {user_country} not in allowlist, skipping item")
                            continue

                # Create message and add to queue
                sub_type = item.raw_data.get('status', 'N/A')

                content = (
                    f"✨ <b>{item.title}</b>\n\n"
                    f"💶 <b>Цена:</b> {item.price} {item.currency}\n"
                    f"🏷 <b>Бренд:</b> {item.brand_title}\n"
                    f"📏 <b>Размер:</b> {item.size_title or 'N/A'}\n"
                    f"🔄 <b>Состояние:</b> {sub_type}\n"
                )

                # Mark item as seen for all unseen_users immediately to prevent re-queueing
                for uid in unseen_users:
                    db.mark_item_seen_by_user(item.id, uid)

                # Send item to queue with list of recipient user IDs
                new_items_queue.put((content, item.url, "🔎 Открыть", item.photo, item.buy_url, unseen_users))

                # Add item to database items table
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
                    logger.info(f"✅ NEW ({time_diff}s ago) for {len(unseen_users)} user(s): {item.title} | {item_time}")
                except UnicodeEncodeError:
                    safe_title = item.title.encode('ascii', 'ignore').decode('ascii')
                    logger.info(f"✅ NEW ({time_diff}s ago) for {len(unseen_users)} user(s): {safe_title} | {item_time}")

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
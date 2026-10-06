import threading
import queue
import time
import os
import signal
import json
import http.server
import socketserver
from dotenv import load_dotenv

import core
import db
import db_commercial as db_tma
import proxies
from logger import configure_root_logger, get_logger

load_dotenv()
configure_root_logger()
logger = get_logger(__name__)

shutdown_event = threading.Event()

items_queue = queue.Queue()
new_items_queue = queue.Queue()
telegram_queue = queue.Queue()

scraper_thread = None
telegram_thread = None
item_extractor_thread = None
dispatcher_thread = None


def signal_handler(sig, frame):
    logger.info("Received shutdown signal")
    shutdown_event.set()
    try:
        from telegram_bot_plugin.telegram_bot import stop_bot
        stop_bot()
    except Exception:
        pass


def start_health_server():
    """Starts a minimal HTTP server if PORT environment variable is set (Heroku web dyno support)."""
    port_str = os.getenv("PORT")
    if not port_str:
        return
    try:
        port = int(port_str)

        class HealthHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path in ("/debug", "/status"):
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    try:
                        queries_cnt = db.get_total_queries_count()
                        users_cnt = db_tma.get_all_users_count()
                        proxies_list = proxies.get_proxies_list()
                        debug_data = {
                            "status": "ok",
                            "queries_count": queries_cnt,
                            "users_count": users_cnt,
                            "proxies_count": len(proxies_list),
                            "server_time": int(time.time()),
                            "threads": {
                                "scraper": scraper_thread.is_alive() if scraper_thread else False,
                                "telegram": telegram_thread.is_alive() if telegram_thread else False,
                                "extractor": item_extractor_thread.is_alive() if item_extractor_thread else False,
                                "dispatcher": dispatcher_thread.is_alive() if dispatcher_thread else False,
                            },
                            "queues": {
                                "items": items_queue.qsize(),
                                "new_items": new_items_queue.qsize(),
                                "telegram": telegram_queue.qsize(),
                            }
                        }
                        self.wfile.write((json.dumps(debug_data, indent=2) + "\n").encode("utf-8"))
                    except Exception as ex:
                        self.wfile.write(f'{{"error": "{ex}"}}\n'.encode("utf-8"))
                    return

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'{"status": "ok", "service": "vinted-bot"}\n')

            def log_message(self, format, *args):
                pass

        class ReusableTCPServer(socketserver.TCPServer):
            allow_reuse_address = True

        httpd = ReusableTCPServer(("", port), HealthHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True, name="HealthServer")
        thread.start()
        logger.info(f"Health server listening on port {port}")
    except Exception as e:
        logger.error(f"Failed to start health server: {e}")


def initialize_database():
    sql_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "initial_db.sql")
    if not os.path.exists(sql_file):
        sql_file = "initial_db.sql"
    try:
        if os.path.exists(sql_file):
            db.create_or_update_sqlite_db(sql_file)
            logger.info("Database initialized successfully")
        else:
            logger.error(f"SQL file {sql_file} not found! Cannot initialize database.")
            return False
    except Exception as e:
        logger.error(f"Error creating database: {e}")
        return False

    token = os.getenv("TELEGRAM_TOKEN")
    if token:
        db.set_parameter("telegram_token", token)
    db.set_parameter("sniper_enabled", "False")

    return True


def scraper_worker(q):
    logger.info("Scraper worker thread started")
    from pyVintedVN.requester import requester
    requester._init_session(rotate_proxy=False)

    while not shutdown_event.is_set():
        try:
            core.process_items(q)
        except Exception as e:
            logger.error(f"Error during query scrape cycle: {e}", exc_info=True)

        delay = int(db.get_parameter("query_refresh_delay") or 30)
        for _ in range(delay):
            if shutdown_event.is_set():
                break
            time.sleep(1)

    logger.info("Scraper worker thread fully terminated")


def item_extractor_worker(in_q, out_q):
    logger.info("Item extractor thread started")
    while not shutdown_event.is_set():
        try:
            core.clear_item_queue(in_q, out_q)
            time.sleep(0.1)
        except Exception as e:
            logger.error(f"Error in item extractor: {e}", exc_info=True)
            time.sleep(1)
    logger.info("Item extractor thread fully terminated")


def dispatcher_worker(in_q, out_q):
    logger.info("Dispatcher thread started")
    while not shutdown_event.is_set():
        try:
            item = in_q.get(timeout=1.0)
            logger.info(f"🚚 Dispatcher got item for user(s) {item[5]}: {item[0][:50]}...")
            out_q.put(item)
            logger.info(f"📨 Sent to telegram_queue, size: {out_q.qsize()}")
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"Error in dispatcher: {e}", exc_info=True)
            time.sleep(1)
    logger.info("Dispatcher thread fully terminated")


def telegram_bot_worker(q):
    logger.info("Starting Telegram bot thread")
    try:
        from telegram_bot_plugin.telegram_bot import run_bot_in_process
        run_bot_in_process(q)
    except Exception as e:
        logger.error(f"Error in Telegram bot thread: {e}", exc_info=True)
    logger.info("Telegram bot thread fully terminated")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    start_health_server()

    if not initialize_database():
        logger.error("Failed to initialize database. Exiting.")
        exit(1)

    db.set_parameter('sniper_enabled', 'False')
    db.set_parameter('telegram_enabled', 'True')
    db.set_parameter('telegram_process_running', 'True')

    logger.info("In-memory thread-safe queues created.")

    # 1. Telegram bot thread
    telegram_thread = threading.Thread(target=telegram_bot_worker, args=(telegram_queue,), name="TelegramBot", daemon=True)
    telegram_thread.start()
    time.sleep(1)

    # 2. Item extractor thread
    item_extractor_thread = threading.Thread(target=item_extractor_worker, args=(items_queue, new_items_queue), name="ItemExtractor", daemon=True)
    item_extractor_thread.start()

    # 3. Dispatcher thread
    dispatcher_thread = threading.Thread(target=dispatcher_worker, args=(new_items_queue, telegram_queue), name="Dispatcher", daemon=True)
    dispatcher_thread.start()

    # 4. Scraper thread
    scraper_thread = threading.Thread(target=scraper_worker, args=(items_queue,), name="Scraper", daemon=True)
    scraper_thread.start()

    logger.info("=== PROCESS STATUS ===")
    logger.info(f"Telegram: {'Alive' if telegram_thread.is_alive() else 'Dead'}")
    logger.info(f"Scraper: {'Alive' if scraper_thread.is_alive() else 'Dead'}")
    logger.info(f"ItemExtractor: {'Alive' if item_extractor_thread.is_alive() else 'Dead'}")
    logger.info(f"Dispatcher: {'Alive' if dispatcher_thread.is_alive() else 'Dead'}")

    try:
        while not shutdown_event.is_set():
            logger.info(
                f"Queue status - Items: {items_queue.qsize()}, New: {new_items_queue.qsize()}, Telegram: {telegram_queue.qsize()}"
            )

            # Health monitor
            if not telegram_thread.is_alive() and not shutdown_event.is_set():
                logger.warning("Telegram bot thread unexpectedly terminated. Restarting...")
                telegram_thread = threading.Thread(target=telegram_bot_worker, args=(telegram_queue,), name="TelegramBot", daemon=True)
                telegram_thread.start()

            if not scraper_thread.is_alive() and not shutdown_event.is_set():
                logger.warning("Scraper thread unexpectedly terminated. Restarting...")
                scraper_thread = threading.Thread(target=scraper_worker, args=(items_queue,), name="Scraper", daemon=True)
                scraper_thread.start()

            time.sleep(30)

    except (KeyboardInterrupt, SystemExit):
        logger.info("Main shutdown triggered")
        shutdown_event.set()
    finally:
        shutdown_event.set()
        try:
            from telegram_bot_plugin.telegram_bot import stop_bot
            stop_bot()
        except Exception:
            pass

        threads = [scraper_thread, item_extractor_thread, dispatcher_thread, telegram_thread]
        for t in threads:
            if t and t.is_alive():
                t.join(timeout=2.0)

        db.set_parameter('telegram_process_running', 'False')
        logger.info("All processes terminated")

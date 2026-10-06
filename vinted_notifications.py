import multiprocessing
import time
import core
import os
import db
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from logger import get_logger
import logging
import signal

load_dotenv()

# Configure logging for console (stdout / Heroku) and file
from logger import configure_root_logger, get_logger
configure_root_logger()
logger = get_logger(__name__)

shutdown_event = multiprocessing.Event()

def signal_handler(sig, frame):
    logger.info("Received shutdown signal")
    shutdown_event.set()

telegram_process = None
scrape_process = None
current_query_refresh_delay = None

def start_health_server():
    """Starts a minimal HTTP server if PORT environment variable is set (Heroku web dyno support)."""
    port_str = os.getenv("PORT")
    if not port_str:
        return
    try:
        import http.server
        import socketserver
        import threading
        import json
        import db_commercial as db_tma
        import proxies

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
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
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

    # Automatically sync TELEGRAM_TOKEN from environment/.env to database if present
    token = os.getenv("TELEGRAM_TOKEN")
    if token:
        db.set_parameter("telegram_token", token)
    db.set_parameter("sniper_enabled", "False")

    return True

def scraper_process(items_queue):
    logger.info("Scrape process started")
    current_query_refresh_delay = int(db.get_parameter("query_refresh_delay") or 60)
    logger.info(f"Using query refresh delay of {current_query_refresh_delay} seconds")
    int(time.time()) - 180
    scraper_scheduler = BackgroundScheduler()
    scraper_scheduler.add_job(
        core.process_items,  # Только 1 аргумент
        'interval',
        seconds=current_query_refresh_delay,
        args=[items_queue],  # Только очередь, без time_threshold
        name="scraper"
    )
    scraper_scheduler.start()
    try:
        while not shutdown_event.is_set():
            int(time.time()) - 180
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scraper_scheduler.shutdown()
        logger.info("Scrape process stopped")
    finally:
        scraper_scheduler.shutdown()
        logger.info("Scrape process fully terminated")

def item_extractor(items_queue, new_items_queue):
    logger.info("Item extractor process started")
    try:
        while not shutdown_event.is_set():
            core.clear_item_queue(items_queue, new_items_queue)
            time.sleep(0.1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Item extractor process stopped")
    finally:
        logger.info("Item extractor process fully terminated")

def dispatcher_function(input_queue, telegram_queue):
    logger.info("Dispatcher process started")
    try:
        while not shutdown_event.is_set():
            try:
                item = input_queue.get(timeout=1.0)
                # item is (content, url, btn_text, photo_url, buy_url, target_user_id)
                logger.info(f"🚚 Dispatcher got item for user {item[5]}: {item[0][:50]}...")
                telegram_queue.put(item)
                try:
                    logger.info(f"📨 Sent to telegram_queue, size: {telegram_queue.qsize()}")
                except NotImplementedError:
                    logger.info("📨 Sent to telegram_queue, size: unavailable")
            except multiprocessing.queues.Empty:
                continue
    except (KeyboardInterrupt, SystemExit):
        logger.info("Dispatcher process stopped")
    except Exception as e:
        logger.error(f"Error in dispatcher: {e}")
    finally:
        logger.info("Dispatcher process fully terminated")

def telegram_bot_process(queue):
    logger.info("Starting Telegram bot process")
    try:
        from telegram_bot_plugin.telegram_bot import run_bot_in_process
        run_bot_in_process(queue)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Telegram bot process stopped")
    except Exception as e:
        logger.error(f"Error in telegram bot process: {e}", exc_info=True)
    finally:
        logger.info("Telegram bot process fully terminated")

def check_refresh_delay(items_queue):
    global scrape_process, current_query_refresh_delay
    if scrape_process is None or not scrape_process.is_alive():
        return
    try:
        new_delay = int(db.get_parameter("query_refresh_delay") or 60)
        if new_delay != current_query_refresh_delay:
            logger.info(f"Query refresh delay changed from {current_query_refresh_delay} to {new_delay} seconds")
            current_query_refresh_delay = new_delay
            scrape_process.terminate()
            scrape_process.join()
            scrape_process = multiprocessing.Process(target=scraper_process, args=(items_queue,))
            scrape_process.start()
            logger.info(f"Scheduler updated with new refresh delay of {new_delay} seconds")
    except Exception as e:
        logger.error(f"Error updating refresh delay: {e}", exc_info=True)

def monitor_processes(items_queue, telegram_queue):
    global telegram_process
    check_refresh_delay(items_queue)
    telegram_is_running = telegram_process is not None and telegram_process.is_alive()
    if not telegram_is_running and not shutdown_event.is_set():
        if telegram_process is not None:
            telegram_process.join(timeout=2.0)
            telegram_process = None
        logger.info("Starting telegram bot process.")
        telegram_process = multiprocessing.Process(target=telegram_bot_process, args=(telegram_queue,), name="TelegramBot")
        telegram_process.start()
        time.sleep(1)
        logger.info(
            f"Telegram process status: {'Running' if telegram_process and telegram_process.is_alive() else 'Stopped'}")

def plugin_checker():
    db.set_parameter('telegram_process_running', 'True')

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
    plugin_checker()
    manager = multiprocessing.Manager()
    items_queue = manager.Queue()
    new_items_queue = manager.Queue()
    telegram_queue = manager.Queue()
    logger.info(f"Queues created. Telegram queue: {telegram_queue}")
    logger.info("Starting Telegram process...")
    telegram_process = multiprocessing.Process(target=telegram_bot_process, args=(telegram_queue,), name="TelegramBot")
    telegram_process.start()
    time.sleep(3)
    telegram_status = "Running" if telegram_process and telegram_process.is_alive() else "Stopped"
    logger.info(f"Telegram process status: {telegram_status}")
    logger.info("Starting scrape process...")
    current_query_refresh_delay = int(db.get_parameter("query_refresh_delay") or 60)
    scrape_process = multiprocessing.Process(target=scraper_process, args=(items_queue,), name="Scraper")
    scrape_process.start()
    logger.info("Starting item extractor process...")
    item_extractor_process = multiprocessing.Process(target=item_extractor, args=(items_queue, new_items_queue),
                                                     name="ItemExtractor")
    item_extractor_process.start()
    logger.info("Starting dispatcher process...")
    dispatcher_process = multiprocessing.Process(target=dispatcher_function,
                                                 args=(new_items_queue, telegram_queue,),
                                                 name="Dispatcher")
    dispatcher_process.start()

    logger.info("Starting monitor scheduler...")
    monitor_scheduler = BackgroundScheduler()
    monitor_scheduler.add_job(monitor_processes, 'interval', seconds=10, args=[items_queue, telegram_queue],
                              name="process_monitor")
    monitor_scheduler.start()
    logger.info("=== PROCESS STATUS ===")
    logger.info(f"Telegram: {'Alive' if telegram_process.is_alive() else 'Dead'}")
    logger.info(f"Scraper: {'Alive' if scrape_process.is_alive() else 'Dead'}")
    logger.info(f"ItemExtractor: {'Alive' if item_extractor_process.is_alive() else 'Dead'}")
    logger.info(f"Dispatcher: {'Alive' if dispatcher_process.is_alive() else 'Dead'}")
    try:
        while not shutdown_event.is_set():
            try:
                logger.info(
                    f"Queue status - Items: {items_queue.qsize()}, New: {new_items_queue.qsize()}, Telegram: {telegram_queue.qsize()}")
            except NotImplementedError:
                logger.info("Queue status - Size information unavailable on this platform.")
            time.sleep(30)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Main process interrupted")
        shutdown_event.set()
    finally:
        monitor_scheduler.shutdown()
        processes = [
            scrape_process, item_extractor_process, dispatcher_process,
            telegram_process
        ]
        for proc in processes:
            if proc and proc.is_alive():
                logger.info(f"Terminating {proc.name}...")
                proc.terminate()
                proc.join(timeout=5.0)
        db.set_parameter('telegram_process_running', 'False')
        logger.info("All processes terminated")

import sqlite3
from traceback import print_exc
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vinted_notifications.db")
SQL_INIT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "initial_db.sql")

def _init_db_if_needed(conn):
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='parameters'")
        table_exists = cursor.fetchone()
        if not table_exists:
            if os.path.exists(SQL_INIT_PATH):
                with open(SQL_INIT_PATH, "r", encoding="utf-8") as f:
                    conn.executescript(f.read())
                conn.commit()
        else:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            if cursor.fetchone():
                cursor.execute("PRAGMA table_info(users)")
                cols = [col[1] for col in cursor.fetchall()]
                if "created_at" not in cols:
                    cursor.execute("ALTER TABLE users ADD COLUMN created_at INTEGER DEFAULT 0")
                    conn.commit()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='queries'")
            if cursor.fetchone():
                cursor.execute("SELECT COUNT(*) FROM queries")
                cnt = cursor.fetchone()[0]
                if cnt == 0 and os.path.exists(SQL_INIT_PATH):
                    with open(SQL_INIT_PATH, "r", encoding="utf-8") as f:
                        conn.executescript(f.read())
                    conn.commit()
    except Exception:
        print_exc()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    _init_db_if_needed(conn)
    return conn

def create_or_update_sqlite_db(db_path):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"SQL file {db_path} not found")
        with open(db_path, "r", encoding='utf-8') as sql_file:
            sql_script = sql_file.read()
            cursor.executescript(sql_script)
        conn.commit()
        return True
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()

def is_item_in_db_by_id(id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT() FROM items WHERE item=?", (id,))
        if cursor.fetchone()[0]:
            return True
        return False
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()

def get_last_timestamp(query_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT last_item FROM queries WHERE id=?", (query_id,))
        result = cursor.fetchone()
        if result:
            return result[0]
        return None
    except Exception:
        print_exc()
        return None
    finally:
        if conn:
            conn.close()

def update_last_timestamp(query_id, timestamp):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE queries SET last_item=? WHERE id=?", (timestamp, query_id))
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()

def add_item_to_db(id, title, query_id, price, timestamp, photo_url, currency="EUR"):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO items (item, title, price, currency, timestamp, photo_url, query_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id, title, price, currency, timestamp, photo_url, query_id))
        cursor.execute("UPDATE queries SET last_item=? WHERE id=?", (timestamp, query_id))
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()

def get_queries(user_id=None):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if user_id:
            cursor.execute("SELECT id, query, last_item, query_name FROM queries WHERE user_id=?", (user_id,))
        else:
            cursor.execute("SELECT id, query, last_item, query_name FROM queries")
        return cursor.fetchall()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()

def get_query_by_id(query_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, query, last_item, query_name, user_id FROM queries WHERE id=?", (query_id,))
        return cursor.fetchone()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()

def is_query_in_db(processed_query, user_id=None):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if user_id:
            cursor.execute("SELECT COUNT() FROM queries WHERE query = ? AND user_id = ?", (processed_query, user_id))
        else:
            cursor.execute("SELECT COUNT() FROM queries WHERE query = ?", (processed_query,))
        if cursor.fetchone()[0]:
            return True
        return False
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()

def add_query_to_db(query, name=None, user_id=None):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if name:
            cursor.execute("INSERT INTO queries (query, last_item, query_name, user_id) VALUES (?, NULL, ?, ?)", (query, name, user_id))
        else:
            cursor.execute("INSERT INTO queries (query, last_item, user_id) VALUES (?, NULL, ?)", (query, user_id))
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()

def update_query_name(query_id, user_id, new_name):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE queries SET query_name=? WHERE id=? AND user_id=?", (new_name, query_id, user_id))
        conn.commit()
        return True
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()

def remove_query_by_id(query_id, user_id=None):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if user_id:
            cursor.execute("SELECT id FROM queries WHERE id=? AND user_id=?", (query_id, user_id))
        else:
            cursor.execute("SELECT id FROM queries WHERE id=?", (query_id,))
        
        if cursor.fetchone():
            cursor.execute("DELETE FROM items WHERE query_id=?", (query_id,))
            cursor.execute("DELETE FROM queries WHERE id=?", (query_id,))
            conn.commit()
            return True
        return False
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()

def remove_query_from_db(query_number):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query_string = f"SELECT id, query, rowid FROM (SELECT id, query, rowid, ROW_NUMBER() OVER (ORDER BY ROWID) rn FROM queries) t WHERE rn={query_number}"
        cursor.execute(query_string)
        query_result = cursor.fetchone()
        if query_result:
            query_id, query_text, rowid = query_result
            cursor.execute("DELETE FROM items WHERE query_id=?", (query_id,))
            cursor.execute("DELETE FROM queries WHERE ROWID=?", (rowid,))
            conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()

def remove_all_queries_from_db():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM items")
        cursor.execute("DELETE FROM queries")
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()

def clear_items_only():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM items")
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()

def add_to_allowlist(country):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO allowlist VALUES (?)", (country,))
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()

def remove_from_allowlist(country):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM allowlist WHERE country=?", (country,))
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()

def get_allowlist():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM allowlist")
        countries = [country[0] for country in cursor.fetchall()]
        if not countries:
            return 0
        return countries
    finally:
        if conn:
            conn.close()

def clear_allowlist():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM allowlist")
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()

def get_parameter(key):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM parameters WHERE key=?", (key,))
        result = cursor.fetchone()
        return result[0] if result else None
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()

def set_parameter(key, value):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO parameters (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()

def get_all_parameters():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM parameters")
        return {row[0]: row[1] for row in cursor.fetchall()}
    except Exception:
        print_exc()
        return {}
    finally:
        if conn:
            conn.close()

def get_items(limit=50, query=None, user_id=None):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if query:
            if user_id:
                cursor.execute("SELECT id FROM queries WHERE query=? AND user_id=?", (query, user_id))
            else:
                cursor.execute("SELECT id FROM queries WHERE query=?", (query,))
            result = cursor.fetchone()
            if result:
                query_id = result[0]
                cursor.execute(
                    "SELECT i.item, i.title, i.price, i.currency, i.timestamp, q.query, i.photo_url FROM items i JOIN queries q ON i.query_id = q.id WHERE i.query_id=? ORDER BY i.timestamp DESC LIMIT ?",
                    (query_id, limit))
            else:
                return []
        else:
            if user_id:
                cursor.execute(
                    "SELECT i.item, i.title, i.price, i.currency, i.timestamp, q.query, i.photo_url FROM items i JOIN queries q ON i.query_id = q.id WHERE q.user_id=? ORDER BY i.timestamp DESC LIMIT ?",
                    (user_id, limit))
            else:
                cursor.execute(
                    "SELECT i.item, i.title, i.price, i.currency, i.timestamp, q.query, i.photo_url FROM items i JOIN queries q ON i.query_id = q.id ORDER BY i.timestamp DESC LIMIT ?",
                    (limit,))
        return cursor.fetchall()
    except Exception:
        print_exc()
        return []
    finally:
        if conn:
            conn.close()

def get_total_items_count():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM items")
        return cursor.fetchone()[0]
    except Exception:
        print_exc()
        return 0
    finally:
        if conn:
            conn.close()

def get_total_queries_count():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM queries")
        return cursor.fetchone()[0]
    except Exception:
        print_exc()
        return 0
    finally:
        if conn:
            conn.close()

def get_last_found_item():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT i.item, i.title, i.price, i.currency, i.timestamp, q.query, i.photo_url FROM items i JOIN queries q ON i.query_id = q.id ORDER BY i.timestamp DESC LIMIT 1")
        return cursor.fetchone()
    except Exception:
        print_exc()
        return None
    finally:
        if conn:
            conn.close()

def get_items_per_day():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM items")
        total_items = cursor.fetchone()[0]
        if total_items == 0:
            return 0
        cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM items")
        min_timestamp, max_timestamp = cursor.fetchone()
        min_date = datetime.fromtimestamp(min_timestamp).date()
        max_date = datetime.fromtimestamp(max_timestamp).date()
        days_diff = (max_date - min_date).days + 1
        days_diff = max(1, days_diff)
        return round(total_items / days_diff, 1)
    except Exception:
        print_exc()
        return 0
    finally:
        if conn:
            conn.close()


def remove_all_user_queries_from_db(user_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM items WHERE query_id IN (SELECT id FROM queries WHERE user_id=?)", (user_id,))
        cursor.execute("DELETE FROM queries WHERE user_id=?", (user_id,))
        conn.commit()
    except Exception:
        from traceback import print_exc
        print_exc()
    finally:
        if conn:
            conn.close()

import os
import sqlite3
import time
import hashlib
import hmac
import json
from urllib.parse import parse_qs

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vinted_notifications.db")


def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    return conn


# --- TMA AUTH & USER MANAGEMENT ---

def verify_tg_data(init_data, bot_token):
    if not init_data or not bot_token:
        return False, None
    try:
        parsed_data = parse_qs(init_data)
        hash_str = parsed_data.get('hash', [None])[0]
        if not hash_str:
            return False, None
        data_check_list = sorted([f"{k}={v[0]}" for k, v in parsed_data.items() if k != 'hash'])
        data_check_string = "\n".join(data_check_list)
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if calculated_hash == hash_str:
            return True, json.loads(parsed_data.get('user', ['{}'])[0])
        return False, None
    except Exception:
        return False, None


def get_or_create_user(telegram_id, username=None, referred_by_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = cursor.fetchone()

    now = int(time.time())
    if not user:
        cursor.execute("""
            INSERT INTO users (telegram_id, username, is_admin, is_banned, created_at)
            VALUES (?, ?, 1, 0, ?)
        """, (telegram_id, username, now))
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        user = cursor.fetchone()
    else:
        if not user['is_admin']:
            cursor.execute("UPDATE users SET is_admin = 1 WHERE telegram_id = ?", (telegram_id,))
            conn.commit()
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            user = cursor.fetchone()
        if username and user['username'] != username:
            cursor.execute("UPDATE users SET username = ? WHERE telegram_id = ?", (username, telegram_id))
            conn.commit()
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            user = cursor.fetchone()

    conn.close()
    return dict(user)


def get_user_status(user_id):
    return "Активен"


def has_active_subscription(user_id):
    return True


def is_admin(telegram_id):
    return True


def set_admin_status(telegram_id, status: bool):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_admin = ? WHERE telegram_id = ?", (1 if status else 0, telegram_id))
    conn.commit()
    conn.close()


def ban_user(telegram_id, status: bool):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_banned = ? WHERE telegram_id = ?", (1 if status else 0, telegram_id))
    conn.commit()
    conn.close()


def is_user_banned(telegram_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_banned FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row['is_banned']) if row else False


def get_all_users_count():
    conn = get_db_connection()
    cursor = conn.cursor()
    count = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return count


def get_all_telegram_ids():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id FROM users")
    ids = [row['telegram_id'] for row in cursor.fetchall()]
    conn.close()
    return ids


def get_all_admin_ids():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id FROM users WHERE is_admin = 1")
    ids = [row['telegram_id'] for row in cursor.fetchall()]
    conn.close()
    return ids


def get_active_subscribers():
    """Returns a list of telegram_ids for active users (not banned)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id FROM users WHERE is_banned = 0")
    ids = [row['telegram_id'] for row in cursor.fetchall()]
    conn.close()
    return ids


def search_users(query_str):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        user_id = int(query_str)
        cursor.execute("SELECT * FROM users WHERE telegram_id = ? OR id = ?", (user_id, user_id))
    except ValueError:
        pattern = f"%{query_str}%"
        cursor.execute("SELECT * FROM users WHERE username LIKE ?", (pattern,))

    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def admin_get_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    stats = {
        'total_users': cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        'active_users': cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 0").fetchone()[0],
        'total_queries': cursor.execute("SELECT COUNT(*) FROM queries").fetchone()[0],
    }
    conn.close()
    return stats


def admin_get_users(limit=50):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]




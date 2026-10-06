import sqlite3
import time
import hashlib
import hmac
import json
import uuid
import base64
from urllib.parse import parse_qs

try:
    from aiocryptopay import AioCryptoPay, Networks
except ImportError:
    AioCryptoPay, Networks = None, None

DB_PATH = "vinted_notifications.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    return conn

# --- TMA AUTH & USER ---
def verify_tg_data(init_data, bot_token):
    if not init_data or not bot_token:
        return False, None
    try:
        parsed_data = parse_qs(init_data)
        hash_str = parsed_data.get('hash', [None])[0]
        if not hash_str: return False, None
        data_check_list = sorted([f"{k}={v[0]}" for k, v in parsed_data.items() if k != 'hash'])
        data_check_string = "\n".join(data_check_list)
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if calculated_hash == hash_str:
            return True, json.loads(parsed_data.get('user', ['{}'])[0])
        return False, None
    except: return False, None

def get_or_create_user(telegram_id, username=None, referred_by_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = cursor.fetchone()
    
    now = int(time.time())
    if not user:
        ref_code = str(uuid.uuid4())[:8]
        cursor.execute("""
            INSERT INTO users (telegram_id, username, is_admin, is_banned, subscription_expiry, subscription_type, referral_code, referred_by, created_at)
            VALUES (?, ?, 1, 0, 9999999999, 'unlimited', ?, ?, ?)
        """, (telegram_id, username, ref_code, referred_by_id, now))
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        user = cursor.fetchone()
    else:
        cursor.execute("UPDATE users SET is_admin = 1, subscription_expiry = 9999999999, subscription_type = 'unlimited' WHERE telegram_id = ?", (telegram_id,))
        if username and user['username'] != username:
            cursor.execute("UPDATE users SET username = ? WHERE telegram_id = ?", (username, telegram_id))
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        user = cursor.fetchone()
    
    conn.close()
    return dict(user)

def get_user_status(user_id):
    return "Безлимит (100% доступ)"

# --- PAYMENTS: LIQPAY & CRYPTOBOT ---
def get_setting(key):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM commercial_settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row['value'] if row else None

def update_setting(key, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO commercial_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def create_liqpay_payment(user_id, amount, currency="UAH", sub_type="basic"):
    public_key = get_setting('liqpay_public_key')
    private_key = get_setting('liqpay_private_key')
    order_id = f"vinted_{user_id}_{sub_type}_{int(time.time())}"
    
    params = {
        "public_key": public_key,
        "version": "3",
        "action": "pay",
        "amount": amount,
        "currency": currency,
        "description": f"Vinted PRO Subscription ({sub_type}, 30 days)",
        "order_id": order_id,
        "result_url": "https://t.me/your_bot", # Redirect after payment
        "server_url": "https://your-domain.com/api/liqpay_callback" # Callback URL
    }
    
    data = base64.b64encode(json.dumps(params).encode()).decode()
    signature = base64.b64encode(hashlib.sha1((private_key + data + private_key).encode()).digest()).decode()
    
    # Save pending payment
    create_payment_record(user_id, amount, currency, "liqpay", order_id, sub_type=sub_type)
    
    return f"https://www.liqpay.ua/api/3/checkout?data={data}&signature={signature}"

def create_payment_record(user_id, amount, currency, method, external_id, sub_type="basic"):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO payments (user_id, amount, currency, method, status, external_id, created_at, subscription_type)
        VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
    ''', (user_id, amount, currency, method, external_id, int(time.time()), sub_type))
    conn.commit()
    conn.close()

def process_payment_success(user_id, days=30, sub_type="basic"):
    conn = get_db_connection()
    cursor = conn.cursor()
    # 1. Update user subscription
    now = int(time.time())
    cursor.execute("SELECT subscription_expiry, referred_by FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    current_expiry = row['subscription_expiry']
    referred_by = row['referred_by']
    
    new_expiry = max(current_expiry, now) + (days * 24 * 3600)
    cursor.execute("UPDATE users SET subscription_expiry = ?, subscription_type = ? WHERE id = ?", (new_expiry, sub_type, user_id))
    
    # 2. Handle Referral Reward
    if referred_by:
        reward_days = int(get_setting('referral_reward_days') or 5)
        cursor.execute("SELECT subscription_expiry FROM users WHERE id = ?", (referred_by,))
        ref_row = cursor.fetchone()
        if ref_row:
            ref_expiry = max(ref_row['subscription_expiry'], now) + (reward_days * 24 * 3600)
            cursor.execute("UPDATE users SET subscription_expiry = ? WHERE id = ?", (ref_expiry, referred_by))
            # Log reward
            print(f"Referral reward given to user {referred_by}")

    conn.commit()
    conn.close()

# --- ADMIN PANEL ---
def admin_get_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    stats = {
        'total_users': cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        'active_users': cursor.execute("SELECT COUNT(*) FROM users WHERE subscription_expiry > ?", (int(time.time()),)).fetchone()[0],
        'total_revenue': cursor.execute("SELECT SUM(amount) FROM payments WHERE status='success'").fetchone()[0] or 0
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

def admin_generate_key(days=30, sub_type="basic"):
    key = str(uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO subscription_keys (key, duration_days, subscription_type) VALUES (?, ?, ?)", (key, days, sub_type))
    conn.commit()
    conn.close()
    return key

def activate_key(user_id, key):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM subscription_keys WHERE key = ? AND is_used = 0", (key,))
    key_row = cursor.fetchone()
    if not key_row: return False, "Invalid key"
    process_payment_success(user_id, key_row['duration_days'], sub_type=key_row['subscription_type'])
    cursor.execute("UPDATE subscription_keys SET is_used = 1, used_by = ?, used_at = ? WHERE key = ?", 
                   (user_id, int(time.time()), key))
    conn.commit()
    conn.close()
    return True, "Success!"

# --- REFS ---
def get_user_referrals(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, telegram_id FROM users WHERE referred_by = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_crypto_client():
    token = get_setting('crypto_token')
    if not token:
        return None
    return AioCryptoPay(token=token, network=Networks.MAIN_NET)

async def create_crypto_invoice(user_id, amount_usdt=5.0, days=30, sub_type="basic"):
    client = get_crypto_client()
    if client is None:
        return None, None
    order_id = f'vinted_{user_id}_{sub_type}_{int(time.time())}'
    desc = f'Vinted PRO {days} days'
    invoice = await client.create_invoice(asset='USDT', amount=amount_usdt, description=desc, payload=order_id)
    create_payment_record(user_id, amount_usdt, 'USDT', 'cryptobot', str(invoice.invoice_id), sub_type=sub_type)
    return invoice.bot_invoice_url, str(invoice.invoice_id)

def get_pending_crypto_invoices():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT external_id FROM payments WHERE method = 'cryptobot' AND status = 'pending'")
    rows = cursor.fetchall()
    conn.close()
    return [row['external_id'] for row in rows]

async def check_crypto_invoice(invoice_id):
    client = get_crypto_client()
    if client is None:
        return False
    invoices = await client.get_invoices(invoice_ids=invoice_id)
    invoice = invoices[0] if invoices else None
    
    if not invoice or invoice.status != 'paid':
        return False
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE payments SET status = 'success' WHERE method = 'cryptobot' AND external_id = ?",
        (invoice_id,)
    )
    conn.commit()
    conn.close()
    
    payload = invoice.payload or ''
    parts = payload.split('_')
    # vinted_USERID_SUBTYPE_TIMESTAMP
    if len(parts) >= 3 and parts[1].isdigit():
        user_id = int(parts[1])
        sub_type = parts[2]
        process_payment_success(user_id, sub_type=sub_type)
    elif len(parts) >= 2 and parts[1].isdigit():
        # Fallback for old invoices
        user_id = int(parts[1])
        process_payment_success(user_id)
    return True

def is_admin(telegram_id):
    return True

def get_all_users_count():
    conn = get_db_connection()
    cursor = conn.cursor()
    count = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return count

def get_active_subscriptions_count():
    conn = get_db_connection()
    cursor = conn.cursor()
    count = cursor.execute("SELECT COUNT(*) FROM users WHERE subscription_expiry > ?", (int(time.time()),)).fetchone()[0]
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
    # Try to match by ID or Username
    try:
        user_id = int(query_str)
        cursor.execute("SELECT * FROM users WHERE telegram_id = ? OR id = ?", (user_id, user_id))
    except ValueError:
        pattern = f"%{query_str}%"
        cursor.execute("SELECT * FROM users WHERE username LIKE ?", (pattern,))
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def set_user_subscription(telegram_id, days):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = int(time.time())
    new_expiry = now + (days * 24 * 3600)
    cursor.execute("UPDATE users SET subscription_expiry = ? WHERE telegram_id = ?", (new_expiry, telegram_id))
    conn.commit()
    conn.close()


def add_user_subscription_days(telegram_id, days):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = int(time.time())
    cursor.execute("SELECT subscription_expiry FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False

    current_expiry = row['subscription_expiry'] or 0
    base_ts = max(current_expiry, now)
    new_expiry = base_ts + (days * 24 * 3600)
    cursor.execute("UPDATE users SET subscription_expiry = ? WHERE telegram_id = ?", (new_expiry, telegram_id))
    conn.commit()
    conn.close()
    return True


def has_active_subscription(user_id):
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

def admin_get_recent_payments(limit=10):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.*, u.username, u.telegram_id 
        FROM payments p 
        JOIN users u ON p.user_id = u.id 
        ORDER BY p.created_at DESC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# --- MULTI-ACCOUNT SNIPER ---

def get_user_sniper_settings(user_id):
    """Get sniper settings for a specific telegram_id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_sniper_settings WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {
        "user_id": user_id,
        "enabled": False,
        "proxy": "",
        "session_cookie": "",
        "domain": "www.vinted.fr"
    }

def update_user_sniper_setting(user_id, key, value):
    """Update a specific sniper setting for a telegram_id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    # Ensure row exists
    cursor.execute("INSERT OR IGNORE INTO user_sniper_settings (user_id) VALUES (?)", (user_id,))
    
    # Safe list of updatable columns
    if key in ["enabled", "proxy", "session_cookie", "domain"]:
        query = f"UPDATE user_sniper_settings SET {key} = ?, updated_at = strftime('%s', 'now') WHERE user_id = ?"
        cursor.execute(query, (value, user_id))
    
    conn.commit()
    conn.close()

def get_all_enabled_snipers():
    """Returns a list of user_id for users who have sniper enabled."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM user_sniper_settings WHERE enabled = 1")
    rows = cursor.fetchall()
    conn.close()
    return [row['user_id'] for row in rows]

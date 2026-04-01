import os
import sqlite3
from dotenv import load_dotenv

def sync():
    load_dotenv()
    db_path = "vinted_notifications.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("Syncing .env values to database...")

    # Mapping from .env variable to (table, key)
    mapping = {
        'TELEGRAM_TOKEN': ('parameters', 'telegram_token'),
        'BOT_USERNAME': ('commercial_settings', 'bot_username'),
        'CRYPTO_TOKEN': ('commercial_settings', 'crypto_token'),
        'CRYPTO_PRICE_USDT': ('commercial_settings', 'crypto_price_usdt'),
        'SUBSCRIPTION_PRICE_30D': ('commercial_settings', 'subscription_price_30d'),
        'REFERRAL_REWARD_DAYS': ('commercial_settings', 'referral_reward_days'),
        'ADMIN_CONTACTS': ('commercial_settings', 'admin_contacts'),
    }

    for env_var, (table, key) in mapping.items():
        value = os.getenv(env_var)
        if value:
            print(f"Updating {table}.{key} = {value}")
            cursor.execute(f"UPDATE {table} SET value=? WHERE key=?", (value, key))
            if cursor.rowcount == 0:
                if table == 'commercial_settings':
                    cursor.execute(f"INSERT OR IGNORE INTO {table} (key, value) VALUES (?, ?)", (key, value))

    conn.commit()
    conn.close()
    print("Sync completed.")

if __name__ == "__main__":
    sync()

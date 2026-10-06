"""
migrate_sniper.py — Миграция базы данных для AntiGravity Sniper.

Запустить один раз для добавления таблицы snipe_log и параметров снайпера
в существующую базу данных.

Usage:
    python migrate_sniper.py
"""

import sqlite3
import sys

DB_PATH = "vinted_notifications.db"


def migrate():
    print(f"Migrating database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Create snipe_log table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS snipe_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id TEXT NOT NULL,
            item_title TEXT,
            price REAL,
            currency TEXT,
            status TEXT,
            latency_ms REAL,
            checkout_url TEXT,
            target_user_id INTEGER,
            error_detail TEXT,
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        )
    """)
    print("  ✅ snipe_log table created")

    # 2. Create user_sniper_settings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_sniper_settings (
            user_id INTEGER PRIMARY KEY,
            enabled BOOLEAN DEFAULT 0,
            proxy TEXT,
            session_cookie TEXT,
            domain TEXT DEFAULT 'www.vinted.fr',
            updated_at INTEGER DEFAULT (strftime('%s', 'now'))
        )
    """)
    print("  ✅ user_sniper_settings table created")

    # 3. Create indexes
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_snipe_log_item ON snipe_log(item_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_snipe_log_status ON snipe_log(status)"
    )
    print("  ✅ Indexes created")

    # 4. Insert global sniper parameters (will be deprecated, but kept for fallback)
    params = [
        ("sniper_enabled", "False"),
        ("sniper_proxy", ""),
        ("sniper_session_cookie", ""),
        ("sniper_vinted_domain", "www.vinted.fr"),
        (
            "sniper_user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ),
    ]
    for key, value in params:
        cursor.execute(
            "INSERT OR IGNORE INTO parameters (key, value) VALUES (?, ?)",
            (key, value),
        )
    print("  ✅ Global sniper parameters inserted")

    # 5. Clean up legacy parameters
    cursor.execute("DELETE FROM parameters WHERE key = 'legit_check_token'")
    cursor.execute(
        "DELETE FROM commercial_settings WHERE key = 'crypto_price_bot_legit_usdt'"
    )
    print("  ✅ Legacy legit parameters cleaned up")

    conn.commit()
    conn.close()
    print("\n🎯 Migration complete! You can now configure the sniper via the Telegram admin panel.")


if __name__ == "__main__":
    migrate()

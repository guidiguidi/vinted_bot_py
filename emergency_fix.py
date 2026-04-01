import sqlite3

def fix():
    conn = sqlite3.connect("vinted_notifications.db")
    cursor = conn.cursor()
    
    print("Проверка и исправление базы данных...")
    
    # 1. Проверяем таблицу users
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN referral_code TEXT")
        print("Колонка referral_code добавлена.")
    except sqlite3.OperationalError:
        print("Колонка referral_code уже есть.")

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
        print("Колонка referred_by добавлена.")
    except sqlite3.OperationalError:
        print("Колонка referred_by уже есть.")

    # 2. Проверяем таблицу subscription_keys
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS subscription_keys (
        key TEXT PRIMARY KEY,
        duration_days INTEGER,
        is_used BOOLEAN DEFAULT 0,
        used_by INTEGER,
        used_at INTEGER
    )
    ''')
    
    # 3. Проверяем таблицу commercial_settings
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS commercial_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    ''')

    # 4. Проверяем таблицу payments
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        currency TEXT,
        method TEXT,
        status TEXT,
        external_id TEXT,
        created_at INTEGER
    )
    ''')

    conn.commit()
    conn.close()
    print("Готово! Все таблицы исправлены.")

if __name__ == "__main__":
    fix()

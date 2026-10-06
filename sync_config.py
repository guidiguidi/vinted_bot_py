import os
import sqlite3
from dotenv import load_dotenv


def sync():
    load_dotenv()
    db_path = "vinted_notifications.db"
    if not os.path.exists(db_path):
        return

    token = os.getenv("TELEGRAM_TOKEN")
    if token:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE parameters SET value=? WHERE key='telegram_token'", (token,))
        if cursor.rowcount == 0:
            cursor.execute("INSERT OR IGNORE INTO parameters (key, value) VALUES ('telegram_token', ?)", (token,))
        conn.commit()
        conn.close()
        print(f"Synced TELEGRAM_TOKEN: {token[:10]}...")


if __name__ == "__main__":
    sync()

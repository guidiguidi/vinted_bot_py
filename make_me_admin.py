import sqlite3
import os

def set_admin():
    db_path = "vinted_notifications.db"
    if not os.path.exists(db_path):
        print(f"Ошибка: База данных {db_path} не найдена!")
        return

    tid = input("Введите ваш Telegram ID (только цифры): ").strip()
    if not tid.isdigit():
        print("Ошибка: ID должен состоять только из цифр!")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Сначала проверим, есть ли такой юзер в базе (он должен был хотя бы раз написать /start)
    cursor.execute("SELECT id, username FROM users WHERE telegram_id = ?", (tid,))
    user = cursor.fetchone()
    
    if user:
        cursor.execute("UPDATE users SET is_admin = 1 WHERE telegram_id = ?", (tid,))
        conn.commit()
        print(f"✅ Успех! Пользователь @{user[1]} (ID: {tid}) теперь администратор.")
    else:
        print(f"❌ Ошибка: Пользователь с ID {tid} не найден в базе данных.")
        print("Сначала напишите боту /start в Телеграме, а потом запустите этот скрипт снова.")

    conn.close()

if __name__ == "__main__":
    set_admin()

import sqlite3
import os

def set_admins():
    db_path = "vinted_notifications.db"
    if not os.path.exists(db_path):
        print(f"Ошибка: База данных {db_path} не найдена!")
        return

    admin_ids = ["913862074", "525127130"]
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    for tid in admin_ids:
        # Проверяем, есть ли юзер, если нет - создаем заглушку, чтобы потом можно было зайти
        cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (tid,))
        user = cursor.fetchone()
        
        if user:
            cursor.execute("UPDATE users SET is_admin = 1 WHERE telegram_id = ?", (tid,))
            print(f"✅ Пользователь {tid} теперь администратор.")
        else:
            # Если пользователя нет, создаем его сразу админом
            import uuid
            ref_code = str(uuid.uuid4())[:8]
            cursor.execute("INSERT INTO users (telegram_id, is_admin, referral_code) VALUES (?, 1, ?)", (tid, ref_code))
            print(f"✅ Пользователь {tid} не был в базе, создан новый профиль администратора.")
    
    conn.commit()
    conn.close()
    print("Готово! Все указанные ID теперь имеют права администратора.")

if __name__ == "__main__":
    set_admins()

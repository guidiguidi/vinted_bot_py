-- Таблица пользователей
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE,
    username TEXT,
    is_admin BOOLEAN DEFAULT 1,
    is_banned BOOLEAN DEFAULT 0,
    created_at INTEGER
);

-- Создание таблицы queries
CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    last_item INTEGER,
    query_name TEXT,
    user_id INTEGER,
    UNIQUE(query, user_id)
);

-- Создание таблицы items
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item TEXT NOT NULL,
    title TEXT,
    price REAL,
    currency TEXT DEFAULT 'EUR',
    timestamp INTEGER,
    photo_url TEXT,
    query_id INTEGER,
    FOREIGN KEY (query_id) REFERENCES queries (id) ON DELETE CASCADE,
    UNIQUE(item, query_id)
);

-- Создание таблицы allowlist
CREATE TABLE IF NOT EXISTS allowlist (
    country TEXT PRIMARY KEY
);

-- Создание таблицы parameters
CREATE TABLE IF NOT EXISTS parameters (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Вставка начальных параметров
INSERT OR IGNORE INTO parameters (key, value) VALUES
('telegram_enabled', 'True'),
('telegram_token', ''),
('items_per_query', '20'),
('query_refresh_delay', '60'),
('check_proxies', 'False'),
('proxy_list', ''),
('proxy_list_link', ''),
('dataimpulse_api_token', ''),
('dataimpulse_plan_mb', '0'),
('dataimpulse_tz', 'Europe/Kyiv'),
('last_proxy_check_time', '1'),
('telegram_process_running', 'False'),
('rss_process_running', 'False'),
('github_url', 'https://github.com/guidiguidi/vinted_bot_py'),
('version', '1.0.0');

-- Создание индексов для улучшения производительности
CREATE INDEX IF NOT EXISTS idx_items_timestamp ON items(timestamp);
CREATE INDEX IF NOT EXISTS idx_items_query_id ON items(query_id);
CREATE INDEX IF NOT EXISTS idx_queries_query ON queries(query);
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
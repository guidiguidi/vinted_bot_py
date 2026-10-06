-- Таблица пользователей (расширенная)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE,
    username TEXT,
    is_admin BOOLEAN DEFAULT 0,
    is_banned BOOLEAN DEFAULT 0,
    subscription_expiry INTEGER DEFAULT 0,
    subscription_type TEXT DEFAULT 'basic',
    referral_code TEXT UNIQUE,
    referred_by INTEGER,
    created_at INTEGER
);

-- Таблица платежей
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    currency TEXT,
    method TEXT,
    status TEXT,
    external_id TEXT,
    subscription_type TEXT,
    created_at INTEGER,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- Таблица ключей активации
CREATE TABLE IF NOT EXISTS subscription_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE,
    duration_days INTEGER,
    subscription_type TEXT,
    is_used BOOLEAN DEFAULT 0,
    used_by INTEGER,
    used_at INTEGER,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY (used_by) REFERENCES users (id)
);

-- Таблица коммерческих настроек
CREATE TABLE IF NOT EXISTS commercial_settings (
    key TEXT PRIMARY KEY,
    value TEXT
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
('github_url', 'https://github.com/your-repo'),
('version', '1.0.0');

-- Вставка коммерческих настроек
INSERT OR IGNORE INTO commercial_settings (key, value) VALUES
('crypto_price_usdt', '5.0'),
('crypto_price_bot_legit_usdt', '10.0'),
('referral_reward_days', '5'),
('crypto_token', '');

-- Параметры AntiGravity Sniper
INSERT OR IGNORE INTO parameters (key, value) VALUES
('sniper_enabled', 'False'),
('sniper_proxy', ''),
('sniper_session_cookie', ''),
('sniper_vinted_domain', 'www.vinted.fr'),
('sniper_user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36');

-- Таблица логов снайпера
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
);

-- Таблица настроек снайпера для пользователей (Multi-Account)
CREATE TABLE IF NOT EXISTS user_sniper_settings (
    user_id INTEGER PRIMARY KEY, -- Telegram ID
    enabled BOOLEAN DEFAULT 0,
    proxy TEXT,
    session_cookie TEXT,
    domain TEXT DEFAULT 'www.vinted.fr',
    updated_at INTEGER DEFAULT (strftime('%s', 'now'))
);

-- Создание индексов для улучшения производительности
CREATE INDEX IF NOT EXISTS idx_items_timestamp ON items(timestamp);
CREATE INDEX IF NOT EXISTS idx_items_query_id ON items(query_id);
CREATE INDEX IF NOT EXISTS idx_queries_query ON queries(query);
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_keys_key ON subscription_keys(key);
CREATE INDEX IF NOT EXISTS idx_snipe_log_item ON snipe_log(item_id);
CREATE INDEX IF NOT EXISTS idx_snipe_log_status ON snipe_log(status);
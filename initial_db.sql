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

-- Начальные пользователи
INSERT OR IGNORE INTO users (id, telegram_id, username, is_admin, is_banned, created_at) VALUES
(1, 525127130, 'admin', 1, 0, 1700000000),
(2, 8025919160, 'paragein', 1, 0, 1700000000),
(3, 913862074, 'admin', 1, 0, 1700000000),
(4, 7636899263, 's4uce10', 1, 0, 1700000000),
(5, 899565284, 'black1resale', 1, 0, 1700000000),
(6, 732024902, 'user_732024902', 1, 0, 1700000000),
(7, 944233674, 'user_944233674', 1, 0, 1700000000),
(8, 8666520865, 'hangetdUnsu', 1, 0, 1700000000),
(9, 5141940909, 'llinkovv', 1, 0, 1700000000);

-- Начальные поисковые запросы
INSERT OR IGNORE INTO queries (id, query, last_item, query_name, user_id) VALUES
(9, 'https://www.vinted.de/catalog?order=newest_first&size_ids%5B%5D=208&size_ids%5B%5D=209&size_ids%5B%5D=210&size_ids%5B%5D=1640&size_ids%5B%5D=1641&size_ids%5B%5D=1642&size_ids%5B%5D=786&size_ids%5B%5D=787&size_ids%5B%5D=788&size_ids%5B%5D=789&brand_ids%5B%5D=2369&brand_ids%5B%5D=145654&brand_ids%5B%5D=1003289&brand_ids%5B%5D=484649&brand_ids%5B%5D=1670540&brand_ids%5B%5D=923398&brand_ids%5B%5D=344976&brand_ids%5B%5D=505614&brand_ids%5B%5D=639289&brand_ids%5B%5D=671&brand_ids%5B%5D=83122', 0, 'приколы', 525127130),
(10, 'https://www.vinted.be/catalog?status_ids%5B%5D=3&status_ids%5B%5D=2&status_ids%5B%5D=1&status_ids%5B%5D=6&status_ids%5B%5D=4&brand_ids%5B%5D=270420&brand_ids%5B%5D=145654&brand_ids%5B%5D=2369&brand_ids%5B%5D=1885278&brand_ids%5B%5D=891681&brand_ids%5B%5D=95106&order=newest_first', 0, 'BE Brands', 732024902),
(11, 'https://www.vinted.be/catalog?search_text=Balenciaga%2520&brand_ids%5B%5D=2369&brand_ids%5B%5D=10390185&brand_ids%5B%5D=6483274&brand_ids%5B%5D=7492757&order=newest_first', 0, 'Balenciaga BE', 913862074),
(12, 'https://www.vinted.at/catalog?brand_ids%5B%5D=2369&brand_ids%5B%5D=145654&brand_ids%5B%5D=270420&brand_ids%5B%5D=95106&brand_ids%5B%5D=1885278&brand_ids%5B%5D=1996050&order=newest_first', 0, 'AT Brands', 944233674),
(13, 'https://www.vinted.co.uk/catalog?order=newest_first&size_ids%5B%5D=208&size_ids%5B%5D=209&size_ids%5B%5D=210&size_ids%5B%5D=1640&size_ids%5B%5D=1641&size_ids%5B%5D=1642&size_ids%5B%5D=786&size_ids%5B%5D=787&size_ids%5B%5D=788&size_ids%5B%5D=789&brand_ids%5B%5D=2369&brand_ids%5B%5D=145654&brand_ids%5B%5D=1003289&brand_ids%5B%5D=484649&brand_ids%5B%5D=1670540&brand_ids%5B%5D=923398&brand_ids%5B%5D=344976&brand_ids%5B%5D=505614&brand_ids%5B%5D=639289&brand_ids%5B%5D=671&brand_ids%5B%5D=83122&brand_ids%5B%5D=319587&currency=EUR', 0, 'UK Brands', 525127130),
(14, 'https://www.vinted.it/catalog?order=newest_first&size_ids%5B%5D=208&size_ids%5B%5D=209&size_ids%5B%5D=210&size_ids%5B%5D=1640&size_ids%5B%5D=1641&size_ids%5B%5D=1642&size_ids%5B%5D=786&size_ids%5B%5D=787&size_ids%5B%5D=788&size_ids%5B%5D=789&brand_ids%5B%5D=2369&brand_ids%5B%5D=145654&brand_ids%5B%5D=1003289&brand_ids%5B%5D=484649&brand_ids%5B%5D=1670540&brand_ids%5B%5D=923398&brand_ids%5B%5D=344976&brand_ids%5B%5D=505614&brand_ids%5B%5D=639289&brand_ids%5B%5D=671&brand_ids%5B%5D=83122&brand_ids%5B%5D=319587&currency=EUR', 0, 'IT Brands', 525127130),
(15, 'https://www.vinted.pl/catalog?order=newest_first&size_ids%5B%5D=208&size_ids%5B%5D=209&size_ids%5B%5D=210&size_ids%5B%5D=1640&size_ids%5B%5D=1641&size_ids%5B%5D=1642&size_ids%5B%5D=786&size_ids%5B%5D=787&size_ids%5B%5D=788&size_ids%5B%5D=789&brand_ids%5B%5D=2369&brand_ids%5B%5D=145654&brand_ids%5B%5D=1003289&brand_ids%5B%5D=484649&brand_ids%5B%5D=1670540&brand_ids%5B%5D=923398&brand_ids%5B%5D=344976&brand_ids%5B%5D=505614&brand_ids%5B%5D=639289&brand_ids%5B%5D=671&brand_ids%5B%5D=83122&brand_ids%5B%5D=319587&currency=EUR', 0, 'PL Brands', 525127130);
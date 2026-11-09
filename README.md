# 👗 Vinted Marketplace Real-Time Scraper & Monitor

A high-performance, asynchronous monitoring engine and Telegram notification service for **Vinted**, featuring dynamic residential proxy rotation, user-agent randomization, and SQLite deduplication.

---

## 🚀 Key Highlights & Capabilities

Scraping Vinted at scale requires bypassing aggressive rate-limiting, IP reputation checks, and country-specific marketplace routing.

### 1. 🔍 High-Concurrency Item Discovery
- Real-time catalog polling with sub-minute latency.
- Intelligent query management with user-defined filters (price bounds, country allowlists, brand/size queries).
- Telegram bot interface providing instant interactive alerts with direct buy links, item photos, and seller ratings.

### 2. 🌐 Advanced Proxy & Network Infrastructure (`proxies.py`)
- **Multi-Format Ingestion:** Supports `ip:port:user:pass`, `user:pass@ip:port`, HTTP/HTTPS, and SOCKS5 residential protocols.
- **Dynamic Pool Management:** Automatic health-checking, latency-based scoring, and automatic dead-proxy pruning.
- **Provider Synchronization:** Native integration with proxy providers (e.g. DataImpulse) and remote endpoint proxy list auto-refreshing.
- **Anti-Bot Rotation:** Synchronized User-Agent randomization and header normalization aligned with proxy geo-exit points.

### 3. 💾 State Management & Deduplication
- Asynchronous SQLite indexing preventing duplicate notifications across thousands of active searches.
- Historical price drop tracking and instant alert dispatching to target Telegram channels.

---

## 🛠️ Tech Stack

- **Language:** Python 3.11+ (AsyncIO, aiohttp)
- **Database:** SQLite / SQLAlchemy for persistent state caching
- **Interface:** Telegram Bot API (aiogram / pyTelegramBotAPI)
- **Deployment:** Docker, systemd, Procfile support

---

## 🚀 Quickstart

```bash
# Clone the repository
git clone https://github.com/guidiguidi/vinted_bot_py.git
cd vinted_bot_py

# Set up environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure bot token
echo "TELEGRAM_TOKEN=your_telegram_bot_token" > .env

# Run the monitoring engine
python3 vinted_notifications.py
```

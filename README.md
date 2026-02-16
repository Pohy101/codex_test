# Discord ↔ Telegram Bridge

Сервис пересылает сообщения между указанными каналами Discord и чатами Telegram.

## 1) Создание ботов в Discord и Telegram

### Discord
1. Откройте [Discord Developer Portal](https://discord.com/developers/applications).
2. Создайте новое приложение (`New Application`).
3. В разделе **Bot** добавьте бота (`Add Bot`).
4. Скопируйте токен бота — это значение для `DISCORD_BOT_TOKEN`.
5. В разделе **Privileged Gateway Intents** включите как минимум:
   - `MESSAGE CONTENT INTENT`

### Telegram
1. Откройте `@BotFather` в Telegram.
2. Выполните команду `/newbot` и следуйте шагам.
3. Скопируйте токен — это значение для `TELEGRAM_BOT_TOKEN`.

## 2) Выдача прав и получение channel/chat id

### Discord: права и ID канала
1. Пригласите бота на сервер через OAuth2 URL (Scopes: `bot`, Bot Permissions: минимум `View Channels`, `Send Messages`, `Read Message History`).
2. В Discord включите **Developer Mode** (User Settings → Advanced).
3. Правой кнопкой по нужному каналу → **Copy Channel ID**.
4. Используйте это значение в `DISCORD_CHANNEL_ID`.

### Telegram: права и ID чата
1. Добавьте бота в нужный чат/группу/канал.
2. Выдайте боту права на чтение и отправку сообщений (для канала — сделайте бота администратором).
3. Получите `chat id`:
   - отправьте сообщение в чат,
   - выполните запрос: `https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates`,
   - найдите поле `chat.id` в ответе.
4. Используйте это значение в `TELEGRAM_CHAT_ID`.

## 3) Настройка `.env`

Создайте файл `.env` в корне проекта:

```env
DISCORD_BOT_TOKEN=your_discord_bot_token
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
DISCORD_CHANNEL_ID=123456789012345678
TELEGRAM_CHAT_ID=-1001234567890

# Опционально
# BRIDGE_PAIRS=[{"discord_channel_id":123456789012345678,"telegram_chat_id":-1001234567890},{"discord_channel_id":223456789012345678,"telegram_chat_id":-1002234567890},{"discord_channel_id":323456789012345678,"telegram_chat_id":-1003234567890,"telegram_thread_id":42}]
# BRIDGE_PAIRS_STORE_PATH=data/bridge_pairs.json
# WHITELIST_USERS=["alice", "12345"]
# BLACKLIST_USERS=[]
# EXCLUDED_COMMANDS=["/start","!admin"]
# IGNORE_BOTS=true
# DEDUP_TTL_SECONDS=300
# DEDUP_REDIS_URL=redis://redis:6379/0
# HEARTBEAT_INTERVAL_SECONDS=60
# ADMIN_TOKEN=change_me
# ADMIN_HOST=0.0.0.0
# ADMIN_PORT=8080
```

> Можно использовать либо пару `DISCORD_CHANNEL_ID` + `TELEGRAM_CHAT_ID`, либо массив `BRIDGE_PAIRS` (JSON).
> При первом запуске пары из env инициализируют JSON-хранилище `BRIDGE_PAIRS_STORE_PATH`.

Примеры `BRIDGE_PAIRS`:

- Обычный канал/чат (без темы):

  ```jsonc
  [
    {
      "discord_channel_id": 123456789012345678, // ID канала Discord (целое число, без кавычек)
      "telegram_chat_id": -1001234567890 // ID чата/канала Telegram (обычно отрицательное число)
    }
  ]
  ```

- Форум/тема в Telegram (`telegram_thread_id`):

  ```jsonc
  [
    {
      "discord_channel_id": 123456789012345678, // ID канала Discord
      "telegram_chat_id": -1001234567890, // ID Telegram-чата, где есть тема
      "telegram_thread_id": 42 // ID темы (topic/thread) внутри этого Telegram-чата
    }
  ]
  ```

### Типичные ошибки JSON

- Используются **одинарные кавычки** вместо двойных:
  - неверно: `{'discord_channel_id': 123}`
  - верно: `{"discord_channel_id": 123}`
- Пропущена **запятая** между полями или объектами массива.
- ID переданы как **строки**, а не как целые числа:
  - неверно: `"discord_channel_id": "123456789012345678"`
  - верно: `"discord_channel_id": 123456789012345678`
- Лишняя запятая в конце объекта/массива:
  - неверно: `[{"discord_channel_id": 123,}]`

## 4) Локальный запуск

### Вариант A: напрямую через Python

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

### Вариант B: через Docker Compose

```bash
docker compose up --build
```

Админ-панель доступна по `http://localhost:8080/` (или вашему `ADMIN_PORT`).
Для API и страницы используется заголовок `Authorization: Bearer <ADMIN_TOKEN>`.

### API админки

- `GET /api/bridge-pairs`
- `POST /api/bridge-pairs`
- `PUT /api/bridge-pairs/{id}`
- `DELETE /api/bridge-pairs/{id}`

## Ограничения

1. **Лимиты API**
   - Discord и Telegram ограничивают частоту запросов.
   - При всплесках сообщений возможны задержки доставки из-за rate limits.

2. **Потери форматирования при пересылке**
   - Некоторые элементы форматирования (упоминания, вложения, спец-разметка, эмодзи/стикеры) могут отображаться иначе или теряться при переносе между платформами.

3. **Политика приватности и хранение сообщений**
   - Бот обрабатывает содержимое сообщений для пересылки.
   - Логи и внешние хранилища (например, Redis для дедупликации) могут временно содержать служебные данные.
   - Перед использованием убедитесь, что это соответствует политике приватности вашей команды и требованиям платформ.

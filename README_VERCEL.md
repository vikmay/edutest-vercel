
# FREE cloud deploy — Telegram EduTest Bot (Vercel + Supabase)

Ця збірка дозволяє **безкоштовно** запустити ваш тест‑бот у хмарі:
- **Vercel (Hobby)** — безкоштовні серверлес‑функції; приймаємо **webhook** від Telegram.  
- **Supabase (Free)** — безкоштовний Postgres для збереження результатів.

> Чому так? Без зовнішньої БД серверлес‑функції не мають постійного диска. Supabase Free дає 500 MB БД і достатньо для шкільного класу. Див. ліміти у їх офіційній сторінці.

## 1) Підготовка
1. Створіть репозиторій (GitHub) і завантажте сюди вміст цієї теки (`api/`, `edubot/`, `bank/`, `requirements.txt`, `vercel.json`).
2. **Supabase Free**: створіть проект → у Settings → **Database** скопіюйте `Connection string` (postgres://...).
3. **BotFather**: створіть бота і отримайте `TELEGRAM_TOKEN`.

## 2) Деплой на **Vercel** (безкоштовно)
1. Зареєструйтесь на https://vercel.com та імпортуйте ваш GitHub репозиторій.
2. У налаштуваннях проекту → **Environment Variables** додайте:
   - `TELEGRAM_TOKEN` — ваш токен
   - `ADMIN_IDS` — наприклад `12345,67890`
   - `DATABASE_URL` — рядок з Supabase (`postgres://…`)
3. Нічого більше не потрібно: Vercel авто‑виявить `api/index.py` і збере функцію.

> За потреби локально: `vercel dev` (але не обов’язково).

## 3) Установити **Webhook** (один раз)
Після деплою у вас буде домен на кшталт `https://<project>.vercel.app`. Виконайте в браузері або curl:

```
https://api.telegram.org/bot<ВАШ_ТОКЕН>/setWebhook?url=https://<project>.vercel.app/api/webhook
```

Відповідь Telegram має бути `{"ok":true, ...}`.

## 4) Як користуватися
- Учень з телефону відкриває вашого бота → **/start** → **/test**.
- Ви підтверджуєте доступи **/approve <tg_id>**, дивитесь **/leaderboard**, експорту поки немає (для простоти).  
- Банки питань — JSON у теці `bank/`. Щоб оновити — комітьте нові файли і **redeploy**.

## 5) Обмеження й поради
- `bank/` — **read-only** у Vercel функції. Тому **/import** (надіслати файл у чат) відключено в цій збірці.
- Таймаут Vercel функцій за замовчуванням до 10s (можна збільшити до 60s). Наш webhook відповідає миттєво.
- Стежте за безкоштовними квотами:
  - **Vercel Hobby** — безплатні функції, великі ліміти на інвокації.
  - **Supabase Free** — 500 MB БД; якщо проект «засне» через тиждень неактивності, просто відкрийте консоль Supabase, щоб «розбудити».

## 6) Структура
```
api/index.py          # FastAPI webhook для Telegram
edubot/logic.py       # обробники команд/квізу
edubot/db.py          # Postgres (pg8000)
bank/*.json           # банки питань (read-only)
requirements.txt
vercel.json
```

Гарних контрольних!


# -*- coding: utf-8 -*-
"""
Vercel entry (ASGI) for Telegram bot webhook.
- FastAPI endpoint at /api/webhook
- Reads env: TELEGRAM_TOKEN, ADMIN_IDS, DATABASE_URL
- Question bank in bank/*.json (read-only)
"""

import os, asyncio
from fastapi import FastAPI, Request, Response
from telegram import Update

from edubot.logic import build_application

app = FastAPI()
tg_app = None
_started = False
_lock = asyncio.Lock()

async def ensure_started():
    global tg_app, _started
    if _started:
        return
    async with _lock:
        if _started:
            return
        tg_app = build_application()
        await tg_app.initialize()
        await tg_app.start()
        _started = True

@app.get("/api/health")
async def health():
    return {"ok": True}

@app.post("/api/webhook")
async def webhook(request: Request):
    await ensure_started()
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    # Telegram requires a fast 200 OK
    return Response(status_code=200)

# (Optional) Endpoint to quickly check bot identity
@app.get("/api/botinfo")
async def botinfo():
    await ensure_started()
    me = await tg_app.bot.get_me()
    return {"id": me.id, "username": me.username}

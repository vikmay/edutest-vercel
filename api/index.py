# api/index.py
# -*- coding: utf-8 -*-
import os, asyncio, traceback, sys
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
        try:
            tg_app = build_application()
            await tg_app.initialize()
            await tg_app.start()
            _started = True
        except Exception:
            traceback.print_exc()  # виводимо стек у логи
            # не піднімаємо далі — нехай /api/botinfo покаже помилку

@app.get("/api/health")
async def health():
    return {"ok": True}

@app.get("/api/botinfo")
async def botinfo():
    try:
        await ensure_started()
        if not tg_app:
            return {"ok": False, "error": "tg_app not started"}
        me = await tg_app.bot.get_me()
        return {"id": me.id, "username": me.username}
    except Exception as e:
        # Повернемо текст помилки у відповідь (тимчасово для діагностики)
        traceback.print_exc()
        return Response(content=f"botinfo error: {e}", status_code=500, media_type="text/plain")

@app.post("/api/webhook")
async def webhook(request: Request):
    try:
        await ensure_started()
        if not tg_app:
            return Response(status_code=500, content="webhook: tg_app not started")
        data = await request.json()
        update = Update.de_json(data, tg_app.bot)
        await tg_app.process_update(update)
        return Response(status_code=200)
    except Exception as e:
        traceback.print_exc()
        # Telegram вимагає швидкий 200, але для діагностики повернемо 500 з текстом
        return Response(content=f"webhook error: {e}", status_code=500, media_type="text/plain")

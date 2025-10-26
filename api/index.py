# -*- coding: utf-8 -*-
import os, asyncio, traceback
from fastapi import FastAPI, Request, Response
from telegram import Update

from edubot.logic import build_application

app = FastAPI()
tg_app = None
_started = False
_lock = asyncio.Lock()
last_error = None  # <— збережемо останню помилку старту

async def ensure_started():
    global tg_app, _started, last_error
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
            last_error = None
        except Exception as e:
            # запишемо traceback у last_error і в stderr
            tb = traceback.format_exc()
            last_error = f"{e.__class__.__name__}: {e}\n{tb}"
            print(last_error)

@app.get("/api/health")
async def health():
    return {"ok": True}

@app.get("/api/botinfo")
async def botinfo():
    await ensure_started()
    if not _started or tg_app is None:
        # Повернемо зрозумілу діагностику, але без секретів
        return {
            "ok": False,
            "error": "tg_app not started",
            "hint": "check environment variables and database connectivity",
            "last_error": (last_error[:5000] if last_error else None)
        }
    me = await tg_app.bot.get_me()
    return {"id": me.id, "username": me.username}

@app.post("/api/webhook")
async def webhook(request: Request):
    await ensure_started()
    if not _started or tg_app is None:
        return Response(status_code=500, content="webhook: tg_app not started")
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return Response(status_code=200)

# -*- coding: utf-8 -*-
import os, asyncio, traceback
from fastapi import FastAPI, Request, Response
from telegram import Update

from edubot.logic import build_application

app = FastAPI()
tg_app = None
_started = False
_lock = asyncio.Lock()
last_error = None            # помилка старту
last_webhook_error = None    # помилка обробки webhook
last_update_json = None      # останній сирий апдейт (для діагностики)

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
        return {
            "ok": False,
            "error": "tg_app not started",
            "hint": "check env vars and database connectivity",
            "last_error": (last_error[:5000] if last_error else None),
        }
    me = await tg_app.bot.get_me()
    return {"id": me.id, "username": me.username}

@app.get("/api/diag")
async def diag():
    """Показати останню помилку вебхука та статус старту."""
    return {
        "started": _started,
        "last_start_error": (last_error[:2000] if last_error else None),
        "last_webhook_error": (last_webhook_error[:4000] if last_webhook_error else None),
        "last_update_sample": (last_update_json[:1000] if last_update_json else None),
    }

@app.post("/api/webhook")
async def webhook(request: Request):
    global last_webhook_error, last_update_json
    await ensure_started()
    if not _started or tg_app is None:
        last_webhook_error = "tg_app not started"
        return Response(status_code=500, content="webhook: tg_app not started")

    try:
        raw = await request.body()
        last_update_json = raw.decode("utf-8", errors="replace")
        data = await request.json()
        update = Update.de_json(data, tg_app.bot)
        await tg_app.process_update(update)
        return Response(status_code=200)
    except Exception as e:
        tb = traceback.format_exc()
        last_webhook_error = f"{e.__class__.__name__}: {e}\n{tb}"
        print(last_webhook_error)
        return Response(status_code=500, content="webhook error", media_type="text/plain")


# -*- coding: utf-8 -*-
"""
Telegram EduTest logic (webhook-friendly).
- Uses Postgres (Supabase/Neon) via pg8000 (see edubot.db).
- Reads question banks from bank/*.json (read-only).
- No /import (FS is read-only on Vercel Free).
"""

import os, json, random
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Set

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from telegram.constants import ParseMode
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

from . import db

BANK_DIR = Path(os.environ.get("QUIZ_BANK_DIR","bank"))
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS","").split(",") if x.strip().isdigit()}
TOKEN = os.environ.get("TELEGRAM_TOKEN")

ASK_NAME = 1

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# === Bank helpers ===
def load_all_questions() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for p in BANK_DIR.glob("*.json"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    items.extend(data)
        except Exception:
            continue
    return items

def list_topics() -> Dict[str,int]:
    topics: Dict[str,int] = {}
    for q in load_all_questions():
        t = q.get("topic") or "Без теми"
        topics[t] = topics.get(t, 0) + 1
    return dict(sorted(topics.items(), key=lambda x: x[0].lower()))

def select_questions(topic: str, n: int, shuffle_opts: bool=True) -> List[Dict[str, Any]]:
    pool = [q for q in load_all_questions() if (q.get("topic") or "") == topic]
    random.shuffle(pool)
    picked = pool[:min(n, len(pool))]
    if shuffle_opts:
        for q in picked:
            if "options" in q and isinstance(q["options"], list):
                random.shuffle(q["options"])
    return picked

def badge(ok: bool) -> str: return "🟩" if ok else "🟥"

def render_single(q: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    kb = [[InlineKeyboardButton(text=opt, callback_data=f"ans::{opt}")] for opt in q.get("options",[])]
    return q["question"], InlineKeyboardMarkup(kb)

def render_multi(q: Dict[str, Any], chosen: Optional[Set[str]] = None) -> Tuple[str, InlineKeyboardMarkup]:
    if chosen is None: chosen = set()
    rows = []
    for opt in q.get("options", []):
        label = ("✅ " if opt in chosen else "") + opt
        rows.append([InlineKeyboardButton(text=label, callback_data=f"multi::{opt}")])
    rows.append([InlineKeyboardButton(text="Підтвердити", callback_data="multi::confirm")])
    return q["question"], InlineKeyboardMarkup(rows)

def render_match_blocks(left: List[str], right: List[str]) -> str:
    letters = [chr(ord('A') + i) for i in range(len(left))]
    nums = [str(i+1) for i in range(len(right))]
    lb = "\n".join([f"{letters[i]}) {left[i]}" for i in range(len(left))])
    rb = "\n".join([f"{nums[i]}) {right[i]}" for i in range(len(right))])
    return f"{lb}\n\n{rb}\n\nНадішліть як: A-2,B-1,C-3"

def parse_args(text: str) -> Dict[str,str]:
    import re
    out = {}
    for part in re.split(r"\s+", text.strip()):
        if "=" in part:
            k,v = part.split("=",1)
            out[k.strip().lower()] = v.strip()
    return out

# === Handlers ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.ensure_user(user.id, user.full_name or "")
    if not u["full_name"]:
        await update.message.reply_text("Привіт! Вкажіть, будь ласка, *ім'я та прізвище* одним повідомленням (напр.: `Олена Петренко`).", parse_mode=ParseMode.MARKDOWN)
        return ASK_NAME
    if u["approved"] == 1:
        await update.message.reply_text(
            "Вас вітає EduTest бот (хмара) 👋\n"
            "Команди:\n"
            "• /topics — теми\n"
            "• /test — пройти тест (або `/test topic=Планіметрія n=10 time=8`)\n"
            "• /score — мій прогрес\n"
            "• /leaderboard — табло (або `/leaderboard topic=Планіметрія`)\n"
            "• /help — довідка"
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("Дякуємо! Зачекайте підтвердження доступу від адміністратора.")
        return ConversationHandler.END

async def save_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if len(name.split()) < 2:
        await update.message.reply_text("Будь ласка, надішліть *ім'я та прізвище* (два слова).", parse_mode=ParseMode.MARKDOWN)
        return ASK_NAME
    db.set_user_name(update.effective_user.id, name)
    await update.message.reply_text("Дякуємо! Очікуйте підтвердження доступу від адміністратора.")
    return ConversationHandler.END

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Довідка:\n"
        "/topics — доступні теми\n"
        "/test — почати тест\n"
        "/score — ваші бали\n"
        "/leaderboard [topic=...] — табло\n"
        "Адмін: /pending, /approve <tg_id>, /ban <tg_id>\n"
        "Примітка: у хмарній версії імпорт файлів у чаті вимкнено. Додавайте теми як JSON у теку bank/ та деплойте."
    )

async def topics_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = list_topics()
    if not t:
        await update.message.reply_text("Теми не знайдено. Додайте банк питань у теку bank/.")
        return
    lines = [f"• {k} — {v} питань" for k,v in t.items()]
    await update.message.reply_text("Доступні теми:\n" + "\n".join(lines))

async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # check approved
    if db.ensure_user(update.effective_user.id).get("approved") != 1:
        await update.message.reply_text("Доступ ще не підтверджено адміністратором.")
        return

    text = update.message.text or ""
    args = parse_args(text.replace("/test","",1))
    topics = list_topics()
    if not topics:
        await update.message.reply_text("Немає доступних тем. Додайте питання у теку bank/.")
        return

    topic = args.get("topic")
    if not topic:
        if len(topics) == 1:
            topic = next(iter(topics.keys()))
        else:
            buttons = [[InlineKeyboardButton(text=k, callback_data=f"choose_topic::{k}")] for k in topics.keys()]
            await update.message.reply_text("Оберіть тему:", reply_markup=InlineKeyboardMarkup(buttons))
            return
    if topic not in topics:
        await update.message.reply_text(f"Теми «{topic}» не знайдено. Спробуйте /topics")
        return

    try:
        n = int(args.get("n","10"))
    except: n = 10
    try:
        minutes = int(args.get("time","0"))
    except: minutes = 0

    await start_quiz(update, context, topic=topic, n=n, minutes=minutes)

async def choose_topic_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    topic = query.data.split("::",1)[1]
    await start_quiz(update, context, topic=topic, n=10, minutes=0)

def start_new_session(tg_id: int, topic: str, total: int, timer_minutes: int) -> int:
    return db.start_session(tg_id, topic, total, timer_minutes)

async def start_quiz(update_or_query, context: ContextTypes.DEFAULT_TYPE, topic: str, n: int, minutes: int):
    is_query = hasattr(update_or_query, "callback_query") and update_or_query.callback_query
    send = (update_or_query.callback_query.message.reply_text if is_query else update_or_query.message.reply_text)
    user = update_or_query.effective_user

    questions = select_questions(topic, n, shuffle_opts=True)
    if not questions:
        await send("У вибраній темі немає питань.")
        return

    session_id = start_new_session(user.id, topic, len(questions), minutes)
    deadline = None
    if minutes and minutes > 0:
        deadline = datetime.utcnow() + timedelta(minutes=minutes)

    context.user_data["quiz"] = {
        "topic": topic,
        "questions": questions,
        "current": 0,
        "score": 0,
        "session_id": session_id,
        "details": [],
        "deadline": deadline
    }
    await send(f"Починаємо тест з теми *{topic}* ({len(questions)} питань){' — час ' + str(minutes) + ' хв.' if minutes else ''}. Успіхів!",
               parse_mode=ParseMode.MARKDOWN)
    await send_next_question(update_or_query, context)

async def send_next_question(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    st = context.user_data.get("quiz")
    if not st: return
    send = (update_or_query.callback_query.message.reply_text if hasattr(update_or_query, "callback_query") and update_or_query.callback_query
            else update_or_query.message.reply_text)

    idx = st["current"]
    if idx >= len(st["questions"]):
        await finish_quiz(update_or_query, context)
        return

    time_note = ""
    if st.get("deadline"):
        left = (st["deadline"] - datetime.utcnow()).total_seconds()
        if left <= 0:
            await finish_quiz(update_or_query, context)
            return
        mins = int(left // 60); secs = int(left % 60)
        time_note = f"\n⏳ Залишилось: {mins:02d}:{secs:02d}"

    q = st["questions"][idx]
    qtype = q.get("type","single")
    header = f"*Питання {idx+1}/{len(st['questions'])}*{time_note}\n"

    if qtype == "single":
        text, kb = render_single(q)
        await send(header + text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        context.user_data["await"] = ("single", q)
    elif qtype == "multi":
        text, kb = render_multi(q, chosen=set())
        await send(header + text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        context.user_data["await"] = ("multi", q, set())
    elif qtype == "match":
        right = q.get("match_right", [])[:]
        random.shuffle(right)
        context.user_data["await"] = ("match", q, right)
        blocks = render_match_blocks(q.get("match_left", []), right)
        await send(header + q.get("question","") + "\n\n" + blocks, parse_mode=ParseMode.MARKDOWN)
    else:
        await send("Невідомий тип питання, пропускаємо.")
        st["current"] += 1
        await send_next_question(update_or_query, context)

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    aw = context.user_data.get("await")
    st = context.user_data.get("quiz")
    if not aw or not st: return
    kind = aw[0]

    if kind == "single":
        q = aw[1]
        chosen = query.data.split("::",1)[1]
        correct = q.get("answer","")
        ok = (chosen == correct)
        if ok: st["score"] += 1
        st["details"].append({"id": q.get("id"), "type":"single","chosen":chosen,"correct":correct,"ok":ok})
        await query.message.reply_text(f"{badge(ok)} {'Правильно!' if ok else 'Неправильно.'}\nПравильна: *{correct}*\n\n{q.get('explanation','')}", parse_mode=ParseMode.MARKDOWN)
        st["current"] += 1
        await send_next_question(update, context)

    elif kind == "multi":
        q, chosen = aw[1], aw[2]
        payload = query.data.split("::",1)[1]
        if payload == "confirm":
            correct_set = set(q.get("answers",[]))
            ok = (chosen == correct_set)
            if ok: st["score"] += 1
            st["details"].append({"id": q.get("id"), "type":"multi","chosen":sorted(list(chosen)),"correct":sorted(list(correct_set)),"ok":ok})
            await query.message.reply_text(f"{badge(ok)} {'Правильно!' if ok else 'Неправильно.'}\nПравильні: *{', '.join(correct_set)}*\n\n{q.get('explanation','')}", parse_mode=ParseMode.MARKDOWN)
            st["current"] += 1
            await send_next_question(update, context)
        else:
            opt = payload
            if opt in chosen: chosen.remove(opt)
            else: chosen.add(opt)
            text, kb = render_multi(q, chosen)
            await query.message.edit_reply_markup(reply_markup=kb)
            context.user_data["await"] = ("multi", q, chosen)

async def on_text_for_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    aw = context.user_data.get("await"); st = context.user_data.get("quiz")
    if not aw or aw[0] != "match" or not st: return
    q = aw[1]
    shown_right = aw[2]
    letters = [chr(ord('A') + i) for i in range(len(q.get("match_left",[])))]
    nums = [str(i+1) for i in range(len(shown_right))]
    text = (update.message.text or "").upper().replace(" ", "")
    try:
        parsed = []
        for part in [x for x in text.split(",") if x]:
            a,b = part.split("-",1)
            if a not in letters or b not in nums: raise ValueError("Невірні позначення.")
            parsed.append((letters.index(a), nums.index(b)))
        shown_to_orig = {i: q.get("match_right", []).index(shown_right[i]) for i in range(len(shown_right))}
        correct_pairs = set(tuple(x) for x in q.get("pairs", []))
        user_pairs = set((li, shown_to_orig[ri]) for (li, ri) in parsed)
        ok = (user_pairs == correct_pairs)
        if ok: st["score"] += 1
        st["details"].append({"id": q.get("id"), "type":"match","chosen_pairs":sorted(list(user_pairs)),"correct_pairs":sorted(list(correct_pairs)),"ok":ok})
        await update.message.reply_text(f"{badge(ok)} {'Правильно!' if ok else 'Неправильно.'}\n\n{q.get('explanation','')}")
        st["current"] += 1
        await send_next_question(update, context)
    except Exception:
        await update.message.reply_text("Не вдалося розібрати відповідь. Формат: A-1,B-3,C-2 ...")

async def finish_quiz(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    st = context.user_data.get("quiz")
    if not st: return
    score = st["score"]; total = len(st["questions"])
    db.finish_session(st["session_id"], score, st["details"])
    db.add_points(update_or_query.effective_user.id, score, topic=st["topic"])
    context.user_data["quiz"] = None
    send = (update_or_query.callback_query.message.reply_text if hasattr(update_or_query, "callback_query") and update_or_query.callback_query
            else update_or_query.message.reply_text)
    await send(f"Тест завершено! Результат: *{score}/{total}*.", parse_mode=ParseMode.MARKDOWN)

async def score_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pts = db.get_user_points(update.effective_user.id)
    await update.message.reply_text(f"Ваші бали: *{pts}*", parse_mode=ParseMode.MARKDOWN)

async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "")
    topic = None
    if "topic=" in text:
        topic = text.split("topic=",1)[1].strip()
    rows = db.top_scores(limit=15, topic=topic)
    if not rows:
        await update.message.reply_text("Ще нема результатів.")
        return
    title = "🏆 Табло лідерів" + (f" — {topic}" if topic else "")
    lines = [f"{i+1}. {name or 'невідомо'} — {pts}" for i,(name,pts) in enumerate(rows)]
    await update.message.reply_text(title + ":\n" + "\n".join(lines))

async def pending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    rows = db.list_pending()
    if not rows:
        await update.message.reply_text("Немає заявок на підтвердження.")
        return
    txt = "Заявки:\n" + "\n".join([f"• {r[1] or '(без імені)'} — `{r[0]}`" for r in rows])
    await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)

async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Використання: /approve <tg_id>")
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("tg_id має бути числом.")
        return
    db.set_approved(uid, 1)
    await update.message.reply_text(f"Користувача `{uid}` підтверджено ✅", parse_mode=ParseMode.MARKDOWN)

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Використання: /ban <tg_id>")
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("tg_id має бути числом.")
        return
    db.set_approved(uid, 0)
    await update.message.reply_text(f"Користувача `{uid}` вимкнено ❌", parse_mode=ParseMode.MARKDOWN)

# === Factory ===
def build_application() -> Application:
    if not TOKEN:
        raise RuntimeError("Не задано TELEGRAM_TOKEN")
    db.ensure_schema()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_name)]},
        fallbacks=[CommandHandler("help", help_cmd)],
    ))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("topics", topics_cmd))
    app.add_handler(CommandHandler("test", test_cmd))
    app.add_handler(CallbackQueryHandler(choose_topic_cb, pattern=r"^choose_topic::"))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^(ans|multi)::"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_for_match))
    app.add_handler(CommandHandler("score", score_cmd))
    app.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    # admin
    app.add_handler(CommandHandler("pending", pending_cmd))
    app.add_handler(CommandHandler("approve", approve_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    return app

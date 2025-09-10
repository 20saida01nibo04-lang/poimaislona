import asyncio, os, json, re, random
from pathlib import Path
from typing import Dict, Any, Optional

import yaml
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from dotenv import load_dotenv

# ---- ENV ----
BASE = Path(__file__).parent
load_dotenv(BASE / ".env")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise SystemExit("В .env нет BOT_TOKEN. Вставь токен из @BotFather и запусти снова.")

# ---- Files / Storage ----
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
STORE = DATA / "progress.json"


def db_load() -> Dict[str, Any]:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def db_save(d: Dict[str, Any]) -> None:
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STORE)


def get_state(uid: int) -> Dict[str, Any]:
    db = db_load()
    return db.get(str(uid), {"current": QCFG["start_point_id"], "history": [], "prize": None})


def set_state(uid: int, st: Dict[str, Any]) -> None:
    db = db_load()
    db[str(uid)] = st
    db_save(db)

# ---- Quest config ----
QCFG = yaml.safe_load((BASE / "quest.yaml").read_text(encoding="utf-8"))["quest"]
POINTS = {p["id"]: p for p in QCFG["points"]}


def next_point_id(cur: str) -> Optional[str]:
    ids = [p["id"] for p in QCFG["points"]]
    if cur not in ids:
        return None
    i = ids.index(cur)
    return ids[i+1] if i + 1 < len(ids) else None


def validate_text(ans: str, rule: Dict[str, Any]) -> bool:
    if not ans:
        return False
    ans = ans.strip()
    if "any_of_regex" in rule:
        return any(re.search(pat, ans, flags=re.IGNORECASE) for pat in rule["any_of_regex"])
    if "min_len" in rule:
        return len(ans) >= int(rule["min_len"])
    return True


def make_code(pattern: str) -> str:
    m = re.search(r"\{rand:(\d+)\}", pattern)
    if m:
        n = int(m.group(1))
        rnd = "".join(random.choice("0123456789") for _ in range(n))
        return pattern.replace(m.group(0), rnd)
    return pattern


def fmt_point(p: Dict[str, Any]) -> str:
    return f"📍 <b>{p.get('title','')}</b>\n\n{p.get('instruction','')}"


# ---- Bot / FSM ----
class Flow(StatesGroup):
    Waiting = State()


bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    st = {"current": QCFG["start_point_id"], "history": [], "prize": None}
    set_state(m.from_user.id, st)
    await state.set_state(Flow.Waiting)
    await m.answer(
        f"Привет! Это <b>{QCFG['title']}</b>.\n"
        f"Выполняй задания по очереди. /help — справка.\n\n"
        + fmt_point(POINTS[st['current']])
    )


@dp.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer("Как играть:\n— Бот даёт точку и задание.\n— Отправь текст или фото по условию.\n— Получишь подсказку и следующую точку.\n\nКоманды: /progress, /reset")


@dp.message(Command("progress"))
async def cmd_progress(m: Message):
    st = get_state(m.from_user.id)
    cur = st["current"]
    done = len(st.get("history", []))
    title = POINTS.get(cur, {}).get("title", "?")
    await m.answer(f"Завершено точек: {done}\nТекущая: <b>{title}</b>")


@dp.message(Command("reset"))
async def cmd_reset(m: Message, state: FSMContext):
    st = {"current": QCFG["start_point_id"], "history": [], "prize": None}
    set_state(m.from_user.id, st)
    await state.set_state(Flow.Waiting)
    await m.answer("Квест начат заново ✅\n\n" + fmt_point(POINTS[st["current"]]))


@dp.message(Flow.Waiting, F.text | F.photo)
async def flow(m: Message, state: FSMContext):
    st = get_state(m.from_user.id)
    cur_id = st["current"]
    p = POINTS.get(cur_id)
    if not p:
        await m.answer("Не нашёл текущую точку. Напиши /reset.")
        return

    ptype = p["type"]
    ok = False

    if ptype == "text":
        if not m.text:
            await m.answer("Здесь нужен <b>текстовый</b> ответ. Напиши его сообщением.")
            return
        ok = validate_text(m.text, p.get("text_accept", {}))

    elif ptype == "photo":
        if not m.photo:
            await m.answer("Здесь нужно <b>фото</b>. Пришли фото в чат.")
            return
        ok = True

    elif ptype == "text_or_photo":
        if m.text:
            ok = validate_text(m.text, p.get("text_accept", {}))
        elif m.photo:
            ok = True
        else:
            await m.answer("Пришли текст или фото.")
            return

    elif ptype == "finish":
        if st.get("prize"):
            await m.answer(f"Твой призовой код: <b>{st['prize']}</b>\nПокажи организатору.")
            return
        prize = p.get("prize", {})
        code = make_code(prize.get("pattern", "SLON-{rand:6}"))
        st["prize"] = code
        set_state(m.from_user.id, st)
        await m.answer(f"Финиш! 🎉\nТвой призовой код: <b>{code}</b>\n{prize.get('instructions','Покажи код организатору.')}")
        return

    if not ok:
        await m.answer("Почти! Проверь подсказку в задании и попробуй ещё раз.")
        return

    # success on point
    if cur_id not in st["history"]:
        st["history"].append(cur_id)
    nxt = next_point_id(cur_id)
    if not nxt:
        st["current"] = QCFG["finish_point_id"]
        set_state(m.from_user.id, st)
        await m.answer("Это последняя точка. Напиши любое сообщение, чтобы получить призовой код.")
        return

    st["current"] = nxt
    set_state(m.from_user.id, st)

    hint = p.get("hint_after_ok")
    if hint:
        await m.answer("Засчитано ✔️\nПодсказка: " + hint)

    await m.answer(fmt_point(POINTS[nxt]))


async def main():
    print("✅ Bot is running. Открой Telegram и напиши своему боту /start")
    await dp.start_polling(bot)


# ---- Фейковый веб-сервер для Render ----
from aiohttp import web

async def handle(request):
    return web.Response(text="Bot is running!")

app = web.Application()
app.router.add_get("/", handle)

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    web.run_app(app, port=port)

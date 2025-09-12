from aiohttp import web
from aiogram import Bot, Dispatcher
import os

# ---- Настройки ----
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN не найден. Добавь его в .env")

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"https://poimaislona.onrender.com{WEBHOOK_PATH}"  # Замени на свой URL Render

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# ---- Обработчики ----
@dp.message()
async def echo_handler(message):
    await message.answer(f"Привет! Ты написал: {message.text}")

# ---- Настройка Webhook ----
async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)

async def on_shutdown(app):
    await bot.delete_webhook()

async def health_check(request):
    return web.Response(text="Bot is running!")

# ---- Aiohttp сервер ----
app = web.Application()
app.router.add_post(WEBHOOK_PATH, dp.webhook_handler)
app.router.add_get("/", health_check)

app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

if __name__ == "__main__":
    web.run_app(app, port=int(os.getenv("PORT", 10000)))
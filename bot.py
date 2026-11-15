import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

def init_db():
    conn = sqlite3.connect("appeals.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS appeals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        name TEXT,
        contact TEXT,
        category TEXT,
        description TEXT,
        photo_id TEXT,
        status TEXT DEFAULT 'Нове',
        created_at TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

class Appeal(StatesGroup):
    category = State()
    name = State()
    contact = State()
    description = State()
    photo = State()

class AdminReply(StatesGroup):
    waiting = State()

def category_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Технічна проблема", callback_data="cat_tech")],
        [InlineKeyboardButton(text="Якість товару / послуги", callback_data="cat_quality")],
        [InlineKeyboardButton(text="Інше", callback_data="cat_other")]
    ])

def status_keyboard(appeal_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="В роботі", callback_data=f"status_{appeal_id}_work"),
            InlineKeyboardButton(text="Вирішено", callback_data=f"status_{appeal_id}_done")
        ],
        [InlineKeyboardButton(text="Відповісти клієнту", callback_data=f"reply_{appeal_id}")]
    ])

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Вітаємо в службі підтримки!\n\nОберіть категорію звернення:",
        reply_markup=category_keyboard()
    )
    await state.set_state(Appeal.category)

@dp.callback_query(Appeal.category, F.data.startswith("cat_"))
async def process_category(callback: CallbackQuery, state: FSMContext):
    categories = {
        "cat_tech": "Технічна проблема",
        "cat_quality": "Якість товару / послуги",
        "cat_other": "Інше"
    }
    category = categories.get(callback.data, "Інше")
    await state.update_data(category=category)
    await callback.message.edit_text(f"Категорія: {category}\n\nВведіть ваше ім'я:")
    await state.set_state(Appeal.name)
    await callback.answer()

@dp.message(Appeal.name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введіть ваш контакт (телефон або @username):")
    await state.set_state(Appeal.contact)

@dp.message(Appeal.contact)
async def process_contact(message: Message, state: FSMContext):
    await state.update_data(contact=message.text)
    await message.answer("Опишіть вашу ситуацію детально:")
    await state.set_state(Appeal.description)

@dp.message(Appeal.description)
async def process_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустити фото", callback_data="skip_photo")]
    ])
    await message.answer("Можете прикріпити фото або натисніть кнопку нижче:", reply_markup=kb)
    await state.set_state(Appeal.photo)

@dp.callback_query(Appeal.photo, F.data == "skip_photo")
async def skip_photo(callback: CallbackQuery, state: FSMContext):
    await finish_appeal(callback.message, state, callback.from_user, photo_id=None)
    await callback.answer()

@dp.message(Appeal.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await finish_appeal(message, state, message.from_user, photo_id=photo_id)

async def finish_appeal(message: Message, state: FSMContext, user, photo_id: str = None):
    data = await state.get_data()
    conn = sqlite3.connect("appeals.db")
    c = conn.cursor()
    c.execute('''INSERT INTO appeals 
        (user_id, username, name, contact, category, description, photo_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (user.id, user.username or "немає", data.get("name"), data.get("contact"),
         data.get("category"), data.get("description"), photo_id,
         datetime.now().strftime("%d.%m.%Y %H:%M"))
    )
    appeal_id = c.lastrowid
    conn.commit()
    conn.close()

    text = (
        f"🆕 Звернення #{appeal_id}\n\n"
        f"📂 Категорія: {data.get('category')}\n"
        f"👤 Ім'я: {data.get('name')}\n"
        f"📞 Контакт: {data.get('contact')}\n"
        f"🆔 @{user.username or 'немає'} (ID: {user.id})\n"
        f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"📝 Опис:\n{data.get('description')}"
    )

    try:
        if photo_id:
            await bot.send_photo(ADMIN_ID, photo_id, caption=text, reply_markup=status_keyboard(appeal_id))
        else:
            await bot.send_message(ADMIN_ID, text, reply_markup=status_keyboard(appeal_id))
    except Exception as e:
        logging.error(f"Помилка надсилання адміну: {e}")

    await message.answer(f"✅ Звернення #{appeal_id} прийнято!\nМи зв'яжемося з вами найближчим часом.")
    await state.clear()

@dp.callback_query(F.data.startswith("status_"))
async def change_status(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Немає доступу", show_alert=True)
        return
    parts = callback.data.split("_")
    appeal_id = int(parts[1])
    new_status = "В роботі" if parts[2] == "work" else "Вирішено"

    conn = sqlite3.connect("appeals.db")
    c = conn.cursor()
    c.execute("UPDATE appeals SET status = ? WHERE id = ?", (new_status, appeal_id))
    conn.commit()
    conn.close()

    await callback.answer(f"Статус: {new_status}")

@dp.callback_query(F.data.startswith("reply_"))
async def start_reply(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Немає доступу", show_alert=True)
        return
    appeal_id = int(callback.data.split("_")[1])
    await state.update_data(reply_appeal_id=appeal_id)
    await callback.message.answer(f"Напишіть відповідь для звернення #{appeal_id}:")
    await state.set_state(AdminReply.waiting)
    await callback.answer()

@dp.message(AdminReply.waiting, F.from_user.id == ADMIN_ID)
async def admin_reply(message: Message, state: FSMContext):
    data = await state.get_data()
    appeal_id = data.get("reply_appeal_id")
    if not appeal_id:
        await state.clear()
        return

    conn = sqlite3.connect("appeals.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM appeals WHERE id = ?", (appeal_id,))
    row = c.fetchone()
    conn.close()

    if row:
        try:
            await bot.send_message(row[0], f"📩 Відповідь по зверненню #{appeal_id}:\n\n{message.text}")
            await message.answer("Відповідь надіслано клієнту.")
        except Exception as e:
            await message.answer(f"Помилка: {e}")
    else:
        await message.answer("Звернення не знайдено.")
    await state.clear()

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

"""
Telegram бот для 911 Суші
Функції:
- Меню з уточненням кількості осіб і рекомендацією сетів
- Розрахунок порцій
- Наголос на додаткові прибори 20.99 грн
- Оформлення замовлення / оплата
- Звернення клієнтів
"""

import asyncio
import logging
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ==================== НАЛАШТУВАННЯ ====================
BOT_TOKEN = "9222820094:AAEIlMrKLssFHt0laTcFBU5jM7WO_bXYlVI"  # Замініть на свій токен
ADMIN_ID = 1205290558  # Твій особистий Telegram ID
GROUP_CHAT_ID = -1003984284456  # ID групи «Суші 911»
THREAD_ORDERS = 6      # Гілка «Замовлення»
THREAD_PAYMENT = 8     # Гілка «Оплата»
THREAD_INQUIRY = 7     # Гілка «Звернення»
CARD_NUMBER = "4441 1144 5269 1122"  # Номер картки для оплати

# ==================== БАЗА КЛІЄНТІВ ====================
DB_PATH = "clients.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            username TEXT,
            phone TEXT,
            address TEXT,
            first_order TEXT,
            last_order TEXT,
            orders_count INTEGER DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            sets TEXT,
            total REAL,
            people INTEGER,
            created_at TEXT,
            FOREIGN KEY (client_id) REFERENCES clients(id)
        )
    ''')
    conn.commit()
    conn.close()

def save_client_and_order(user_id: int, username: str, phone: str, address: str, sets: list, total: float, people: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Upsert client
    c.execute('''
        INSERT INTO clients (user_id, username, phone, address, first_order, last_order, orders_count)
        VALUES (?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            phone = excluded.phone,
            address = excluded.address,
            last_order = excluded.last_order,
            orders_count = orders_count + 1
    ''', (user_id, username or "", phone, address, now, now))
    
    client_id = c.execute("SELECT id FROM clients WHERE user_id = ?", (user_id,)).fetchone()[0]
    
    c.execute('''
        INSERT INTO orders (client_id, sets, total, people, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (client_id, ", ".join(sets), total, people, now))
    
    conn.commit()
    conn.close()

init_db()

# Меню сетів з сайту 911sushi.com (Луцьк, актуальні на момент створення)
# Формат: назва: {people: (мін, макс), weight: грами, price: грн, description: str}
SETS = {
    "Філа": {"people": (4, 5), "weight": 1500, "price": 1119, "desc": "Класичний сет Філадельфія"},
    "Сет запечених ролів": {"people": (2, 3), "weight": 850, "price": 679, "desc": "Запечені роли"},
    "XXL 50/50": {"people": (2, 3), "weight": 1000, "price": 845, "desc": "Великий сет 50/50"},
    "Infinity": {"people": (2, 3), "weight": 1100, "price": 825, "desc": "Для тих, хто хоче спробувати все"},
    "Апгрейд": {"people": (2, 3), "weight": 1100, "price": 865, "desc": "Покращений сет"},
    "Філа 50/50": {"people": (1, 2), "weight": 715, "price": 571, "desc": "Філадельфія 50/50"},
    "Філадельфія МАКСІ": {"people": (3, 4), "weight": 1850, "price": 1599, "desc": "6 ролів, максимум риби"},
    "Філадельфія МАКСІ 50/50": {"people": (2, 3), "weight": 925, "price": 849, "desc": "МАКСІ у форматі 50/50"},
    "Fila Baby": {"people": (3, 4), "weight": 1375, "price": 879, "desc": "Для компанії"},
    "Fila Baby mini": {"people": (1, 2), "weight": 685, "price": 449, "desc": "Міні версія"},
    "Філа NEW": {"people": (3, 4), "weight": 1440, "price": 1159, "desc": "Нова Філадельфія"},
    "Філа NEW 50/50": {"people": (1, 2), "weight": 715, "price": 591, "desc": "Нова Філа 50/50"},
    "Сет запечених NEW": {"people": (2, 3), "weight": 850, "price": 649, "desc": "Нові запечені"},
    "XXL": {"people": (4, 5), "weight": 2000, "price": 1665, "desc": "Дуже великий сет"},
    "Канада": {"people": (3, 4), "weight": 1150, "price": 1049, "desc": "Канадський сет"},
    "Канада 50/50": {"people": (2, 3), "weight": 700, "price": 649, "desc": "Канада 50/50"},
    "Лабубу": {"people": (3, 4), "weight": 1140, "price": 849, "desc": "Авторський сет"},
    "Імба": {"people": (2, 3), "weight": 720, "price": 619, "desc": "Імба сет"},
    "ЗСУ": {"people": (3, 4), "weight": 1120, "price": 749, "desc": "Сет на підтримку ЗСУ"},
    "Тренд 911": {"people": (3, 4), "weight": 1150, "price": 819, "desc": "Трендовий сет"},
    "Тест-драйв": {"people": (3, 4), "weight": 1370, "price": 959, "desc": "Для тестування смаків"},
    "Тріо NEW": {"people": (2, 3), "weight": 850, "price": 699, "desc": "Тріо нових ролів"},
    "Мейнстрім": {"people": (2, 3), "weight": 1100, "price": 819, "desc": "Мейнстрім"},
    "Кайфовий": {"people": (2, 3), "weight": 1100, "price": 939, "desc": "Кайфовий сет"},
    "Філа з авокадо": {"people": (3, 4), "weight": 1430, "price": 1199, "desc": "Філадельфія з авокадо"},
    "Філа з авокадо 50/50": {"people": (1, 2), "weight": 715, "price": 619, "desc": "З авокадо 50/50"},
    "Only 911": {"people": (3, 4), "weight": 1380, "price": 989, "desc": "Ексклюзив 911"},
    "Spectrum NEW": {"people": (4, 5), "weight": 1500, "price": 1149, "desc": "Спектр смаків"},
    "Luxury": {"people": (7, 9), "weight": 2850, "price": 2369, "desc": "Люкс сет для великої компанії"},
    "Лагуна": {"people": (7, 10), "weight": 2850, "price": 2145, "desc": "Лагуна для компанії"},
    "Дракони": {"people": (3, 4), "weight": 1430, "price": 1299, "desc": "Сети з драконами"},
    "2025": {"people": (5, 7), "weight": 2000, "price": 1649, "desc": "Сет 2025"},
    "Garfield": {"people": (3, 4), "weight": 1140, "price": 899, "desc": "Garfield сет"},
    "Макі": {"people": (2, 3), "weight": 750, "price": 409, "desc": "Макі роли"},
    "911 лав'ю": {"people": (3, 4), "weight": 1450, "price": 1149, "desc": "Love сет"},
    "Футомаки": {"people": (3, 4), "weight": 1080, "price": 715, "desc": "Футомаки"},
    "Фіш-н-чіз": {"people": (2, 3), "weight": 950, "price": 649, "desc": "Риба і сир"},
    "Каліфорнії": {"people": (3, 4), "weight": 1200, "price": 841, "desc": "Каліфорнія сети"},
    "Каліфорнії 50/50": {"people": (1, 2), "weight": 600, "price": 439, "desc": "Каліфорнія 50/50"},
    "Гункани": {"people": (1, 1), "weight": 250, "price": 249, "desc": "Гункани на одну особу"},
    "Дитячий сет": {"people": (2, 3), "weight": 800, "price": 549, "desc": "Для дітей"},
}

EXTRA_UTENSILS_PRICE = 20.99

# ==================== FSM ====================
class OrderStates(StatesGroup):
    waiting_people = State()
    selecting_set = State()
    cart = State()
    address = State()
    phone = State()
    confirm = State()
    inquiry = State()
    waiting_payment_photo = State()

# ==================== КЛАВІАТУРИ ====================
def main_menu():
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🍣 Меню")],
            [KeyboardButton(text="🛒 Оформити замовлення"), KeyboardButton(text="💳 Оплата")],
            [KeyboardButton(text="💬 Звернення"), KeyboardButton(text="📞 Контакти")]
        ],
        resize_keyboard=True
    )
    return kb

def people_kb():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 особа", callback_data="people_1"),
         InlineKeyboardButton(text="2 особи", callback_data="people_2")],
        [InlineKeyboardButton(text="3 особи", callback_data="people_3"),
         InlineKeyboardButton(text="4 особи", callback_data="people_4")],
        [InlineKeyboardButton(text="5 осіб", callback_data="people_5"),
         InlineKeyboardButton(text="6+ осіб", callback_data="people_6")],
        [InlineKeyboardButton(text="Ввести вручну", callback_data="people_custom")]
    ])
    return kb

# ==================== БОТ ====================
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

user_carts = {}  # user_id: list of items
user_people = {}  # user_id: int

async def notify_admin_and_group(text: str = None, photo=None, caption: str = None, thread_id: int = None):
    """Відправляє повідомлення в особисті і в групу (у вказану гілку)."""
    # Особисті
    try:
        if photo:
            await bot.send_photo(ADMIN_ID, photo=photo, caption=caption or text)
        elif text:
            await bot.send_message(ADMIN_ID, text)
    except Exception as e:
        logging.warning(f"Не вдалося відправити адміну: {e}")
    
    # Група (у гілку)
    if GROUP_CHAT_ID:
        try:
            kwargs = {"chat_id": GROUP_CHAT_ID}
            if thread_id:
                kwargs["message_thread_id"] = thread_id
            if photo:
                kwargs["photo"] = photo
                kwargs["caption"] = caption or text
                await bot.send_photo(**kwargs)
            elif text:
                kwargs["text"] = text
                await bot.send_message(**kwargs)
        except Exception as e:
            logging.warning(f"Не вдалося відправити в групу: {e}")

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🍣 Привіт! Вітаємо в боті 911 Суші!\n\n"
        "Тут ви можете:\n"
        "• Переглянути меню та підібрати сет під кількість осіб\n"
        "• Оформити замовлення\n"
        "• Звернутися до підтримки\n\n"
        "Оберіть дію:",
        reply_markup=main_menu()
    )

@dp.message(F.text == "🍣 Меню")
async def menu_start(message: types.Message, state: FSMContext):
    await state.set_state(OrderStates.waiting_people)
    await message.answer(
        "На скільки осіб плануєте замовлення?\n\n"
        "Бот підбере оптимальні сети з сайту 911sushi.com та розрахує порції.",
        reply_markup=people_kb()
    )

@dp.callback_query(F.data.startswith("people_"))
async def process_people(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data
    if data == "people_custom":
        await callback.message.answer("Введіть кількість осіб числом (наприклад, 7):")
        await state.set_state(OrderStates.waiting_people)
        await callback.answer()
        return
    
    people = int(data.split("_")[1])
    if people == 6:
        people = 6  # для 6+
    user_people[callback.from_user.id] = people
    await show_recommended_sets(callback.message, people)
    await callback.answer()

@dp.message(OrderStates.waiting_people)
async def process_custom_people(message: types.Message, state: FSMContext):
    try:
        people = int(message.text.strip())
        if people < 1 or people > 30:
            await message.answer("Будь ласка, введіть число від 1 до 30.")
            return
        user_people[message.from_user.id] = people
        await show_recommended_sets(message, people)
        await state.clear()
    except ValueError:
        await message.answer("Будь ласка, введіть коректне число.")

async def show_recommended_sets(message: types.Message, people: int):
    # Знаходимо сети, які підходять або майже підходять
    single_suitable = []
    large_sets = []  # сети на 4+ осіб
    
    for name, info in SETS.items():
        min_p, max_p = info["people"]
        if min_p <= people <= max_p:
            single_suitable.append((name, info, 1))  # один сет
        if max_p >= 4:
            large_sets.append((name, info))
    
    recommendations = []
    
    # 1. Один сет, який ідеально підходить
    for name, info, qty in single_suitable:
        recommendations.append((name, info, qty))
    
    # 2. Якщо людей багато — пропонуємо комбінації з двох сетів
    if people >= 6:
        for name1, info1 in large_sets:
            max1 = info1["people"][1]
            remaining = people - max1
            if remaining <= 0:
                continue
            for name2, info2 in large_sets:
                if name1 == name2:
                    continue
                max2 = info2["people"][1]
                if min(info2["people"]) <= remaining <= max2 + 1:
                    # Уникаємо дублікатів
                    combo = tuple(sorted([name1, name2]))
                    if combo not in [tuple(sorted([r[0], r[0]])) for r in recommendations if False]:
                        recommendations.append((f"{name1} + {name2}", None, 2))
                        break  # беремо першу хорошу комбінацію для кожного
    
    # Обмежуємо кількість рекомендацій
    recommendations = recommendations[:8]
    
    if not recommendations:
        recommendations = [(n, i, 1) for n, i in large_sets[:5]]
    
    text = f"👥 Для <b>{people} осіб</b> рекомендуємо:\n\n"
    kb_buttons = []
    
    for item in recommendations:
        if item[2] == 1:  # один сет
            name, info, _ = item
            min_p, max_p = info["people"]
            text += (
                f"🍣 <b>{name}</b>\n"
                f"   На {min_p}-{max_p} осіб • {info['weight']} г • {info['price']} грн\n"
                f"   {info['desc']}\n\n"
            )
            kb_buttons.append([InlineKeyboardButton(text=f"Додати {name}", callback_data=f"add_{name}")])
        else:  # комбінація
            combo_name = item[0]
            text += f"🍣 <b>{combo_name}</b>\n   Два сети разом покриють ~{people} осіб\n\n"
            # Додаємо кнопки для кожного сету в комбінації
            parts = combo_name.split(" + ")
            for part in parts:
                if part in SETS:
                    kb_buttons.append([InlineKeyboardButton(text=f"Додати {part}", callback_data=f"add_{part}")])
    
    text += (
        "\n⚠️ <b>Прибори:</b>\n"
        "Якщо осіб більше, ніж у сеті — додаткові прибори <b>20.99 грн</b> за комплект.\n"
        "Можна також додати окремі роли, якщо не вистачає."
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons + [
        [InlineKeyboardButton(text="Показати всі сети", callback_data="all_sets")]
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("add_"))
async def add_to_cart(callback: types.CallbackQuery):
    set_name = callback.data[4:]
    if set_name not in SETS:
        await callback.answer("Сет не знайдено")
        return
    
    uid = callback.from_user.id
    if uid not in user_carts:
        user_carts[uid] = []
    user_carts[uid].append(set_name)
    
    people = user_people.get(uid, 1)
    info = SETS[set_name]
    min_p, max_p = info["people"]
    
    warning = ""
    if people > max_p:
        extra = people - max_p
        warning = f"\n⚠️ Для {people} осіб до цього сету потрібно ~{extra} додаткових комплектів приборів по 20.99 грн."
    
    await callback.message.answer(
        f"✅ Додано: <b>{set_name}</b> ({info['price']} грн){warning}\n\n"
        f"Кошик: {len(user_carts[uid])} позицій",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "all_sets")
async def show_all_sets(callback: types.CallbackQuery):
    text = "📋 Всі сети 911 Суші:\n\n"
    for name, info in list(SETS.items())[:15]:
        min_p, max_p = info["people"]
        text += f"• {name} — {min_p}-{max_p} ос., {info['weight']}г, {info['price']} грн\n"
    text += "\n... і ще більше. Напишіть назву сету або оберіть через рекомендації."
    await callback.message.answer(text)
    await callback.answer()

@dp.message(F.text == "🛒 Оформити замовлення")
async def start_order(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    cart = user_carts.get(uid, [])
    if not cart:
        await message.answer("Кошик порожній. Спочатку оберіть сети в меню.")
        return
    
    people = user_people.get(uid, 1)
    total = 0
    text = f"🛒 Ваше замовлення на {people} осіб:\n\n"
    extra_utensils = 0
    
    for set_name in cart:
        info = SETS[set_name]
        total += info["price"]
        min_p, max_p = info["people"]
        text += f"• {set_name} — {info['price']} грн\n"
        if people > max_p:
            extra_utensils += (people - max_p)
    
    utensils_cost = extra_utensils * EXTRA_UTENSILS_PRICE
    total += utensils_cost
    
    text += f"\n💰 Сума сетів: {total - utensils_cost:.2f} грн"
    if extra_utensils > 0:
        text += f"\n🥢 Додаткові прибори ({extra_utensils} компл. × 20.99): {utensils_cost:.2f} грн"
        text += "\n⚠️ Наголошуємо: додаткові прибори — 20.99 грн за комплект!"
    text += f"\n\n<b>Разом до сплати: {total:.2f} грн</b>"
    text += "\n\nОплата при отриманні або готівкою/картою кур'єру."
    
    await message.answer(text, parse_mode="HTML")
    await message.answer("Введіть адресу доставки:")
    await state.set_state(OrderStates.address)

@dp.message(OrderStates.address)
async def process_address(message: types.Message, state: FSMContext):
    await state.update_data(address=message.text)
    await message.answer("Введіть номер телефону для зв'язку:")
    await state.set_state(OrderStates.phone)

@dp.message(OrderStates.phone)
async def process_phone(message: types.Message, state: FSMContext):
    data = await state.get_data()
    address = data.get("address", "")
    phone = message.text
    uid = message.from_user.id
    people = user_people.get(uid, 1)
    cart = user_carts.get(uid, [])
    
    total = sum(SETS[s]["price"] for s in cart)
    # recalculate utensils
    extra = 0
    for s in cart:
        max_p = SETS[s]["people"][1]
        if people > max_p:
            extra += people - max_p
    utensils_cost = extra * EXTRA_UTENSILS_PRICE
    total += utensils_cost
    
    order_text = (
        f"🆕 НОВЕ ЗАМОВЛЕННЯ\n"
        f"Користувач: @{message.from_user.username or 'без username'} (ID: {uid})\n"
        f"Осіб: {people}\n"
        f"Адреса: {address}\n"
        f"Телефон: {phone}\n"
        f"Сети: {', '.join(cart)}\n"
        f"Додаткові прибори: {extra} × 20.99\n"
        f"Сума: {total:.2f} грн"
    )
    
    # Зберігаємо клієнта і замовлення в базу
    try:
        save_client_and_order(
            user_id=uid,
            username=message.from_user.username,
            phone=phone,
            address=address,
            sets=cart,
            total=total,
            people=people
        )
    except Exception as e:
        logging.warning(f"Помилка збереження в БД: {e}")
    
    try:
        await notify_admin_and_group(text=order_text, thread_id=THREAD_ORDERS)
    except Exception:
        pass  # якщо ID не налаштовано
    
    await message.answer(
        f"✅ Замовлення прийнято!\n\n"
        f"Сума: <b>{total:.2f} грн</b>\n"
        f"Адреса: {address}\n"
        f"Телефон: {phone}\n\n"
        f"Для оплати картою перейдіть у розділ «💳 Оплата» і надішліть фото чеку.\n"
        f"Або оплата при отриманні. Очікуйте дзвінка для підтвердження.\n"
        f"Дякуємо, що обрали 911 Суші! 🍣",
        parse_mode="HTML",
        reply_markup=main_menu()
    )
    # очистити кошик
    user_carts[uid] = []
    await state.clear()

@dp.message(F.text == "💳 Оплата")
async def payment_start(message: types.Message, state: FSMContext):
    await message.answer(
        f"💳 <b>Оплата замовлення</b>\n\n"
        f"⚠️ <b>ВАЖЛИВО!</b>\n"
        f"Спочатку обов’язково <b>узгодьте оплату з оператором</b> (напишіть у «💬 Звернення» або зателефонуйте).\n"
        f"Тільки після підтвердження оператором можна здійснювати переказ.\n\n"
        f"Номер картки для переказу:\n"
        f"<code>{CARD_NUMBER}</code>\n\n"
        f"Після оплати надішліть <b>фото чеку</b> (скріншот переказу).\n"
        f"Бот передасть його менеджеру для підтвердження.",
        parse_mode="HTML"
    )
    await state.set_state(OrderStates.waiting_payment_photo)

@dp.message(OrderStates.waiting_payment_photo, F.photo)
async def process_payment_photo(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    caption = (
        f"💳 ОПЛАТА / ЧЕК\n"
        f"Від: @{message.from_user.username or 'без username'} (ID: {uid})\n"
        f"Кошик: {', '.join(user_carts.get(uid, [])) or 'не вказано'}\n"
        f"Осіб: {user_people.get(uid, 'не вказано')}"
    )
    try:
        # Відправляємо фото і адміну, і в групу
        await notify_admin_and_group(photo=message.photo[-1].file_id, caption=caption, thread_id=THREAD_PAYMENT)
        await message.answer(
            "✅ Фото чеку отримано! Передали менеджеру.\n"
            "Очікуйте підтвердження оплати.",
            reply_markup=main_menu()
        )
    except Exception:
        await message.answer(
            "✅ Фото отримано, але не вдалося відправити (перевірте ADMIN_ID / GROUP_CHAT_ID).\n"
            "Збережіть чек і зв’яжіться з нами.",
            reply_markup=main_menu()
        )
    await state.clear()

@dp.message(OrderStates.waiting_payment_photo)
async def process_payment_not_photo(message: types.Message):
    await message.answer("Будь ласка, надішліть саме <b>фото</b> чеку (скріншот).", parse_mode="HTML")

@dp.message(F.text == "💬 Звернення")
async def inquiry_start(message: types.Message, state: FSMContext):
    await message.answer("Напишіть ваше звернення, питання або скаргу. Ми передамо його менеджеру.")
    await state.set_state(OrderStates.inquiry)

@dp.message(OrderStates.inquiry)
async def process_inquiry(message: types.Message, state: FSMContext):
    inquiry_text = (
        f"💬 ЗВЕРНЕННЯ КЛІЄНТА\n"
        f"Від: @{message.from_user.username or 'без username'} (ID: {message.from_user.id})\n"
        f"Текст: {message.text}"
    )
    try:
        await notify_admin_and_group(text=inquiry_text, thread_id=THREAD_INQUIRY)
    except Exception:
        pass
    await message.answer("Дякуємо! Ваше звернення відправлено. Очікуйте відповіді.", reply_markup=main_menu())
    await state.clear()

@dp.message(F.text == "📞 Контакти")
async def contacts(message: types.Message):
    await message.answer(
        "📞 Контакти 911 Суші (Дубно):\n"
        "Телефон: +380 99 400 09 11\n"
        "Адреса: вул. Зерова, 2\n"
        "Сайт: https://911sushi.com/\n"
        "Instagram: @911_sushi_lutsk\n\n"
        "Працюємо щодня з 10:00 до 22:00"
    )

@dp.message()
async def fallback(message: types.Message):
    await message.answer("Оберіть дію з меню або напишіть /start")

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


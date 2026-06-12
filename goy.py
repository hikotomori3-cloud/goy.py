import asyncio
import logging
import sqlite3
import re
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# ================= НАСТРОЙКИ БОТА =================
BOT_TOKEN = "8566981203:AAEvFc93f4O4AS76VkYvZ63c2SoG1bULNSE"
ADMIN_IDS = [7551725586]  # <-- ВСТАВЬТЕ СЮДА СВОЙ TELEGRAM ID СТРОГО ВНУТРИ СКОБОК

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= БАЗА ДАННЫХ (SQLite) =================
def init_db():
    conn = sqlite3.connect("wesbet.db")
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
        balance REAL DEFAULT 0.0, earned REAL DEFAULT 0.0,
        total_accounts INTEGER DEFAULT 0, is_banned INTEGER DEFAULT 0
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS phone_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        phone TEXT, status TEXT, date TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY, bot_status INTEGER DEFAULT 1, hold_time INTEGER DEFAULT 5,
        queue_count INTEGER DEFAULT 0, global_paid REAL DEFAULT 0.0,
        global_vstal INTEGER DEFAULT 0, global_slet INTEGER DEFAULT 0
    )""")
    cur.execute("INSERT OR IGNORE INTO settings VALUES (1, 1, 5, 0, 0.0, 0, 0)")
    conn.commit()
    conn.close()

init_db()

def get_settings():
    conn = sqlite3.connect("wesbet.db")
    cur = conn.cursor()
    cur.execute("SELECT bot_status, hold_time, queue_count, global_paid, global_vstal, global_slet FROM settings WHERE id=1")
    res = cur.fetchone()
    conn.close()
    return {"bot_status": res[0], "hold_time": res[1], "queue_count": res[2], "global_paid": res[3], "global_vstal": res[4], "global_slet": res[5]}

def update_setting(column, value):
    conn = sqlite3.connect("wesbet.db")
    cur = conn.cursor()
    cur.execute(f"UPDATE settings SET {column} = ? WHERE id = 1", (value,))
    conn.commit()
    conn.close()

def get_user(user_id, message_obj=None):
    conn = sqlite3.connect("wesbet.db")
    cur = conn.cursor()
    cur.execute("SELECT balance, earned, total_accounts, is_banned, username, first_name FROM users WHERE user_id = ?", (user_id,))
    res = cur.fetchone()
    if not res and message_obj:
        username = message_obj.from_user.username or "Не указан"
        first_name = message_obj.from_user.first_name or "Пользователь"
        cur.execute("INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)", (user_id, username, first_name))
        conn.commit()
        res = (0.0, 0.0, 0, 0, username, first_name)
    conn.close()
    return res

def update_user_balance(user_id, balance_change, earned_change=0.0, account_change=0):
    conn = sqlite3.connect("wesbet.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance=balance+?, earned=earned+?, total_accounts=total_accounts+? WHERE user_id=?", (balance_change, earned_change, account_change, user_id))
    conn.commit()
    conn.close()

# ================= СОСТОЯНИЯ (FSM) =================
class BotStates(StatesGroup):
    change_hold = State()
    broadcast = State()
    enter_phone = State()
    enter_code = State()
    enter_withdraw = State()
    unban_user = State()

# ================= ГЛАВНОЕ МЕНЮ =================
def get_main_menu(user_id):
    sets = get_settings()
    status_emoji = "🟢 Включен" if sets["bot_status"] else "🔴 Выключен"
    text = (
        f"👋 Добро пожаловать в бота WESBET TEAM!\n\n"
        f"┌ Статус работы: {status_emoji}\n"
        f"├ Актуальный прайс: 1$\n"
        f"├ Актуальная очередь: {sets['queue_count']}\n"
        f"└ Холд: {sets['hold_time']} минут\n\n👇 Выберите раздел:"
    )
    kb = ReplyKeyboardBuilder()
    kb.button(text="📱 Сдать аккаунт")
    kb.button(text="👤 Профиль")
    kb.button(text="📈 Статистика")
    kb.button(text="💸 Вывод средств")
    kb.button(text="📖 Инструкция")
    kb.button(text="🤝 Поддержка")
    if user_id in ADMIN_IDS: kb.button(text="🛠 Админ панель")
    kb.adjust(1, 2, 2, 1)
    return text, kb.as_markup(resize_keyboard=True)
# ================= ОБРАБОТЧИКИ ПОЛЬЗОВАТЕЛЕЙ =================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    u = get_user(message.from_user.id, message)
    if u and u[3] == 1: return await message.answer("🛑 Вы заблокированы в данном боте.")
    text, kb = get_main_menu(message.from_user.id)
    await message.answer(text, reply_markup=kb)

@dp.message(F.text == "👤 Профиль")
async def user_profile(message: types.Message):
    u = get_user(message.from_user.id, message)
    if u[3] == 1: return
    await message.answer(
        f"👤 **ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ**\n\n┌ Имя: {u[5]}\n├ Юзернейм: @{u[4]}\n└ ID: `{message.from_user.id}`\n\n"
        f"💰 **ФИНАНСОВАЯ СТАТИСТИКА**\n┌ Баланс: {u[0]:.2f}$\n├ Заработано: {u[1]:.2f}$\n\n"
        f"📱 **СДАННЫЕ АККАУНТЫ**\n└ Всего сдано аккаунтов: {u[2]} шт.", parse_mode="Markdown"
    )

@dp.message(F.text == "📱 Сдать аккаунт")
async def start_phone_input(message: types.Message, state: FSMContext):
    sets = get_settings()
    if not sets["bot_status"]: return await message.answer("⚠️ Извините, бот временно выключен администратором.")
    u = get_user(message.from_user.id, message)
    if u[3] == 1: return
    await state.set_state(BotStates.enter_phone)
    await message.answer("📱 Введите номер, который начинается на +7 например 79281233456 (только 11 цифр РФ):")

@dp.message(BotStates.enter_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = re.sub(r"\D", "", message.text)
    if len(phone) == 11 and phone.startswith("8"): phone = "7" + phone[1:]
    if len(phone) != 11 or not (phone.startswith("7") or phone.startswith("9")):
        return await message.answer("❌ Ошибка! Номер должен состоять ровно из 11 цифр РФ. Попробуйте еще раз:")
    
    sets = get_settings()
    update_setting("queue_count", sets["queue_count"] + 1)
    await state.update_data(phone=phone)
    await message.answer("⏳ Номер передан администратору на проверку. Ожидайте запроса кода...")

    kb = InlineKeyboardBuilder().button(text="🔑 Нужен код", callback_data=f"needcode_{message.from_user.id}_{phone}")
    for adm in ADMIN_IDS:
        try: await bot.send_message(adm, f"📱 **Новый номер!**\n\nОт: ID `{message.from_user.id}` (@{message.from_user.username})\nНомер: `{phone}`", reply_markup=kb.as_markup(), parse_mode="Markdown")
        except Exception: pass

@dp.callback_query(F.data.startswith("needcode_"))
async def admin_needs_code(call: types.CallbackQuery):
    _, user_id, phone = call.data.split("_")
    user_id = int(user_id)
    await call.message.edit_text(f"📱 Номер: `{phone}`\nСтатус: Запрошен код у пользователя.", parse_mode="Markdown")
    user_state = dp.fsm.resolve_context(bot, user_id, user_id)
    await user_state.set_state(BotStates.enter_code)
    await user_state.update_data(phone=phone)
    await bot.send_message(user_id, "🔑 Администратор запросил код! **Введите 4-значный код**. У вас есть 2 минуты:", parse_mode="Markdown")

@dp.message(BotStates.enter_code)
async def process_code(message: types.Message, state: FSMContext):
    code = message.text.strip()
    if not code.isdigit() or len(code) != 4: return await message.answer("❌ Ошибка! Код должен состоять строго из 4 ЦИФР. Попробуйте снова:")
    data = await state.get_data()
    phone = data.get("phone")
    await message.answer("⏳ Код отправлен админу. Ожидайте финального решения...")
    await state.clear()

    kb = InlineKeyboardBuilder()
    kb.button(text="🟢 Встал", callback_data=f"dec_vstal_{message.from_user.id}_{phone}")
    kb.button(text="🔴 Слет", callback_data=f"dec_slet_{message.from_user.id}_{phone}")
    for adm in ADMIN_IDS:
        try: await bot.send_message(adm, f"🔑 **Код для номера** `{phone}`\n\nОт: ID `{message.from_user.id}`\nКод: `{code}`", reply_markup=kb.as_markup(row_width=2), parse_mode="Markdown")
        except Exception: pass

@dp.callback_query(F.data.startswith("dec_"))
async def process_admin_decision(call: types.CallbackQuery):
    _, action, user_id, phone = call.data.split("_")
    user_id = int(user_id)
    sets = get_settings()
    if sets["queue_count"] > 0: update_setting("queue_count", sets["queue_count"] - 1)

    conn = sqlite3.connect("wesbet.db"); cur = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cur.execute("INSERT INTO phone_history (user_id, phone, status, date) VALUES (?, ?, ?, ?)", (user_id, phone, action, today))
    
    if action == "vstal":
        cur.execute("UPDATE settings SET global_vstal = global_vstal + 1 WHERE id=1")
        conn.commit(); conn.close()
        await call.message.edit_text(f"📱 Номер `{phone}`\nСтатус: 🟢 ВСТАЛ. Запущен холд {sets['hold_time']} мин.", parse_mode="Markdown")
        await bot.send_message(user_id, f"🟢 Ваш номер ВСТАЛ! Выплата 1$ поступит через {sets['hold_time']} минут.")
        
        pkb = InlineKeyboardBuilder()
        pkb.button(text="💥 Слет (Позже)", callback_data=f"post_slet_{user_id}_{phone}")
        pkb.button(text="🛑 Бан пользователя", callback_data=f"post_ban_{user_id}")
        await call.message.answer(f"⚙️ Управление `{phone}`:", reply_markup=pkb.as_markup(row_width=1))
        asyncio.create_task(hold_reward_task(user_id, phone, sets["hold_time"]))
    else:
        cur.execute("UPDATE settings SET global_slet = global_slet + 1 WHERE id=1")
        conn.commit(); conn.close()
        await call.message.edit_text(f"📱 Номер `{phone}`\nСтатус: 🔴 СЛЕТ.", parse_mode="Markdown")
        await bot.send_message(user_id, "🔴 Администратор отклонил номер (Слет).")

async def hold_reward_task(user_id: int, phone: str, minutes: int):
    await asyncio.sleep(minutes * 60)
    u = get_user(user_id)
    if u and u[3] == 0:
        update_user_balance(user_id, 1.0, 1.0, 1)
        try: await bot.send_message(user_id, f"💰 Холд прошел! 1$ зачислен за номер `{phone}`.")
        except Exception: pass

@dp.callback_query(F.data.startswith("post_"))
async def process_post_actions(call: types.CallbackQuery):
    data = call.data.split("_")
    action, user_id = data[1], int(data[2])
    conn = sqlite3.connect("wesbet.db"); cur = conn.cursor()
    if action == "slet":
        phone = data[3]
        cur.execute("UPDATE users SET balance=MAX(0.0, balance-1.0), earned=MAX(0.0, earned-1.0) WHERE user_id=?", (user_id,))
        await call.message.edit_text(f"💥 Зафиксирован поздний СЛЕТ по номеру `{phone}`. Баланс скорректирован.")
        try: await bot.send_message(user_id, f"💥 Администратор зафиксировал поздний слет по аккаунту `{phone}`. Баланс скорректирован.")
        except Exception: pass
    elif action == "ban":
        cur.execute("UPDATE users SET is_banned=1, balance=0.0 WHERE user_id=?", (user_id,))
        await call.message.edit_text(f"🛑 Пользователь `{user_id}` ЗАБЛОКИРОВАН, баланс обнулен.")
        try: await bot.send_message(user_id, "🛑 Вы были заблокированы администратором.")
        except Exception: pass
    conn.commit(); conn.close()
# ================= ВЫВОД СРЕДСТВ И СТАТИСТИКА =================
@dp.message(F.text == "💸 Вывод средств")
async def start_withdraw(message: types.Message, state: FSMContext):
    u = get_user(message.from_user.id, message)
    if u[3] == 1: return
    if u[0] <= 0: return await message.answer("❌ На вашем балансе 0.00$. Выводить нечего.")
    await state.set_state(BotStates.enter_withdraw)
    await message.answer(f"💸 Ваш баланс: {u[0]:.2f}$.\n\nВведите сумму вывода и реквизиты (одним сообщением):")

@dp.message(BotStates.enter_withdraw)
async def process_withdraw(message: types.Message, state: FSMContext):
    u = get_user(message.from_user.id)
    req = message.text.strip()
    match = re.match(r"^\d+(\.\d+)?", req)
    if not match: return await message.answer("❌ Укажите сумму цифрами в начале сообщения. Пример: '1.50 криптобот @username'")
    amt = float(match.group())
    if amt > u[0] or amt <= 0: return await message.answer(f"❌ Неверная сумма. Доступно: {u[0]:.2f}$")
    await state.clear()
    await message.answer("✅ Ваша заявка успешно отправлена администратору. Ожидайте выплаты.")
    
    kb = InlineKeyboardBuilder().button(text="💳 Оплачено", callback_data=f"pay_{message.from_user.id}_{amt}")
    for adm in ADMIN_IDS:
        try: await bot.send_message(adm, f"💰 **ЗАЯВКА НА ВЫВОД**\n\nЮзер ID: `{message.from_user.id}` (@{u[4]})\nСумма: **{amt}$**\nРеквизиты: {req}", reply_markup=kb.as_markup(), parse_mode="Markdown")
        except Exception: pass

@dp.callback_query(F.data.startswith("pay_"))
async def confirm_withdrawal(call: types.CallbackQuery):
    _, user_id, amt = call.data.split("_")
    user_id, amt = int(user_id), float(amt)
    update_user_balance(user_id, -amt)
    conn = sqlite3.connect("wesbet.db"); cur = conn.cursor()
    cur.execute("UPDATE settings SET global_paid = global_paid + ? WHERE id=1", (amt,))
    conn.commit(); conn.close()
    await call.message.edit_text(f"💰 Заявка `{user_id}` на {amt}$ помечена как **ОПЛАЧЕНО**.")
    try: await bot.send_message(user_id, f"🎉 Уведомление: Ваша заявка на вывод {amt}$ успешно ОПЛАЧЕНА!")
    except Exception: pass

@dp.message(F.text == "📈 Статистика")
async def stats(message: types.Message):
    sets = get_settings()
    conn = sqlite3.connect("wesbet.db"); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users"); total_users = cur.fetchone()[0]
    today = datetime.now().strftime("%Y-%m-%d")
    cur.execute("SELECT COUNT(*) FROM phone_history WHERE user_id=? AND date=? AND status='vstal'", (message.from_user.id, today))
    t_count = cur.fetchone()[0]; conn.close()
    await message.answer(
        f"📊 **СТАТИСТИКА WESBET TEAM**\n\n┌ Всего выплачено: {sets['global_paid']:.2f}$\n├ Всего людей в боте: {total_users}\n"
        f"├ Номеров успешно встало: {sets['global_vstal']} шт.\n└ Номеров слетело: {sets['global_slet']} шт.\n\n"
        f"📈 **ВАШИ ПОКАЗАТЕЛИ ЗА СЕГОДНЯ**\n└ Вы поставили за сегодня: {t_count} номеров", parse_mode="Markdown"
    )

@dp.message(F.text == "📖 Инструкция")
async def manual(message: types.Message): await message.answer("📖 **Правила сдачи:**\n1. Номер должен быть чистым.\n2. Время ожидания смс — до 2 минут.\n3. За слет номера во время холда выплата аннулируется.")

@dp.message(F.text == "🤝 Поддержка")
async def support(message: types.Message): await message.answer("🤝 Связь с администратором: @WESBET_OWNER")

# ================= АДМИН ПАНЕЛЬ =================
def get_admin_inline_kb():
    sets = get_settings()
    kb = InlineKeyboardBuilder()
    kb.button(text="🔴 Выключить бота" if sets["bot_status"] else "🟢 Включить бота", callback_data="adm_status")
    kb.button(text="⏱ Изменить холд", callback_data="adm_hold")
    kb.button(text="🧹 Очистить очередь", callback_data="adm_clear")
    kb.button(text="📢 Рассылка", callback_data="adm_bc")
    kb.button(text="🔓 Разблокировать юзера", callback_data="adm_unban")
    return kb.adjust(1, 2, 2).as_markup()

@dp.message(F.text == "🛠 Админ панель")
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    await message.answer("🛠 Панель управления WESBET TEAM:", reply_markup=get_admin_inline_kb())

@dp.callback_query(F.data == "adm_status")
async def toggle_status(call: types.CallbackQuery):
    sets = get_settings(); new_s = 0 if sets["bot_status"] else 1
    update_setting("bot_status", new_s)
    await call.message.edit_text("🛠 Панель управления WESBET TEAM:", reply_markup=get_admin_inline_kb())
    await call.answer(f"Статус бота изменен!")

@dp.callback_query(F.data == "adm_clear")
async def clear_queue(call: types.CallbackQuery):
    update_setting("queue_count", 0); await call.answer("Очередь очищена!")

@dp.callback_query(F.data == "adm_hold")
async def change_hold_start(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotStates.change_hold); await call.message.answer("Введите новое время холда (число минут):"); await call.answer()

@dp.message(BotStates.change_hold)
async def change_hold_finish(message: types.Message, state: FSMContext):
    if message.text.isdigit():
        update_setting("hold_time", int(message.text)); await message.answer("✅ Холд изменен!"); await state.clear()
    else: await message.answer("Введите число.")

@dp.callback_query(F.data == "adm_unban")
async def unban_start(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotStates.unban_user); await call.message.answer("Введите Telegram ID пользователя для разблокировки:"); await call.answer()

@dp.message(BotStates.unban_user)
async def unban_finish(message: types.Message, state: FSMContext):
    if message.text.isdigit():
        uid = int(message.text)
        conn = sqlite3.connect("wesbet.db"); cur = conn.cursor()
        cur.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (uid,))
        conn.commit(); conn.close()
        await message.answer(f"✅ Пользователь `{uid}` успешно разблокирован!"); await state.clear()
        try: await bot.send_message(uid, "🎉 Вы были разблокированы администратором и снова можете сдавать аккаунты.")
        except Exception: pass
    else: await message.answer("ID должен состоять только из цифр.")

@dp.callback_query(F.data == "adm_bc")
async def broadcast_start(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotStates.broadcast); await call.message.answer("Введите текст рассылки:"); await call.answer()

@dp.message(BotStates.broadcast)
async def broadcast_finish(message: types.Message, state: FSMContext):
    conn = sqlite3.connect("wesbet.db"); cur = conn.cursor(); cur.execute("SELECT user_id FROM users"); users = cur.fetchall(); conn.close()
    count = 0
    for row in users:
        try: await bot.send_message(row[0], message.text); count += 1
        except Exception: pass
    await message.answer(f"📢 Рассылка завершена! Получили {count} человек."); await state.clear()

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))

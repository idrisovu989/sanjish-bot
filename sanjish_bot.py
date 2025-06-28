import asyncio
import logging
import sqlite3
import bcrypt
import random
import os
from datetime import date

from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.exceptions import TelegramBadRequest

# --- ТАНЗИМОТ (CONFIGURATION) ---
BOT_TOKEN = "8132721879:AAEO6EF8FSvOi3MHENA4A6ldBzjMlfHhXho" # Токени худро ворид кунед
ADMIN_ID = 7226492351 # ID-и худро ворид кунед
DB_FILE = "SanjishDB.db"
QUESTIONS_PER_TEST = 15

# --- СОХТОРИ БАЗАИ МАЪЛУМОТ (DATABASE SETUP) ---
def setup_database():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Korbaron (
            telegram_id INTEGER PRIMARY KEY, user_id_custom TEXT UNIQUE, nomu_nasab TEXT NOT NULL, parol BLOB NOT NULL, role TEXT DEFAULT 'donishju'
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Fanho (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nomi_fan TEXT UNIQUE NOT NULL
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS PasswordRequests (
            telegram_id INTEGER PRIMARY KEY, user_name TEXT NOT NULL, verification_code TEXT NOT NULL
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Savolho (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fan_id INTEGER NOT NULL, savol_matn TEXT NOT NULL,
            variant_a TEXT NOT NULL, variant_b TEXT NOT NULL, variant_c TEXT NOT NULL, variant_d TEXT NOT NULL,
            javobi_durust TEXT NOT NULL, FOREIGN KEY (fan_id) REFERENCES Fanho (id) ON DELETE CASCADE
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Natijaho (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_telegram_id INTEGER NOT NULL, fan_id INTEGER NOT NULL,
            sanai_suporidan DATE NOT NULL, javobhoi_durust INTEGER NOT NULL, javobhoi_nodurust INTEGER NOT NULL,
            FOREIGN KEY (user_telegram_id) REFERENCES Korbaron (telegram_id) ON DELETE CASCADE,
            FOREIGN KEY (fan_id) REFERENCES Fanho (id) ON DELETE CASCADE
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS AnsweredQuestions (
            user_telegram_id INTEGER NOT NULL, savol_id INTEGER NOT NULL,
            PRIMARY KEY (user_telegram_id, savol_id),
            FOREIGN KEY (user_telegram_id) REFERENCES Korbaron (telegram_id) ON DELETE CASCADE,
            FOREIGN KEY (savol_id) REFERENCES Savolho (id) ON DELETE CASCADE
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS SupportTickets (
            ticket_id INTEGER PRIMARY KEY AUTOINCREMENT, user_telegram_id INTEGER NOT NULL, user_name TEXT,
            message_text TEXT NOT NULL, status TEXT DEFAULT 'open', timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_telegram_id) REFERENCES Korbaron (telegram_id) ON DELETE CASCADE
        )""")
        cursor.execute("SELECT * FROM Korbaron WHERE telegram_id = ?", (ADMIN_ID,))
        if not cursor.fetchone():
            dummy_password = bcrypt.hashpw(os.urandom(16), bcrypt.gensalt())
            cursor.execute("INSERT INTO Korbaron (telegram_id, user_id_custom, nomu_nasab, parol, role) VALUES (?, ?, ?, ?, ?)",
                           (ADMIN_ID, 'ADMIN-001', '👑 Администратор', dummy_password, 'admin'))

# --- ФУНКСИЯҲОИ ЁРИРАСОН ---
def db_execute(query, params=(), fetchone=False, fetchall=False):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.execute(query, params)
        if fetchone: return cursor.fetchone()
        if fetchall: return cursor.fetchall()
        conn.commit()

def generate_custom_user_id():
    last_id_row = db_execute("SELECT user_id_custom FROM Korbaron WHERE user_id_custom LIKE 'USER-%' ORDER BY user_id_custom DESC LIMIT 1", fetchone=True)
    return f"USER-{(int(last_id_row[0].split('-')[1]) + 1):04d}" if last_id_row else "USER-0001"

# --- ҲОЛАТҲОИ FSM ---
class AuthStates(StatesGroup): getting_name, getting_password_register, getting_password_login = State(), State(), State()
class AdminStates(StatesGroup): add_fan_name, add_question_select_fan, add_question_text, add_question_option_a, add_question_option_b, add_question_option_c, add_question_option_d, add_question_correct_answer, delete_question_select_fan, replying_to_ticket = State(), State(), State(), State(), State(), State(), State(), State(), State(), State()
class PasswordResetStates(StatesGroup): getting_new_password = State()
class StudentStates(StatesGroup): taking_test, getting_support_message = State(), State()
class SettingsStates(StatesGroup): getting_new_password_from_settings = State()

# --- КЛАВИАТУРАҲО ---
def get_start_keyboard(is_registered): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔑 Воридшавӣ", callback_data="login_start")], [InlineKeyboardButton(text="🔄 Иваз кардани парол", callback_data="reset_password_start")]] if is_registered else [[InlineKeyboardButton(text="📝 Бақайдгирӣ", callback_data="register_start")]])
def get_admin_panel_keyboard(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📚 Идораи Фанҳо", callback_data="admin_manage_fanho"), InlineKeyboardButton(text="❓ Идораи Саволҳо", callback_data="admin_manage_questions")], [InlineKeyboardButton(text="👥 Рӯйхати Корбарон", callback_data="admin_manage_users"), InlineKeyboardButton(text="🔒 Дархостҳои Парол", callback_data="admin_password_requests")], [InlineKeyboardButton(text="📨 Паёмҳои Кӯмак", callback_data="admin_support_tickets")], [InlineKeyboardButton(text="🔄 Навсозӣ", callback_data="admin_refresh_panel")]])
def get_student_panel_keyboard(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✍️ Супоридани Тест", callback_data="student_start_test")], [InlineKeyboardButton(text="📊 Натиҷаҳои Ман", callback_data="student_my_results")], [InlineKeyboardButton(text="⚙️ Танзимот", callback_data="student_settings")]])
def get_student_settings_inline_keyboard(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Иваз кардани парол", callback_data="settings_change_password")], [InlineKeyboardButton(text="⬅️ Бозгашт ба Меню", callback_data="back_to_student_panel")]])
def get_student_reply_keyboard(): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="✍️ Супоридани Тест"), KeyboardButton(text="📊 Натиҷаҳои Ман")], [KeyboardButton(text="⚙️ Танзимот"), KeyboardButton(text="💬 Кӯмак")], [KeyboardButton(text="🚪 Баромадан")]], resize_keyboard=True)
back_button_admin, back_button_student = InlineKeyboardButton(text="⬅️ Бозгашт", callback_data="back_to_admin_panel"), InlineKeyboardButton(text="⬅️ Бозгашт ба Меню", callback_data="back_to_student_panel_main_menu")

# --- РОУТЕРҲО ---
main_router, admin_router, student_router = Router(), Router(), Router()

# --- HANDLER-ҲОИ АСОСӢ ВА АУТЕНТИФИКАТСИЯ ---
@main_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user.id == ADMIN_ID:
        await message.answer("👑 **Панели Администратор**", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
    else:
        user = db_execute("SELECT * FROM Korbaron WHERE telegram_id = ?", (message.from_user.id,), fetchone=True)
        await message.answer(f"👋 **Салом, {message.from_user.first_name}!**\nХуш омадед ба **Sanjish Bot**!", reply_markup=ReplyKeyboardRemove(), parse_mode="Markdown")
        prompt = "_Шумо аллакай сабт шудаед. Барои идома ворид шавед._" if user else "_Барои оғози кор аз бақайдгирӣ гузаред._"
        await message.answer(prompt, reply_markup=get_start_keyboard(is_registered=bool(user)), parse_mode="Markdown")

@main_router.callback_query(F.data == "register_start")
async def register_start(callback: CallbackQuery, state: FSMContext): await callback.message.edit_text("📝 **Бақайдгирӣ**\n\n_Ном ва насаби пурраи худро ворид кунед:_\n(Масалан: Алиев Валӣ)", parse_mode="Markdown"); await state.set_state(AuthStates.getting_name); await callback.answer()
@main_router.message(AuthStates.getting_name)
async def get_name(message: Message, state: FSMContext):
    if not message.text or len(message.text.split()) < 2: await message.answer("❌ **Хатогӣ:** Ном ва насаби худро дуруст ворид кунед."); return
    await state.update_data(nomu_nasab=message.text); await message.answer("🔐 Акнун, пароли худро фикр кунед.\n_Парол бояд > 5 аломат бошад._", parse_mode="Markdown"); await state.set_state(AuthStates.getting_password_register)
@main_router.message(AuthStates.getting_password_register)
async def get_password_register(message: Message, state: FSMContext):
    parol = message.text
    try: await message.delete()
    except TelegramBadRequest: pass
    if not parol or len(parol) < 6: await message.answer("⚠️ **Огоҳӣ:** Парол бояд ҳадди ақал 6 аломат дошта бошад."); return
    user_data = await state.get_data(); user_id_custom = generate_custom_user_id()
    hashed_password = bcrypt.hashpw(parol.encode('utf-8'), bcrypt.gensalt())
    db_execute("INSERT INTO Korbaron (telegram_id, user_id_custom, nomu_nasab, parol) VALUES (?, ?, ?, ?)", (message.from_user.id, user_id_custom, user_data['nomu_nasab'], hashed_password))
    await message.answer(f"🎉 **Табрик, {user_data['nomu_nasab']}!**\nШумо сабти ном шудед!\n**ID-и шумо:** `{user_id_custom}`", parse_mode="Markdown")
    await state.clear(); await asyncio.sleep(2); await cmd_start(message, state)
@main_router.callback_query(F.data == "login_start")
async def login_start(callback: CallbackQuery, state: FSMContext): await state.update_data(main_menu_message_id=callback.message.message_id); await callback.message.edit_text("🔐 **Воридшавӣ**\n\n_Пароли худро ворид кунед:_", parse_mode="Markdown"); await state.set_state(AuthStates.getting_password_login); await callback.answer()
@main_router.message(AuthStates.getting_password_login)
async def get_password_login(message: Message, state: FSMContext, bot: Bot):
    parol_entered = message.text; user_data_fsm = await state.get_data(); main_menu_message_id = user_data_fsm.get('main_menu_message_id')
    try:
        await message.delete()
        if main_menu_message_id:
            await bot.delete_message(message.chat.id, main_menu_message_id)
    except TelegramBadRequest:
        pass
    user_db_data = db_execute("SELECT parol, role, nomu_nasab FROM Korbaron WHERE telegram_id = ?", (message.from_user.id,), fetchone=True)
    if user_db_data and bcrypt.checkpw(parol_entered.encode('utf-8'), user_db_data[0]):
        role, nomu_nasab = user_db_data[1], user_db_data[2]; await state.clear()
        if role == 'admin': await message.answer("👑 **Панели Администратор**", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
        else: await message.answer(f"🎓 **Кабинети шахсии {nomu_nasab}**", reply_markup=get_student_reply_keyboard(), parse_mode="Markdown")
    else:
        await state.clear(); sent_msg = await message.answer("❌ **Пароли нодуруст!**", parse_mode="Markdown"); await asyncio.sleep(2)
        try: await sent_msg.delete()
        except TelegramBadRequest: pass
        await cmd_start(message, state)
@main_router.message(F.text == "🚪 Баромадан")
async def logout_reply_button(message: Message, state: FSMContext): await state.clear(); await message.answer("🚪 Шумо аз система баромадед.", reply_markup=ReplyKeyboardRemove()); await asyncio.sleep(1); await cmd_start(message, state)
@admin_router.callback_query(F.data == "admin_refresh_panel")
async def refresh_admin_panel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try: await callback.message.edit_text("👑 **Панели Администратор**", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
    except TelegramBadRequest: await callback.message.answer("👑 **Панели Администратор**", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
    await callback.answer("Панел навсозӣ шуд.")
@main_router.callback_query(F.data == "reset_password_start")
async def reset_password_start(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id;
    if db_execute("SELECT * FROM PasswordRequests WHERE telegram_id = ?", (user_id,), fetchone=True): await callback.answer("⏳ Шумо аллакай дархост фиристодаед.", show_alert=True); return
    verification_code = str(random.randint(1000, 9999))
    db_execute("INSERT INTO PasswordRequests (telegram_id, user_name, verification_code) VALUES (?, ?, ?)", (user_id, callback.from_user.full_name, verification_code))
    try: await bot.send_message(ADMIN_ID, f"🔔 **Дархости нав!**\nКорбари {callback.from_user.full_name} (`{user_id}`) ивази паролро хост.", parse_mode="Markdown")
    except Exception as e: logging.error(f"Failed to send message to admin: {e}")
    await callback.answer("✅ Дархости шумо фиристода шуд.", show_alert=True)
@main_router.callback_query(F.data.startswith("vcode_"))
async def verify_code(callback: CallbackQuery, state: FSMContext, bot: Bot):
    _, selected, correct = callback.data.split("_")
    try: await callback.message.delete(); await bot.delete_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id - 1)
    except TelegramBadRequest: pass
    if selected == correct: await callback.message.answer("✅ Код дуруст. Пароли навро ворид кунед (мин. 6 аломат):"); await state.set_state(PasswordResetStates.getting_new_password)
    else: await callback.message.answer("❌ Коди нодуруст! Раванд бекор шуд. /start")
    await callback.answer()

@main_router.message(PasswordResetStates.getting_new_password)
async def get_new_password(message: Message, state: FSMContext):
    parol = message.text
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    if not parol or len(parol) < 6: await message.answer("⚠️ **Огоҳӣ:** Парол бояд ҳадди ақал 6 аломат дошта бошад."); return

    hashed_password = bcrypt.hashpw(parol.encode('utf-8'), bcrypt.gensalt())
    db_execute("UPDATE Korbaron SET parol = ? WHERE telegram_id = ?", (hashed_password, message.from_user.id))
    db_execute("DELETE FROM PasswordRequests WHERE telegram_id = ?", (message.from_user.id,)) # Clean up request
    await state.clear(); await message.answer("✅ **Парол бомуваффақият иваз карда шуд!**", parse_mode="Markdown"); await asyncio.sleep(2); await cmd_start(message, state)

# --- ПАНЕЛИ АДМИНИСТРАТОР ---
@admin_router.callback_query(F.data == "back_to_admin_panel")
async def back_to_admin_panel(callback: CallbackQuery, state: FSMContext): await state.clear(); await callback.message.edit_text("👑 **Панели Администратор**", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
async def send_manage_fanho_menu(message_or_callback: types.Message | types.CallbackQuery):
    fanho = db_execute("SELECT nomi_fan FROM Fanho", fetchall=True)
    text = "📚 **Идоракунии Фанҳо**\n\n" + ("\n".join([f"🔹 `{fan[0]}`" for fan in fanho]) if fanho else "_Ягон фан илова нашудааст._")
    buttons = [[InlineKeyboardButton(text="➕ Иловаи Фан", callback_data="admin_add_fan")], [InlineKeyboardButton(text="➖ Нест кардани Фан", callback_data="admin_delete_fan_start")], [back_button_admin]]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    if isinstance(message_or_callback, types.CallbackQuery): await message_or_callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    else: await message_or_callback.answer(text, reply_markup=markup, parse_mode="Markdown")
@admin_router.callback_query(F.data == "admin_manage_fanho")
async def admin_manage_fanho(callback: CallbackQuery): await send_manage_fanho_menu(callback)
@admin_router.callback_query(F.data == "admin_add_fan")
async def admin_add_fan_start(callback: CallbackQuery, state: FSMContext): await callback.message.edit_text("✍️ Номи фанни навро ворид кунед:"); await state.set_state(AdminStates.add_fan_name)
@admin_router.message(AdminStates.add_fan_name)
async def admin_add_fan_name(message: Message, state: FSMContext):
    try: db_execute("INSERT INTO Fanho (nomi_fan) VALUES (?)", (message.text,)); await message.answer(f"✅ Фанни '{message.text}' илова шуд.")
    except sqlite3.IntegrityError: await message.answer(f"⚠️ Фанни '{message.text}' аллакай мавҷуд аст.")
    await state.clear(); await send_manage_fanho_menu(message)
@admin_router.callback_query(F.data == "admin_delete_fan_start")
async def admin_delete_fan_start(callback: CallbackQuery):
    fanho = db_execute("SELECT id, nomi_fan FROM Fanho", fetchall=True)
    if not fanho: await callback.answer("❌ Ягон фан барои нест кардан нест.", show_alert=True); return
    buttons = [[InlineKeyboardButton(text=f"🗑️ {fan[1]}", callback_data=f"delete_fan_{fan[0]}")] for fan in fanho]; buttons.append([InlineKeyboardButton(text="⬅️ Бозгашт", callback_data="admin_manage_fanho")])
    await callback.message.edit_text("Кадом фанро нест кардан мехоҳед?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
@admin_router.callback_query(F.data.startswith("delete_fan_"))
async def admin_delete_fan_confirm(callback: CallbackQuery): db_execute("DELETE FROM Fanho WHERE id = ?", (int(callback.data.split("_")[2]),)); await callback.answer("✅ Фан нест карда шуд!", show_alert=True); await send_manage_fanho_menu(callback)
@admin_router.callback_query(F.data == "admin_manage_users")
async def admin_manage_users(callback: CallbackQuery):
    users = db_execute("SELECT user_id_custom, nomu_nasab FROM Korbaron WHERE role != 'admin'", fetchall=True)
    text = "👥 **Рӯйхати Корбарон**\n\n" + ("\n".join([f"{i}. **{user[1]}**\n   _ID:_ `{user[0]}`" for i, user in enumerate(users, 1)]) if users else "_Корбарон сабти ном нашудаанд._")
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button_admin]]), parse_mode="Markdown")
@admin_router.callback_query(F.data == "admin_manage_questions")
async def admin_manage_questions(callback: CallbackQuery):
    buttons = [[InlineKeyboardButton(text="➕ Иловаи Савол", callback_data="q_add_start")], [InlineKeyboardButton(text="🗑️ Нест кардани Савол", callback_data="q_view_delete_start")], [back_button_admin]]
    await callback.message.edit_text("❓ **Идоракунии Саволҳо**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")
@admin_router.callback_query(F.data == "q_add_start")
async def q_add_start(callback: CallbackQuery, state: FSMContext):
    fanho = db_execute("SELECT id, nomi_fan FROM Fanho", fetchall=True);
    if not fanho: await callback.answer("Аввал фан илова кунед!", show_alert=True); return
    buttons = [[InlineKeyboardButton(text=f, callback_data=f"q_add_fan_{i}")] for i, f in fanho]; buttons.append([InlineKeyboardButton(text="⬅️ Бозгашт", callback_data="admin_manage_questions")])
    await callback.message.edit_text("Барои кадом фан савол илова мекунед?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await state.set_state(AdminStates.add_question_select_fan)
@admin_router.callback_query(F.data.startswith("q_add_fan_"), AdminStates.add_question_select_fan)
async def q_add_fan_selected(callback: CallbackQuery, state: FSMContext): await state.update_data(fan_id=int(callback.data.split("_")[3])); await callback.message.edit_text("Матни саволро нависед:"); await state.set_state(AdminStates.add_question_text)
@admin_router.message(AdminStates.add_question_text)
async def q_get_text(message: Message, state: FSMContext): await state.update_data(savol_matn=message.text); await message.answer("Варианти 'А':"); await state.set_state(AdminStates.add_question_option_a)
@admin_router.message(AdminStates.add_question_option_a)
async def q_get_opt_a(message: Message, state: FSMContext): await state.update_data(variant_a=message.text); await message.answer("Варианти 'Б':"); await state.set_state(AdminStates.add_question_option_b)
@admin_router.message(AdminStates.add_question_option_b)
async def q_get_opt_b(message: Message, state: FSMContext): await state.update_data(variant_b=message.text); await message.answer("Варианти 'В':"); await state.set_state(AdminStates.add_question_option_c)
@admin_router.message(AdminStates.add_question_option_c)
async def q_get_opt_c(message: Message, state: FSMContext): await state.update_data(variant_c=message.text); await message.answer("Варианти 'Г':"); await state.set_state(AdminStates.add_question_option_d)
@admin_router.message(AdminStates.add_question_option_d)
async def q_get_opt_d(message: Message, state: FSMContext):
    await state.update_data(variant_d=message.text); buttons = [[InlineKeyboardButton(text=c, callback_data=f"q_correct_{c}")] for c in "ABCD"]
    await message.answer("Ҷавоби дурустро интихоб кунед:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await state.set_state(AdminStates.add_question_correct_answer)
@admin_router.callback_query(F.data.startswith("q_correct_"), AdminStates.add_question_correct_answer)
async def q_get_correct_answer(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data(); db_execute("INSERT INTO Savolho (fan_id, savol_matn, variant_a, variant_b, variant_c, variant_d, javobi_durust) VALUES (?, ?, ?, ?, ?, ?, ?)", (data['fan_id'], data['savol_matn'], data['variant_a'], data['variant_b'], data['variant_c'], data['variant_d'], callback.data.split("_")[2]))
    await state.clear(); await callback.message.edit_text("✅ Савол бомуваффақият илова шуд!")
    await callback.message.answer("Панели саволҳо:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Иловаи дигар", callback_data="q_add_start")], [back_button_admin]]))
@admin_router.callback_query(F.data == "q_view_delete_start")
async def q_view_delete_start(callback: CallbackQuery, state: FSMContext): await q_add_start(callback, state); await state.set_state(AdminStates.delete_question_select_fan)
@admin_router.callback_query(F.data.startswith("q_add_fan_"), AdminStates.delete_question_select_fan)
async def q_delete_fan_selected(callback: CallbackQuery, state: FSMContext):
    questions = db_execute("SELECT id, savol_matn FROM Savolho WHERE fan_id = ?", (int(callback.data.split("_")[3]),), fetchall=True)
    if not questions: await callback.answer("❌ Барои ин фан савол нест.", show_alert=True); await state.clear(); return
    buttons = [[InlineKeyboardButton(text=f"❌ {q_text[:40]}...", callback_data=f"q_delete_{q_id}")] for q_id, q_text in questions]; buttons.append([InlineKeyboardButton(text="⬅️ Бозгашт", callback_data="admin_manage_questions")])
    await callback.message.edit_text("Саволро барои нест кардан интихоб кунед:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await state.clear()
@admin_router.callback_query(F.data.startswith("q_delete_"))
async def q_delete_confirm(callback: CallbackQuery): db_execute("DELETE FROM Savolho WHERE id = ?", (int(callback.data.split("_")[2]),)); await callback.answer("✅ Савол нест шуд!", show_alert=True); await admin_manage_questions(callback)
@admin_router.callback_query(F.data == "admin_password_requests")
async def admin_password_requests(callback: CallbackQuery):
    requests = db_execute("SELECT telegram_id, user_name FROM PasswordRequests", fetchall=True)
    if not requests: await callback.answer("✅ Дархостҳои фаъол вуҷуд надоранд.", show_alert=True); return
    buttons = [[InlineKeyboardButton(text=f"Тасдиқ: {req[1]}", callback_data=f"approve_reset_{req[0]}")] for req in requests]; buttons.append([back_button_admin])
    await callback.message.edit_text("🔒 Рӯйхати дархостҳои фаъол:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
@admin_router.callback_query(F.data.startswith("approve_reset_"))
async def approve_reset(callback: CallbackQuery, bot: Bot):
    user_id = int(callback.data.split("_")[2]); request_data = db_execute("SELECT verification_code FROM PasswordRequests WHERE telegram_id = ?", (user_id,), fetchone=True)
    if not request_data: await callback.answer("Ин дархост дигар фаъол нест.", show_alert=True); return
    correct_code = request_data[0]
    try:
        await bot.send_message(user_id, f"🔑 Коди тасдиқии шумо: ||{correct_code}||", parse_mode="MarkdownV2")
        options = {correct_code};
        while len(options) < 4: options.add(str(random.randint(1000, 9999)))
        shuffled_options = list(options); random.shuffle(shuffled_options)
        code_buttons = [[InlineKeyboardButton(text=opt, callback_data=f"vcode_{opt}_{correct_code}")] for opt in shuffled_options]
        await bot.send_message(user_id, "Коди дурустро интихоб кунед:", reply_markup=InlineKeyboardMarkup(inline_keyboard=code_buttons))
        await callback.answer("✅ Дархост тасдиқ шуд.", show_alert=True); 
        # Дархост дар ин ҷо нест карда намешавад, балки баъди ивази парол
        await admin_password_requests(callback)
    except Exception as e: await callback.answer(f"❌ Хатогӣ: {e}", show_alert=True)

# --- ПАНЕЛИ ДОНИШҶӮ ---

# --- >>>>> ҚИСМИ ИСЛОҲШУДА <<<<< ---
@student_router.callback_query(F.data == "back_to_student_panel")
async def back_to_student_panel_callback(callback: types.CallbackQuery, state: FSMContext):
    """
    Ин функсия хатогӣ дошт. Рафтори дуруст ин аст:
    1. Паёми кӯҳнаро, ки тугмаи "Бозгашт" дошт, нест кунед (`callback.message.delete()`).
    2. Паёми навро бо матни Кабинети шахсӣ ва клавиатураи асосӣ (`ReplyKeyboardMarkup`) фиристед.
    """
    await state.clear()
    user = db_execute("SELECT nomu_nasab FROM Korbaron WHERE telegram_id = ?", (callback.from_user.id,), fetchone=True)
    
    # Ҷавоб ба callback барои аз байн бурдани "соатча" дар тугма
    await callback.answer()

    # Нест кардани паёми ҷорӣ (масалан, менюи "Танзимот")
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        # Агар паём аллакай нест шуда бошад, хатогиро сарфи назар мекунем
        pass

    # Фиристодани паёми нав бо клавиатураи ReplyKeyboard
    if user:
        await callback.message.answer(
            f"🎓 **Кабинети шахсии {user[0]}**",
            reply_markup=get_student_reply_keyboard(),
            parse_mode="Markdown"
        )

# --- >>>>> АНҶОМИ ҚИСМИ ИСЛОҲШУДА <<<<< ---

# Давомнокии боқимондаи код
@main_router.message(F.text == "✍️ Супоридани Тест")
async def student_start_test(message: Message, state: FSMContext):
    await state.clear() # Тоза кардани ҳолати пешина
    fanho = db_execute("SELECT id, nomi_fan FROM Fanho WHERE id IN (SELECT DISTINCT fan_id FROM Savolho)", fetchall=True)
    if not fanho: 
        await message.answer("⏳ Тестҳои фаъол ҳоло вуҷуд надоранд."); 
        return
    
    buttons = [[InlineKeyboardButton(text=f"🔸 {f}", callback_data=f"test_fan_{i}")] for i, f in fanho]
    # Тугмаи бозгашт дар ин ҷо лозим нест, чун корбар метавонад аз клавиатураи асосӣ истифода барад.
    await message.answer(
        "✍️ **Интихоби фан барои тест**", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), 
        parse_mode="Markdown"
    )

@student_router.callback_query(F.data == "back_to_student_panel_main_menu")
async def back_to_student_panel_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user = db_execute("SELECT nomu_nasab FROM Korbaron WHERE telegram_id = ?", (callback.from_user.id,), fetchone=True)
    await callback.message.edit_text(f"🎓 **Кабинети шахсии {user[0]}**", reply_markup=get_student_reply_keyboard(), parse_mode="Markdown")


@main_router.message(F.text == "📊 Натиҷаҳои Ман")
async def student_my_results(message: Message, state: FSMContext):
    await state.clear()
    results = db_execute("SELECT f.nomi_fan, r.sanai_suporidan, r.javobhoi_durust, r.javobhoi_nodurust FROM Natijaho r JOIN Fanho f ON r.fan_id = f.id WHERE r.user_telegram_id = ? ORDER BY r.id DESC", (message.from_user.id,), fetchall=True)
    text = "📊 **Натиҷаҳои охирини ман**\n\n"
    if results:
        for fan, sana, d, n in results:
            total = d + n
            percent = (d / total * 100) if total > 0 else 0
            emoji = '🏆' if percent >= 80 else '👍' if percent >= 50 else '🤔'
            text += f"🔹 **Фан:** {fan} {emoji}\n   _Сана:_ `{sana}`\n   _Натиҷа:_ **{d}** дуруст аз {total} ({percent:.0f}%)\n\n"
    else:
        text += "_Шумо то ҳол ягон тест насупоридаед._"
        
    await message.answer(text, parse_mode="Markdown")


@main_router.message(F.text == "⚙️ Танзимот")
async def student_settings(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("⚙️ **Танзимот**", reply_markup=get_student_settings_inline_keyboard(), parse_mode="Markdown")

@student_router.callback_query(F.data == "settings_change_password")
async def settings_change_password(callback: CallbackQuery, state: FSMContext): 
    await callback.message.edit_text("✍️ Пароли нави худро ворид кунед (мин. 6 аломат):")
    await state.set_state(SettingsStates.getting_new_password_from_settings)
    await callback.answer()

@student_router.message(SettingsStates.getting_new_password_from_settings)
async def get_new_password_from_settings(message: Message, state: FSMContext, bot: Bot):
    parol = message.text
    try: await message.delete()
    except TelegramBadRequest: pass
    
    if not parol or len(parol) < 6:
        await message.answer("⚠️ **Огоҳӣ:** Парол бояд ҳадди ақал 6 аломат дошта бошад.")
        return

    hashed_password = bcrypt.hashpw(parol.encode('utf-8'), bcrypt.gensalt())
    db_execute("UPDATE Korbaron SET parol = ? WHERE telegram_id = ?", (hashed_password, message.from_user.id))
    await state.clear()
    
    sent_msg = await message.answer("✅ **Парол бомуваффақият иваз карда шуд!**", parse_mode="Markdown")
    await asyncio.sleep(2)
    try:
        await sent_msg.delete()
    except TelegramBadRequest:
        pass
    
    # Ба ҷои таҳрир, паёми нав мефиристем
    user = db_execute("SELECT nomu_nasab FROM Korbaron WHERE telegram_id = ?", (message.from_user.id,), fetchone=True)
    await message.answer(f"🎓 **Кабинети шахсии {user[0]}**", reply_markup=get_student_reply_keyboard(), parse_mode="Markdown")

@student_router.callback_query(F.data.startswith("test_fan_"))
async def start_test_for_fan(callback: CallbackQuery, state: FSMContext, bot: Bot):
    fan_id = int(callback.data.split("_")[2]); user_id = callback.from_user.id
    unanswered_questions_query = "SELECT s.* FROM Savolho s LEFT JOIN AnsweredQuestions aq ON s.id = aq.savol_id AND aq.user_telegram_id = ? WHERE s.fan_id = ? AND aq.savol_id IS NULL ORDER BY RANDOM() LIMIT ?"
    questions = db_execute(unanswered_questions_query, (user_id, fan_id, QUESTIONS_PER_TEST), fetchall=True)
    if len(questions) < QUESTIONS_PER_TEST:
        total_questions_count = db_execute("SELECT COUNT(id) FROM Savolho WHERE fan_id = ?", (fan_id,), fetchone=True)[0]
        if total_questions_count < QUESTIONS_PER_TEST: await callback.answer(f"⚠️ Барои ин фан саволҳо кифоя нест (бояд {QUESTIONS_PER_TEST} бошад).", show_alert=True); return
        await callback.answer("🎉 Шумо ҳамаи саволҳои ин фанро ҷавоб додед! Давра аз нав оғоз мешавад.", show_alert=True)
        db_execute("DELETE FROM AnsweredQuestions WHERE user_telegram_id = ? AND savol_id IN (SELECT id FROM Savolho WHERE fan_id = ?)", (user_id, fan_id))
        questions = db_execute("SELECT * FROM Savolho WHERE fan_id = ? ORDER BY RANDOM() LIMIT ?", (fan_id, QUESTIONS_PER_TEST), fetchall=True)
    await state.update_data(fan_id=fan_id, questions=questions, current_q_index=0, correct_answers=0)
    await callback.message.delete(); 
    await send_question(bot, user_id, state)
    await state.set_state(StudentStates.taking_test)
    await callback.answer()

async def send_question(bot: Bot, user_id: int, state: FSMContext):
    data = await state.get_data(); q_index = data.get('current_q_index', 0); questions = data.get('questions', [])
    if q_index >= len(questions):
        correct = data.get('correct_answers', 0); total = len(questions); incorrect = total - correct
        percent = (correct / total) * 100 if total > 0 else 0; emoji = "🎉" if percent >= 80 else "✅" if percent >= 50 else "😔"
        db_execute("INSERT INTO Natijaho (user_telegram_id, fan_id, sanai_suporidan, javobhoi_durust, javobhoi_nodurust) VALUES (?, ?, ?, ?, ?)", (user_id, data['fan_id'], date.today(), correct, incorrect))
        for q_id in [q[0] for q in questions]: db_execute("INSERT OR IGNORE INTO AnsweredQuestions (user_telegram_id, savol_id) VALUES (?, ?)", (user_id, q_id))
        
        user = db_execute("SELECT nomu_nasab FROM Korbaron WHERE telegram_id = ?", (user_id,), fetchone=True)
        await bot.send_message(user_id, f"**Тест ба анҷом расид!** {emoji}\n\n✅ **Дуруст:** {correct}\n❌ **Нодуруст:** {incorrect}\n💯 **Хол:** {percent:.0f}%", parse_mode="Markdown")
        await asyncio.sleep(1)
        await bot.send_message(user_id, f"🎓 **Кабинети шахсии {user[0]}**", reply_markup=get_student_reply_keyboard(), parse_mode="Markdown")
        
        await state.clear(); return
    
    q_data = questions[q_index]; _, _, q_text, opt_a, opt_b, opt_c, opt_d, correct_ans_char = q_data
    text = f"**Саволи {q_index + 1} аз {len(questions)}**\n\n{q_text}"
    variants = {'A': opt_a, 'B': opt_b, 'C': opt_c, 'D': opt_d}; options = list(variants.items()); random.shuffle(options)
    buttons = [[InlineKeyboardButton(text=f"{text_option}", callback_data=f"test_ans_{'True' if char == correct_ans_char else 'False'}")] for char, text_option in options]
    buttons_in_rows = [buttons[i:i + 1] for i in range(len(buttons))] # Ҳар тугма дар сатри нав
    await bot.send_message(user_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons_in_rows), parse_mode="Markdown")

@student_router.callback_query(F.data.startswith("test_ans_"), StudentStates.taking_test)
async def process_test_answer(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.message.delete(); data = await state.get_data()
    if callback.data.split("_")[2] == 'True': await state.update_data(correct_answers=data.get('correct_answers', 0) + 1)
    await callback.answer(); await state.update_data(current_q_index=data.get('current_q_index', 0) + 1)
    await send_question(bot, callback.from_user.id, state)

# --- СИСТЕМАИ КӮМАК (ДАСТГИРӢ) ---
@main_router.message(F.text == "💬 Кӯмак")
async def student_help_start(message: Message, state: FSMContext):
    await state.set_state(StudentStates.getting_support_message)
    await message.answer("💬 **Муроҷиат ба администратор**\n_Савол ё мушкилии худро нависед. Барои бекор кардан, /start-ро пахш кунед._",
                         parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())

@student_router.message(StudentStates.getting_support_message)
async def get_support_message(message: Message, state: FSMContext, bot: Bot):
    db_execute("INSERT INTO SupportTickets (user_telegram_id, user_name, message_text) VALUES (?, ?, ?)", (message.from_user.id, message.from_user.full_name, message.text))
    await message.answer("✅ **Дархости шумо фиристода шуд!**", parse_mode="Markdown", reply_markup=get_student_reply_keyboard())
    try: await bot.send_message(ADMIN_ID, f"🔔 **Дархости нави кӯмак!**\n**Аз:** {message.from_user.full_name}\n**Матн:**\n_{message.text}_", parse_mode="Markdown")
    except Exception as e: logging.error(f"Failed to send support ticket notification: {e}")
    await state.clear()

@admin_router.callback_query(F.data == "admin_support_tickets")
async def admin_support_tickets(callback: CallbackQuery):
    open_tickets = db_execute("SELECT ticket_id, user_name FROM SupportTickets WHERE status = 'open'", fetchall=True)
    if not open_tickets: await callback.answer("✅ Дархостҳои фаъол вуҷуд надоранд.", show_alert=True); return
    text = "📨 **Дархостҳои фаъоли кӯмак:**\n"; buttons = [[InlineKeyboardButton(text=f"💬 Ҷавоб додан ба {user_name}", callback_data=f"admin_reply_ticket_{ticket_id}")] for ticket_id, user_name in open_tickets]; buttons.append([back_button_admin])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
@admin_router.callback_query(F.data.startswith("admin_reply_ticket_"))
async def admin_reply_ticket_start(callback: CallbackQuery, state: FSMContext):
    ticket_id = int(callback.data.split("_")[3]); ticket_info = db_execute("SELECT user_telegram_id, user_name, message_text FROM SupportTickets WHERE ticket_id = ?", (ticket_id,), fetchone=True)
    if not ticket_info: await callback.answer("❌ Ин дархост ёфт нашуд.", show_alert=True); return
    user_id, user_name, message_text = ticket_info
    await state.update_data(reply_to_user_id=user_id, ticket_id=ticket_id); await state.set_state(AdminStates.replying_to_ticket)
    reply_prompt_text = f"✍️ **Ҷавоб ба {user_name}**\n📜 _Дархости ӯ:_\n_{message_text}_\n\n**Ҷавоби худро нависед:**"
    await callback.message.edit_text(reply_prompt_text, parse_mode="Markdown")
@admin_router.message(AdminStates.replying_to_ticket)
async def admin_send_reply(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data(); user_id = data['reply_to_user_id']; ticket_id = data['ticket_id']
    try:
        await bot.send_message(user_id, f"📩 **Ҷавоб аз администратор**\n\n_{message.text}_", parse_mode="Markdown")
        await message.answer("✅ Ҷавоби шумо фиристода шуд."); db_execute("UPDATE SupportTickets SET status = 'closed' WHERE ticket_id = ?", (ticket_id,))
    except Exception as e: await message.answer(f"❌ Хатогӣ: {e}")
    finally: await state.clear(); await message.answer("👑 **Панели Администратор**", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")

# --- ФУНКСИЯИ АСОСИИ ИҶРОКУНАНДА ---
async def set_main_menu(bot: Bot): await bot.set_my_commands([BotCommand(command='/start', description='▶️ Оғози кор / Бозгашт')])
async def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    setup_database()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(main_router); dp.include_router(admin_router); dp.include_router(student_router)
    await set_main_menu(bot); await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Бот ба кор омода аст..."); await dp.start_polling(bot)

if __name__ == '__main__':
    try: asyncio.run(main())
    except KeyboardInterrupt: logging.info("Кори бот қатъ шуд.")
import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    Message, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BotCommand
)
from aiogram.enums import ChatType
import aiosqlite

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8878224142:AAH_KpHFQiQ3zqHvvtAf2tWo7kfDX2uOwFs"  # ← ВСТАВЬТЕ СЮДА ТОКЕН

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== ПРИОРИТЕТЫ ==========
PRIORITY_KEYWORDS = {
    "sos": [
        "срочно", "asap", "urgent", "горит", "пожар", "критично",
        "critical", "немедленно", "immediately", "прямо сейчас",
        "дедлайн", "deadline", "авария", "incident"
    ],
    "important": [
        "важно", "important", "внимание", "задача", "на подумать",
        "priority", "приоритет", "нужно сделать", "надо бы",
        "не забудь", "не забыть", "todo", "туду"
    ]
}

PRIORITY_DISPLAY = {
    "sos": "🔴 СРОЧНО",
    "important": "🟡 ВАЖНО",
    "normal": "🟢 ОБЫЧНО"
}

def detect_priority(text: str) -> str:
    """Определяет приоритет сообщения по ключевым словам."""
    if not text:
        return "normal"
    
    text_lower = text.lower()
    
    for word in PRIORITY_KEYWORDS["sos"]:
        if word in text_lower:
            return "sos"
    
    for word in PRIORITY_KEYWORDS["important"]:
        if word in text_lower:
            return "important"
    
    return "normal"

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
DB_NAME = "task_mention_bot.db"

# ========== КЛАВИАТУРЫ ==========

def get_main_menu() -> ReplyKeyboardMarkup:
    """Создаёт постоянное меню с кнопками."""
    keyboard = [
        [
            KeyboardButton(text="📋 Список задач"),
            KeyboardButton(text="🔴 Срочные")
        ],
        [
            KeyboardButton(text="⭐ Избранное"),
            KeyboardButton(text="✅ Выполненные")
        ],
        [
            KeyboardButton(text="📊 Статистика"),
            KeyboardButton(text="🗑 Очистить всё")
        ],
        [
            KeyboardButton(text="🔇 Замутить чат"),
            KeyboardButton(text="❓ Помощь")
        ]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        persistent=True
    )

def get_clear_confirm_keyboard() -> InlineKeyboardMarkup:
    """Кнопки подтверждения удаления."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить всё", callback_data="clear_confirm"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="clear_cancel")
        ]
    ])

def generate_task_keyboard(mention_id: int, status: str = "new", 
                           message_link: str = None) -> InlineKeyboardMarkup:
    """Генерирует клавиатуру с кнопками управления задачей."""
    keyboard = []
    
    # Ряд 1: Действия
    row1 = []
    if status != "done":
        row1.append(InlineKeyboardButton(text="✅ Готово", callback_data=f"done_{mention_id}"))
    
    fav_text = "🌟 В избранном" if status == "favorite" else "⭐ В избранное"
    row1.append(InlineKeyboardButton(text=fav_text, callback_data=f"fav_{mention_id}"))
    keyboard.append(row1)
    
    # Ряд 2: Отложить
    if status not in ["done", "reminded"]:
        row2 = [
            InlineKeyboardButton(text="⏰ 1ч", callback_data=f"remind_{mention_id}_1h"),
            InlineKeyboardButton(text="⏰ 3ч", callback_data=f"remind_{mention_id}_3h"),
            InlineKeyboardButton(text="⏰ Завтра", callback_data=f"remind_{mention_id}_tomorrow"),
        ]
        keyboard.append(row2)
    
    # Ряд 3: Приоритет и мут
    row3 = [
        InlineKeyboardButton(text="🔴", callback_data=f"priority_{mention_id}_sos"),
        InlineKeyboardButton(text="🟡", callback_data=f"priority_{mention_id}_important"),
        InlineKeyboardButton(text="🟢", callback_data=f"priority_{mention_id}_normal"),
    ]
    
    if status != "muted":
        row3.append(InlineKeyboardButton(text="🔇", callback_data=f"mutechat_{mention_id}"))
    
    keyboard.append(row3)
    
    # Ряд 4: Ссылка
    if message_link:
        keyboard.append([InlineKeyboardButton(text="🔗 Перейти к сообщению", url=message_link)])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ========== БАЗА ДАННЫХ ==========
async def init_db():
    """Инициализация базы данных."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                tracked_username TEXT NOT NULL,
                registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mentions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                chat_id INTEGER,
                chat_title TEXT,
                from_user TEXT,
                message_id INTEGER,
                text TEXT,
                priority TEXT DEFAULT 'normal',
                status TEXT DEFAULT 'new',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS excluded_chats (
                user_id INTEGER,
                chat_id INTEGER,
                chat_title TEXT,
                excluded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, chat_id)
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                mention_id INTEGER,
                note TEXT,
                remind_at DATETIME,
                is_favorite INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (mention_id) REFERENCES mentions(id)
            )
        """)
        
        await db.commit()
        logger.info("✅ База данных инициализирована")

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def make_message_link(chat: types.Chat, message_id: int) -> str | None:
    """Создаёт прямую ссылку на сообщение."""
    if chat.type == ChatType.SUPERGROUP:
        if chat.username:
            return f"https://t.me/{chat.username}/{message_id}"
        else:
            raw_id = str(chat.id).removeprefix("-100")
            return f"https://t.me/c/{raw_id}/{message_id}"
    return None

async def is_chat_excluded(user_id: int, chat_id: int) -> bool:
    """Проверяет, исключён ли чат для пользователя."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT 1 FROM excluded_chats WHERE user_id=? AND chat_id=?",
            (user_id, chat_id)
        )
        return await cursor.fetchone() is not None

async def save_mention(user_id: int, chat_id: int, chat_title: str,
                       from_user: str, message_id: int, text: str, priority: str) -> int:
    """Сохраняет упоминание и возвращает его ID."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "INSERT INTO mentions (user_id, chat_id, chat_title, from_user, message_id, text, priority) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, chat_id, chat_title, from_user, message_id, text or "[медиа]", priority)
        )
        await db.commit()
        return cursor.lastrowid

async def get_priority_stats(user_id: int) -> dict:
    """Возвращает статистику приоритетов за 24 часа."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT priority, COUNT(*) FROM mentions "
            "WHERE user_id=? AND timestamp > datetime('now', '-1 day') "
            "GROUP BY priority",
            (user_id,)
        )
        rows = await cursor.fetchall()
        stats = {"sos": 0, "important": 0, "normal": 0}
        for priority, count in rows:
            if priority in stats:
                stats[priority] = count
        return stats

async def get_user_stats(user_id: int) -> tuple:
    """Возвращает полную статистику пользователя."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM mentions WHERE user_id=?", (user_id,)
        )
        total = (await cursor.fetchone())[0]
        
        cursor = await db.execute(
            "SELECT COUNT(*) FROM mentions WHERE user_id=? AND status='new'", (user_id,)
        )
        active = (await cursor.fetchone())[0]
        
        cursor = await db.execute(
            "SELECT COUNT(*) FROM mentions WHERE user_id=? AND status='done'", (user_id,)
        )
        done = (await cursor.fetchone())[0]
        
        return total, active, done

async def forward_mention_to_user(
    user_id: int,
    message: Message,
    forward_caption: str,
    keyboard: InlineKeyboardMarkup
):
    """Пересылает сообщение пользователю с учётом типа контента."""
    try:
        if message.photo:
            await bot.send_photo(
                chat_id=user_id,
                photo=message.photo[-1].file_id,
                caption=forward_caption,
                reply_markup=keyboard
            )
        elif message.video:
            await bot.send_video(
                chat_id=user_id,
                video=message.video.file_id,
                caption=forward_caption,
                reply_markup=keyboard
            )
        elif message.document:
            await bot.send_document(
                chat_id=user_id,
                document=message.document.file_id,
                caption=forward_caption,
                reply_markup=keyboard
            )
        elif message.voice:
            await bot.send_voice(
                chat_id=user_id,
                voice=message.voice.file_id,
                caption=forward_caption,
                reply_markup=keyboard
            )
        elif message.video_note:
            await bot.send_video_note(
                chat_id=user_id,
                video_note=message.video_note.file_id,
                reply_markup=keyboard
            )
            if forward_caption:
                await bot.send_message(
                    chat_id=user_id,
                    text=forward_caption,
                    reply_markup=keyboard
                )
        elif message.audio:
            await bot.send_audio(
                chat_id=user_id,
                audio=message.audio.file_id,
                caption=forward_caption,
                reply_markup=keyboard
            )
        elif message.sticker:
            await bot.send_sticker(
                chat_id=user_id,
                sticker=message.sticker.file_id,
                reply_markup=keyboard
            )
            if forward_caption:
                await bot.send_message(
                    chat_id=user_id,
                    text=forward_caption,
                    reply_markup=keyboard
                )
        elif message.animation:
            await bot.send_animation(
                chat_id=user_id,
                animation=message.animation.file_id,
                caption=forward_caption,
                reply_markup=keyboard
            )
        else:
            await bot.send_message(
                chat_id=user_id,
                text=forward_caption,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        
        logger.info(f"✅ Сообщение переслано пользователю {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка пересылки: {e}")
        try:
            await message.copy_to(
                chat_id=user_id,
                caption=forward_caption,
                reply_markup=keyboard
            )
        except:
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=f"{forward_caption}\n\n⚠️ Не удалось переслать медиа",
                    reply_markup=keyboard
                )
            except:
                pass

# ========== КОМАНДЫ БОТА ==========
@dp.message(Command("start"), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: Message):
    """Приветственное сообщение с меню."""
    await message.answer(
        "👋 **Добро пожаловать в TaskMentionBot!**\n\n"
        "Я собираю все упоминания о вас из групп в этот чат.\n"
        "Каждое упоминание становится задачей с приоритетом.\n\n"
        "🎯 **Используйте кнопки меню** для управления:\n"
        "📋 Список задач — все активные задачи\n"
        "🔴 Срочные — только срочные\n"
        "⭐ Избранное — важные для вас\n"
        "✅ Выполненные — завершённые\n"
        "📊 Статистика — аналитика\n"
        "🗑 Очистить всё — удалить все задачи\n\n"
        "⚡️ **Начните:** /setme @ваш_username",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )

@dp.message(Command("setme"), F.chat.type == ChatType.PRIVATE)
async def cmd_setme(message: Message):
    """Регистрация пользователя."""
    args = message.text.split()
    if len(args) != 2 or not args[1].startswith("@"):
        await message.answer(
            "❌ Использование: /setme @твой_username\nПример: /setme @ivan",
            reply_markup=get_main_menu()
        )
        return

    username = args[1].lstrip("@").lower()
    user_id = message.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (user_id, tracked_username) VALUES (?, ?)",
            (user_id, username)
        )
        await db.commit()

    await message.answer(
        f"✅ **Отлично!** Теперь я отслеживаю упоминания @{username}\n\n"
        f"📌 Добавьте меня в группы, где вас упоминают.\n"
        f"Используйте кнопки меню для навигации! 📋",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )

@dp.message(Command("stop"), F.chat.type == ChatType.PRIVATE)
async def cmd_stop(message: Message):
    """Удаление данных пользователя."""
    user_id = message.from_user.id
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить всё", callback_data=f"confirm_stop_{user_id}")],
        [InlineKeyboardButton(text="❌ Нет, оставить", callback_data="cancel_stop")]
    ])
    
    await message.answer(
        "⚠️ **Вы уверены?**\n\nБудут удалены все ваши данные.\nЭто действие нельзя отменить.",
        reply_markup=kb,
        parse_mode="Markdown"
    )

# ========== ЕДИНЫЙ ОБРАБОТЧИК КНОПОК МЕНЮ ==========
@dp.message(F.text.in_([
    "📋 Список задач", "🔴 Срочные", "⭐ Избранное", 
    "✅ Выполненные", "📊 Статистика", "🗑 Очистить всё",
    "🔇 Замутить чат", "❓ Помощь"
]))
async def handle_menu_buttons(message: Message):
    """Единый обработчик для всех кнопок меню."""
    user_id = message.from_user.id
    text = message.text
    
    logger.info(f"👆 Нажата кнопка: {text} пользователем {user_id}")
    
    # Проверяем регистрацию для кнопок, требующих данных
    needs_registration = [
        "📋 Список задач", "🔴 Срочные", "⭐ Избранное", 
        "✅ Выполненные", "📊 Статистика", "🗑 Очистить всё"
    ]
    
    if text in needs_registration:
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT tracked_username FROM users WHERE user_id=?", (user_id,))
            if not await cursor.fetchone():
                await message.answer(
                    "❌ Сначала зарегистрируйтесь: /setme @ваш_ник",
                    reply_markup=get_main_menu()
                )
                return
    
    # Маршрутизация по кнопкам
    if text == "📋 Список задач":
        await show_tasks_list(message)
    elif text == "🔴 Срочные":
        await show_urgent_tasks(message)
    elif text == "⭐ Избранное":
        await show_favorites(message)
    elif text == "✅ Выполненные":
        await show_completed(message)
    elif text == "📊 Статистика":
        await show_stats(message)
    elif text == "🗑 Очистить всё":
        await confirm_clear(message)
    elif text == "🔇 Замутить чат":
        await mute_menu(message)
    elif text == "❓ Помощь":
        await show_help(message)

# ========== ФУНКЦИИ ДЛЯ КНОПОК ==========
async def show_tasks_list(message: Message):
    """Показывает список задач."""
    user_id = message.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT chat_title, from_user, text, priority, timestamp "
            "FROM mentions WHERE user_id=? AND status='new' "
            "ORDER BY CASE priority WHEN 'sos' THEN 1 WHEN 'important' THEN 2 ELSE 3 END, "
            "timestamp DESC LIMIT 15",
            (user_id,)
        )
        rows = await cursor.fetchall()
        
        if not rows:
            await message.answer("📭 Нет активных задач!", reply_markup=get_main_menu())
            return
        
        sos = [r for r in rows if r[3] == "sos"]
        imp = [r for r in rows if r[3] == "important"]
        nor = [r for r in rows if r[3] == "normal"]
        
        reply = "📋 **СПИСОК ЗАДАЧ**\n\n"
        
        if sos:
            reply += f"🔴 СРОЧНЫЕ ({len(sos)}):\n"
            for r in sos[:5]:
                time_str = datetime.fromisoformat(r[4]).strftime("%d.%m %H:%M")
                reply += f"🕒 {time_str} | 👤 {r[1]}: {r[2][:80]}\n"
            reply += "\n"
        
        if imp:
            reply += f"🟡 ВАЖНЫЕ ({len(imp)}):\n"
            for r in imp[:5]:
                time_str = datetime.fromisoformat(r[4]).strftime("%d.%m %H:%M")
                reply += f"🕒 {time_str} | 👤 {r[1]}: {r[2][:80]}\n"
            reply += "\n"
        
        if nor:
            reply += f"🟢 ОБЫЧНЫЕ ({len(nor)}):\n"
            for r in nor[:5]:
                time_str = datetime.fromisoformat(r[4]).strftime("%d.%m %H:%M")
                reply += f"🕒 {time_str} | 👤 {r[1]}: {r[2][:80]}\n"
        
        stats = await get_priority_stats(user_id)
        reply += f"\n📊 За 24ч: 🔴{stats['sos']} 🟡{stats['important']} 🟢{stats['normal']}"
        
        await message.answer(reply, reply_markup=get_main_menu(), parse_mode="Markdown")

async def show_urgent_tasks(message: Message):
    """Показывает срочные задачи."""
    user_id = message.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT chat_title, from_user, text, timestamp FROM mentions "
            "WHERE user_id=? AND priority='sos' AND status='new' "
            "ORDER BY timestamp DESC LIMIT 10",
            (user_id,)
        )
        rows = await cursor.fetchall()
        
        if not rows:
            await message.answer("✅ Нет срочных задач! Всё под контролем 👍", reply_markup=get_main_menu())
            return
        
        reply = "🔴 **СРОЧНЫЕ ЗАДАЧИ:**\n\n"
        for r in rows:
            time_str = datetime.fromisoformat(r[3]).strftime("%d.%m %H:%M")
            reply += f"🕒 {time_str} | 📁 {r[0]}\n👤 {r[1]}: {r[2][:200]}\n\n"
        
        await message.answer(reply, reply_markup=get_main_menu(), parse_mode="Markdown")

async def show_favorites(message: Message):
    """Показывает избранное."""
    user_id = message.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT m.chat_title, m.from_user, m.text, m.priority, m.timestamp "
            "FROM mentions m JOIN user_tasks ut ON m.id = ut.mention_id "
            "WHERE ut.user_id=? AND ut.is_favorite=1 AND m.status='new' "
            "ORDER BY m.timestamp DESC",
            (user_id,)
        )
        rows = await cursor.fetchall()
        
        if not rows:
            await message.answer("⭐ Нет избранных задач.", reply_markup=get_main_menu())
            return
        
        reply = "⭐ **ИЗБРАННОЕ:**\n\n"
        for r in rows:
            time_str = datetime.fromisoformat(r[4]).strftime("%d.%m %H:%M")
            icon = {"sos": "🔴", "important": "🟡", "normal": "🟢"}.get(r[3], "⚪")
            reply += f"{icon} {time_str} | 👤 {r[1]}: {r[2][:100]}\n\n"
        
        await message.answer(reply, reply_markup=get_main_menu(), parse_mode="Markdown")

async def show_completed(message: Message):
    """Показывает выполненные задачи."""
    user_id = message.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT chat_title, from_user, text, timestamp FROM mentions "
            "WHERE user_id=? AND status='done' "
            "ORDER BY timestamp DESC LIMIT 10",
            (user_id,)
        )
        rows = await cursor.fetchall()
        
        if not rows:
            await message.answer("📭 Нет выполненных задач.", reply_markup=get_main_menu())
            return
        
        reply = "✅ **ВЫПОЛНЕННЫЕ:**\n\n"
        for r in rows:
            time_str = datetime.fromisoformat(r[3]).strftime("%d.%m %H:%M")
            reply += f"🕒 {time_str} | 👤 {r[1]}: {r[2][:100]}\n\n"
        
        await message.answer(reply, reply_markup=get_main_menu(), parse_mode="Markdown")

async def show_stats(message: Message):
    """Показывает статистику."""
    user_id = message.from_user.id
    
    stats_24h = await get_priority_stats(user_id)
    total, active, done = await get_user_stats(user_id)
    
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT chat_title, COUNT(*) FROM mentions "
            "WHERE user_id=? GROUP BY chat_title ORDER BY COUNT(*) DESC LIMIT 5",
            (user_id,)
        )
        chats = await cursor.fetchall()
    
    reply = (
        f"📊 **СТАТИСТИКА**\n\n"
        f"За 24ч: 🔴{stats_24h['sos']} 🟡{stats_24h['important']} 🟢{stats_24h['normal']}\n"
        f"Всего: {total} | Активных: {active} | Выполнено: {done}\n\n"
    )
    
    if chats:
        reply += "**Топ-5 чатов:**\n"
        for chat, cnt in chats:
            reply += f"📁 {chat}: {cnt}\n"
    
    await message.answer(reply, reply_markup=get_main_menu(), parse_mode="Markdown")

async def confirm_clear(message: Message):
    """Подтверждение очистки."""
    user_id = message.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM mentions WHERE user_id=? AND status='new'", (user_id,)
        )
        count = (await cursor.fetchone())[0]
    
    if count == 0:
        await message.answer("📭 Нет задач для удаления.", reply_markup=get_main_menu())
        return
    
    await message.answer(
        f"⚠️ Удалить **{count}** задач?\nЭто действие нельзя отменить!",
        reply_markup=get_clear_confirm_keyboard(),
        parse_mode="Markdown"
    )

async def mute_menu(message: Message):
    """Меню мута."""
    await message.answer(
        "🔇 Используйте кнопку 🔇 под уведомлением, чтобы замутить конкретный чат.",
        reply_markup=get_main_menu()
    )

async def show_help(message: Message):
    """Показывает справку."""
    help_text = (
        "🤖 **Справка**\n\n"
        "**Кнопки под задачами:**\n"
        "✅ — выполнить задачу\n"
        "⭐ — добавить в избранное\n"
        "⏰ 1ч/3ч/Завтра — отложить\n"
        "🔴🟡🟢 — изменить приоритет\n"
        "🔇 — замутить чат\n"
        "🔗 — перейти к сообщению\n\n"
        "**Команды:**\n"
        "/setme @ник — регистрация\n"
        "/stop — удалить данные\n"
        "/mute_chat — замутить чат (в группе)\n"
        "/unmute_chat — размутить (в группе)"
    )
    await message.answer(help_text, reply_markup=get_main_menu(), parse_mode="Markdown")

# ========== CALLBACK ОБРАБОТЧИКИ ==========
@dp.callback_query(F.data == "clear_confirm")
async def process_clear_confirm(callback: CallbackQuery):
    """Подтверждение очистки всех задач."""
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "UPDATE mentions SET status='done' WHERE user_id=? AND status='new'",
            (user_id,)
        )
        count = cursor.rowcount
        await db.commit()
    
    await callback.message.edit_text(
        f"🗑 **Очищено!** {count} задач отмечены как выполненные.",
        parse_mode="Markdown"
    )
    await callback.answer(f"Удалено {count} задач")

@dp.callback_query(F.data == "clear_cancel")
async def process_clear_cancel(callback: CallbackQuery):
    """Отмена очистки."""
    await callback.message.edit_text("✅ Очистка отменена.")
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_stop_"))
async def process_stop_confirm(callback: CallbackQuery):
    """Подтверждение удаления данных."""
    user_id = int(callback.data.split("_")[2])
    
    if callback.from_user.id != user_id:
        await callback.answer("❌ Это не ваша кнопка!")
        return
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        await db.execute("DELETE FROM mentions WHERE user_id=?", (user_id,))
        await db.execute("DELETE FROM excluded_chats WHERE user_id=?", (user_id,))
        await db.execute("DELETE FROM user_tasks WHERE user_id=?", (user_id,))
        await db.commit()
    
    await callback.message.edit_text("🛑 Все данные удалены. Для нового старта: /setme @ник")
    await callback.answer("Данные удалены")

@dp.callback_query(F.data == "cancel_stop")
async def process_stop_cancel(callback: CallbackQuery):
    """Отмена удаления."""
    await callback.message.edit_text("✅ Удаление отменено.")
    await callback.answer()

@dp.callback_query(F.data.startswith("done_"))
async def process_done(callback: CallbackQuery):
    """Отмечает задачу как выполненную."""
    mention_id = int(callback.data.split("_")[1])
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE mentions SET status='done' WHERE id=?", (mention_id,))
        await db.commit()
    
    try:
        if callback.message.text:
            text = callback.message.text or ""
            for display in PRIORITY_DISPLAY.values():
                text = text.replace(f"{display}\n", "")
            await callback.message.edit_text(f"✅ {text}", reply_markup=None)
        elif callback.message.caption:
            caption = callback.message.caption or ""
            for display in PRIORITY_DISPLAY.values():
                caption = caption.replace(f"{display}\n", "")
            await callback.message.edit_caption(caption=f"✅ {caption}", reply_markup=None)
    except Exception as e:
        logger.error(f"Ошибка обновления: {e}")
    
    await callback.answer("✅ Задача выполнена!")

@dp.callback_query(F.data.startswith("fav_"))
async def process_favorite(callback: CallbackQuery):
    """Добавляет/убирает из избранного."""
    mention_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT is_favorite FROM user_tasks WHERE user_id=? AND mention_id=?",
            (user_id, mention_id)
        )
        row = await cursor.fetchone()
        
        if row and row[0] == 1:
            await db.execute(
                "UPDATE user_tasks SET is_favorite=0 WHERE user_id=? AND mention_id=?",
                (user_id, mention_id)
            )
            await callback.answer("⭐ Убрано из избранного")
            status = "new"
        else:
            await db.execute(
                "INSERT OR REPLACE INTO user_tasks (user_id, mention_id, is_favorite) VALUES (?, ?, 1)",
                (user_id, mention_id)
            )
            await callback.answer("⭐ Добавлено в избранное!")
            status = "favorite"
        await db.commit()
    
    message_link = None
    if callback.message.reply_markup:
        for row in callback.message.reply_markup.inline_keyboard:
            for btn in row:
                if btn.url:
                    message_link = btn.url
                    break
    
    new_kb = generate_task_keyboard(mention_id, status, message_link)
    try:
        await callback.message.edit_reply_markup(reply_markup=new_kb)
    except:
        pass

@dp.callback_query(F.data.startswith("remind_"))
async def process_remind(callback: CallbackQuery):
    """Устанавливает напоминание."""
    parts = callback.data.split("_")
    mention_id = int(parts[1])
    remind_in = parts[2]
    
    now = datetime.now()
    if remind_in == "1h":
        remind_at = now + timedelta(hours=1)
        time_text = "через 1 час"
    elif remind_in == "3h":
        remind_at = now + timedelta(hours=3)
        time_text = "через 3 часа"
    elif remind_in == "tomorrow":
        remind_at = now + timedelta(days=1)
        time_text = "завтра"
    else:
        await callback.answer("Неизвестное время")
        return
    
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO user_tasks (user_id, mention_id, remind_at) VALUES (?, ?, ?)",
            (user_id, mention_id, remind_at.isoformat())
        )
        await db.commit()
    
    await callback.answer(f"⏰ Напомню {time_text}")
    
    message_link = None
    if callback.message.reply_markup:
        for row in callback.message.reply_markup.inline_keyboard:
            for btn in row:
                if btn.url:
                    message_link = btn.url
                    break
    
    new_kb = generate_task_keyboard(mention_id, "reminded", message_link)
    try:
        await callback.message.edit_reply_markup(reply_markup=new_kb)
    except:
        pass

@dp.callback_query(F.data.startswith("mutechat_"))
async def process_mute_chat_callback(callback: CallbackQuery):
    """Мутит чат через кнопку."""
    mention_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT chat_id, chat_title FROM mentions WHERE id=? AND user_id=?",
            (mention_id, user_id)
        )
        row = await cursor.fetchone()
        if not row:
            await callback.answer("Ошибка: чат не найден")
            return
        
        chat_id, chat_title = row
        
        await db.execute(
            "INSERT OR IGNORE INTO excluded_chats (user_id, chat_id, chat_title) VALUES (?, ?, ?)",
            (user_id, chat_id, chat_title)
        )
        await db.commit()
    
    await callback.answer(f"🔇 Чат '{chat_title}' замьючен")
    
    message_link = None
    if callback.message.reply_markup:
        for row in callback.message.reply_markup.inline_keyboard:
            for btn in row:
                if btn.url:
                    message_link = btn.url
                    break
    
    new_kb = generate_task_keyboard(mention_id, "muted", message_link)
    try:
        await callback.message.edit_reply_markup(reply_markup=new_kb)
    except:
        pass

@dp.callback_query(F.data.startswith("priority_"))
async def process_change_priority(callback: CallbackQuery):
    """Изменяет приоритет задачи."""
    parts = callback.data.split("_")
    mention_id = int(parts[1])
    new_priority = parts[2]
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE mentions SET priority=? WHERE id=?",
            (new_priority, mention_id)
        )
        await db.commit()
    
    priority_names = {"sos": "🔴 СРОЧНО", "important": "🟡 ВАЖНО", "normal": "🟢 ОБЫЧНО"}
    await callback.answer(f"Изменён на {priority_names.get(new_priority, new_priority)}")
    
    text = callback.message.text or callback.message.caption or ""
    for key, display in PRIORITY_DISPLAY.items():
        text = text.replace(f"{display}\n", "")
    
    new_text = f"{priority_names.get(new_priority, '')}\n{text.strip()}"
    
    message_link = None
    if callback.message.reply_markup:
        for row in callback.message.reply_markup.inline_keyboard:
            for btn in row:
                if btn.url:
                    message_link = btn.url
                    break
    
    new_kb = generate_task_keyboard(mention_id, "new", message_link)
    
    try:
        if callback.message.text:
            await callback.message.edit_text(new_text, reply_markup=new_kb)
        elif callback.message.caption:
            await callback.message.edit_caption(caption=new_text, reply_markup=new_kb)
    except Exception as e:
        logger.error(f"Ошибка обновления: {e}")

# ========== КОМАНДЫ ДЛЯ ГРУПП ==========
@dp.message(Command("mute_chat"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def cmd_mute_chat(message: Message):
    """Отключает уведомления из чата."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    chat_title = message.chat.title or "чат"

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        if not await cursor.fetchone():
            await message.answer("❌ Сначала зарегистрируйтесь в ЛС: /setme @ваш_ник")
            return

        await db.execute(
            "INSERT OR IGNORE INTO excluded_chats (user_id, chat_id, chat_title) VALUES (?, ?, ?)",
            (user_id, chat_id, chat_title)
        )
        await db.commit()
    
    await message.answer("🔇 Уведомления из этого чата отключены. /unmute_chat чтобы вернуть.")

@dp.message(Command("unmute_chat"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def cmd_unmute_chat(message: Message):
    """Включает уведомления обратно."""
    user_id = message.from_user.id
    chat_id = message.chat.id

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "DELETE FROM excluded_chats WHERE user_id=? AND chat_id=?",
            (user_id, chat_id)
        )
        await db.commit()
    
    await message.answer("🔊 Уведомления из этого чата снова включены.")

# ========== ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ В ГРУППАХ ==========
@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def handle_group_messages(message: Message):
    """Обрабатывает сообщения в группах и пересылает упоминания."""
    
    if message.from_user and message.from_user.is_bot:
        return
    
    mentioned_usernames = set()
    
    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                username = entity.extract_from(message.text or "").lstrip("@").lower()
                if username:
                    mentioned_usernames.add(username)
            elif entity.type == "text_mention":
                if entity.user and entity.user.username:
                    mentioned_usernames.add(entity.user.username.lower())
    
    if message.caption_entities:
        for entity in message.caption_entities:
            if entity.type == "mention":
                username = entity.extract_from(message.caption or "").lstrip("@").lower()
                if username:
                    mentioned_usernames.add(username)
            elif entity.type == "text_mention":
                if entity.user and entity.user.username:
                    mentioned_usernames.add(entity.user.username.lower())
    
    if not mentioned_usernames:
        return
    
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id, tracked_username FROM users")
        tracked_users = await cursor.fetchall()
    
    if not tracked_users:
        return
    
    msg_time = message.date.strftime("%d.%m.%Y %H:%M")
    chat_title = message.chat.title or "личный чат"
    sender = message.from_user.full_name if message.from_user else "Неизвестный"
    
    text_content = message.text or message.caption or ""
    priority = detect_priority(text_content)
    priority_display = PRIORITY_DISPLAY[priority]
    
    content_type = "📝 Текст"
    if message.photo:
        content_type = "🖼 Фото"
    elif message.video:
        content_type = "🎬 Видео"
    elif message.document:
        doc_name = message.document.file_name or "файл"
        content_type = f"📎 Документ: {doc_name}"
    elif message.voice:
        content_type = "🎤 Голосовое"
    elif message.video_note:
        content_type = "🔵 Видео-кружок"
    elif message.audio:
        content_type = "🎵 Аудио"
    elif message.sticker:
        content_type = "😊 Стикер"
    
    message_link = make_message_link(message.chat, message.message_id)
    
    for user_id, tracked_username in tracked_users:
        if tracked_username not in mentioned_usernames:
            continue
        
        if message.from_user and message.from_user.username:
            if message.from_user.username.lower() == tracked_username:
                continue
        
        if await is_chat_excluded(user_id, message.chat.id):
            continue
        
        forward_caption = (
            f"{priority_display}\n"
            f"🔔 Упоминание в чате **{chat_title}**\n"
            f"👤 От: {sender}\n"
            f"🕒 {msg_time}\n"
            f"📦 Тип: {content_type}\n"
        )
        
        if text_content and text_content.strip():
            forward_caption += f"💬 {text_content[:300]}"
        
        mention_id = await save_mention(
            user_id=user_id,
            chat_id=message.chat.id,
            chat_title=chat_title,
            from_user=sender,
            message_id=message.message_id,
            text=text_content[:500] if text_content else f"[{content_type}]",
            priority=priority
        )
        
        keyboard = generate_task_keyboard(mention_id, "new", message_link)
        
        await forward_mention_to_user(
            user_id=user_id,
            message=message,
            forward_caption=forward_caption,
            keyboard=keyboard
        )
        
        await asyncio.sleep(0.1)

# ========== ЗАПУСК ==========
async def main():
    """Точка входа."""
    await init_db()
    
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать работу"),
        BotCommand(command="setme", description="Зарегистрироваться (@username)"),
        BotCommand(command="stop", description="Удалить все данные"),
    ])
    
    logger.info("🤖 Бот запущен и готов к работе!")
    
    while True:
        try:
            await dp.start_polling(bot)
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            logger.info("🔄 Перезапуск через 5 секунд...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())

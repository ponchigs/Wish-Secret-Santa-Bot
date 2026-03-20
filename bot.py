import json
import random
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# ===== НАСТРОЙКИ =====
TOKEN = "TOKEN"  # Ваш токен
DATA_FILE = "santa_data.json"

# ===== ЗАГРУЗКА И СОХРАНЕНИЕ ДАННЫХ =====
def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {"games": {}, "user_chats": {}, "users": {}}
            return json.loads(content)
    except FileNotFoundError:
        return {"games": {}, "user_chats": {}, "users": {}}
    except json.JSONDecodeError:
        return {"games": {}, "user_chats": {}, "users": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def is_admin(user_id, chat_id, data):
    game = data["games"].get(str(chat_id))
    return game and game["admin"] == str(user_id)

def get_user_display_name(user_id, data):
    """Возвращает отображаемое имя: сначала сохранённое вручную, потом username, потом first_name, иначе ID"""
    user_id = str(user_id)
    user_info = data.get("users", {}).get(user_id, {})
    
    # 1. Если пользователь вручную указал имя при пожелании
    if user_info.get("display_name"):
        return user_info["display_name"]
    
    # 2. Если есть username в Telegram
    if user_info.get("username"):
        return f"@{user_info['username']}"
    
    # 3. Если есть first_name
    if user_info.get("first_name"):
        return user_info["first_name"]
    
    # 4. Иначе ID
    return f"ID: {user_id}"

def update_user_info(user, data):
    """Сохраняет базовую информацию из Telegram"""
    user_id = str(user.id)
    if "users" not in data:
        data["users"] = {}
    if user_id not in data["users"]:
        data["users"][user_id] = {}
    
    # Обновляем только то, что пришло от Telegram (не затираем display_name)
    data["users"][user_id]["username"] = user.username
    data["users"][user_id]["first_name"] = user.first_name
    data["users"][user_id]["last_name"] = user.last_name
    return data

def parse_wish_input(text):
    """
    Пытается распарсить введённый текст на имя и пожелание.
    Ожидается формат "Имя: пожелание". Если двоеточия нет, возвращает (None, text).
    """
    parts = text.split(':', 1)
    if len(parts) == 2 and parts[0].strip():
        name = parts[0].strip()
        wish = parts[1].strip()
        return name, wish
    return None, text

# ===== КОМАНДЫ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветствие и сохранение chat_id и информации о пользователе"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    data = load_data()
    data = update_user_info(user, data)
    if "user_chats" not in data:
        data["user_chats"] = {}
    data["user_chats"][str(user.id)] = chat_id
    save_data(data)
    
    await update.message.reply_text(
        "🎅 Привет! Я бот для игры «Тайный Санта».\n\n"
        "Добавьте меня в группу и сделайте администратором, чтобы создавать игры.\n"
        "Команды:\n"
        "/new_game – создать игру (в группе)\n"
        "/join – участвовать в игре\n"
        "/set_wish – указать пожелание (можно сразу с именем: Имя: пожелание)\n"
        "/status – статус игры\n"
        "/ask_question – анонимно спросить своего Санту"
    )

async def new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание новой игры (только в группе)"""
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        await update.message.reply_text("❌ Эту команду нужно использовать в группе.")
        return
    
    data = load_data()
    chat_id = str(chat.id)
    
    if chat_id in data["games"]:
        await update.message.reply_text("❌ В этом чате уже есть активная игра.")
        return
    
    data = update_user_info(user, data)
    
    data["games"][chat_id] = {
        "admin": str(user.id),
        "participants": [],
        "wishes": {},
        "assignments": {},
        "status": "registration",
        "budget": None,
        "deadline": None
    }
    save_data(data)
    
    admin_name = get_user_display_name(user.id, data)
    await update.message.reply_text(
        f"✅ Игра создана! Администратор: {admin_name}\n\n"
        "Теперь участники могут написать мне в личные сообщения /join, чтобы зарегистрироваться."
    )

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Регистрация в игре"""
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type != "private":
        await update.message.reply_text("❌ Для регистрации напишите мне в личные сообщения.")
        return
    
    data = load_data()
    user_id = str(user.id)
    
    data = update_user_info(user, data)
    data["user_chats"][user_id] = chat.id
    
    available_games = []
    for chat_id, game in data["games"].items():
        if game["status"] == "registration" and user_id not in game["participants"]:
            available_games.append(chat_id)
    
    if not available_games:
        await update.message.reply_text("❌ Нет игр, открытых для регистрации.")
        return
    
    if len(available_games) == 1:
        chat_id = available_games[0]
        data["games"][chat_id]["participants"].append(user_id)
        save_data(data)
        await update.message.reply_text(
            "✅ Вы зарегистрированы в игре!\n\n"
            "Теперь укажите пожелание. Если хотите, чтобы вас называли по имени, напишите в формате:\n"
            "/set_wish Ваше имя: описание подарка\n"
            "Например: /set_wish Анна: хочу книгу"
        )
    else:
        keyboard = []
        for chat_id in available_games:
            keyboard.append([InlineKeyboardButton(f"Чат {chat_id}", callback_data=f"join_{chat_id}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("В какой игре участвовать?", reply_markup=reply_markup)

async def join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора игры для join"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_id = str(user.id)
    chat_id = query.data.split("_")[1]
    
    data = load_data()
    data = update_user_info(user, data)
    data["user_chats"][user_id] = query.message.chat.id
    
    if chat_id not in data["games"]:
        await query.edit_message_text("❌ Игра уже не существует.")
        return
    
    game = data["games"][chat_id]
    if user_id in game["participants"]:
        await query.edit_message_text("❌ Вы уже участвуете в этой игре.")
        return
    
    if game["status"] != "registration":
        await query.edit_message_text("❌ Регистрация в этой игре уже закрыта.")
        return
    
    game["participants"].append(user_id)
    save_data(data)
    
    await query.edit_message_text(
        "✅ Вы зарегистрированы!\n\n"
        "Теперь укажите пожелание. Если хотите, чтобы вас называли по имени, напишите в формате:\n"
        "/set_wish Ваше имя: описание подарка\n"
        "Например: /set_wish Анна: хочу книгу"
    )

async def set_wish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка пожелания (в личке) с возможностью указать имя"""
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type != "private":
        await update.message.reply_text("❌ Напишите мне в личные сообщения.")
        return
    
    data = load_data()
    user_id = str(user.id)
    
    # Обновляем информацию из Telegram
    data = update_user_info(user, data)
    
    # Находим игры, где пользователь участвует
    user_games = []
    for chat_id, game in data["games"].items():
        if user_id in game["participants"]:
            user_games.append(chat_id)
    
    if not user_games:
        await update.message.reply_text("❌ Вы не участвуете ни в одной игре. Сначала зарегистрируйтесь через /join.")
        return
    
    if not context.args:
        # Если команда без аргументов, просим ввести пожелание
        await update.message.reply_text(
            "❌ Напишите пожелание после команды.\n"
            "Если хотите указать имя, используйте формат: /set_wish Имя: пожелание\n"
            "Например: /set_wish Анна: хочу книгу"
        )
        return
    
    input_text = " ".join(context.args)
    name, wish = parse_wish_input(input_text)
    
    # Если имя указано, сохраняем его
    if name:
        # Сохраняем display_name для этого пользователя
        if "users" not in data:
            data["users"] = {}
        if user_id not in data["users"]:
            data["users"][user_id] = {}
        data["users"][user_id]["display_name"] = name
        save_data(data)
        await update.message.reply_text(f"✅ Имя «{name}» сохранено.")
    else:
        wish = input_text
        # Если имя не указано, проверяем, есть ли уже сохранённое имя
        if user_id in data.get("users", {}) and data["users"][user_id].get("display_name"):
            name = data["users"][user_id]["display_name"]
        else:
            # Если имени нет, предлагаем указать его в следующий раз
            await update.message.reply_text(
                "ℹ️ Вы не указали имя. Чтобы вас называли по имени, используйте формат:\n"
                "/set_wish Ваше имя: пожелание\n"
                "Сейчас я сохраню только пожелание."
            )
    
    # Сохраняем пожелание для всех игр, где пользователь участвует
    # (в текущей версии поддерживаем только одну игру на пользователя, но можно доработать)
    if len(user_games) == 1:
        chat_id = user_games[0]
        data["games"][chat_id]["wishes"][user_id] = wish
        save_data(data)
        await update.message.reply_text("✅ Пожелание сохранено!")
    else:
        # Если несколько игр, предлагаем выбрать
        keyboard = []
        for chat_id in user_games:
            # Показываем только те игры, где ещё нет пожелания (или можно перезаписать)
            keyboard.append([InlineKeyboardButton(f"Чат {chat_id}", callback_data=f"wish_{chat_id}_{wish}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Для какой игры указать пожелание?", reply_markup=reply_markup)

async def wish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора игры для пожелания"""
    query = update.callback_query
    await query.answer()
    
    _, chat_id, wish = query.data.split("_", 2)
    user_id = str(query.from_user.id)
    
    data = load_data()
    if chat_id not in data["games"]:
        await query.edit_message_text("❌ Игра уже не существует.")
        return
    
    game = data["games"][chat_id]
    if user_id not in game["participants"]:
        await query.edit_message_text("❌ Вы не участвуете в этой игре.")
        return
    
    game["wishes"][user_id] = wish
    save_data(data)
    
    await query.edit_message_text("✅ Пожелание сохранено!")

async def start_draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Жеребьёвка (только админ в группе)"""
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        await update.message.reply_text("❌ Эту команду нужно использовать в группе.")
        return
    
    data = load_data()
    chat_id = str(chat.id)
    
    if chat_id not in data["games"]:
        await update.message.reply_text("❌ В этом чате нет активной игры.")
        return
    
    game = data["games"][chat_id]
    
    if not is_admin(user.id, chat_id, data):
        await update.message.reply_text("❌ Только администратор может запустить жеребьёвку.")
        return
    
    if game["status"] != "registration":
        await update.message.reply_text("❌ Жеребьёвка уже проведена.")
        return
    
    participants = game["participants"]
    if len(participants) < 2:
        await update.message.reply_text("❌ Нужно минимум 2 участника.")
        return
    
    # Проверяем, все ли указали пожелания
    missing_wishes = [uid for uid in participants if uid not in game["wishes"]]
    if missing_wishes:
        await update.message.reply_text(f"❌ Не все участники указали пожелания. Осталось: {len(missing_wishes)}")
        return
    
    # Жеребьёвка (циклический сдвиг)
    random.shuffle(participants)
    assignments = {}
    for i in range(len(participants)):
        giver = participants[i]
        receiver = participants[(i + 1) % len(participants)]
        assignments[giver] = receiver
    
    game["assignments"] = assignments
    game["status"] = "drawing"
    save_data(data)
    
    # Уведомляем каждого участника
    notified = 0
    for giver, receiver in assignments.items():
        user_chat_id = data["user_chats"].get(giver)
        if user_chat_id:
            try:
                wish = game["wishes"][receiver]
                receiver_name = get_user_display_name(receiver, data)
                await context.bot.send_message(
                    chat_id=user_chat_id,
                    text=f"🎅 Ты даришь подарок пользователю {receiver_name}.\nЕго пожелание: {wish}"
                )
                notified += 1
            except Exception as e:
                print(f"Не удалось отправить уведомление {giver}: {e}")
    
    await update.message.reply_text(
        f"✅ Жеребьёвка проведена! Уведомления отправлены {notified} из {len(participants)} участников.\n"
        "Остальные не начинали диалог со мной – напишите мне /start, чтобы получать уведомления."
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статус игры"""
    chat = update.effective_chat
    
    data = load_data()
    chat_id = str(chat.id)
    
    if chat_id not in data["games"]:
        await update.message.reply_text("❌ В этом чате нет активной игры.")
        return
    
    game = data["games"][chat_id]
    
    participants_count = len(game["participants"])
    wishes_count = len(game["wishes"])
    status_text = f"🎮 Статус игры: {game['status']}\n"
    status_text += f"👥 Участников: {participants_count}\n"
    status_text += f"🎁 Пожеланий: {wishes_count}\n"
    
    if participants_count > 0:
        status_text += "\nУчастники:\n"
        for uid in game["participants"]:
            name = get_user_display_name(uid, data)
            wish_mark = "✅" if uid in game["wishes"] else "❌"
            status_text += f" {name} {wish_mark}\n"
    
    if game.get("budget"):
        status_text += f"\n💰 Бюджет: {game['budget']}"
    if game.get("deadline"):
        status_text += f"\n⏰ Дедлайн: {game['deadline']}"
    
    await update.message.reply_text(status_text)

async def set_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка бюджета (админ)"""
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        await update.message.reply_text("❌ Эту команду нужно использовать в группе.")
        return
    
    data = load_data()
    chat_id = str(chat.id)
    
    if chat_id not in data["games"]:
        await update.message.reply_text("❌ В этом чате нет активной игры.")
        return
    
    if not is_admin(user.id, chat_id, data):
        await update.message.reply_text("❌ Только администратор может установить бюджет.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Укажите бюджет. Например: /set_budget 1000 руб.")
        return
    
    budget = " ".join(context.args)
    data["games"][chat_id]["budget"] = budget
    save_data(data)
    
    await update.message.reply_text(f"✅ Бюджет установлен: {budget}")

async def set_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка дедлайна (админ)"""
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        await update.message.reply_text("❌ Эту команду нужно использовать в группе.")
        return
    
    data = load_data()
    chat_id = str(chat.id)
    
    if chat_id not in data["games"]:
        await update.message.reply_text("❌ В этом чате нет активной игры.")
        return
    
    if not is_admin(user.id, chat_id, data):
        await update.message.reply_text("❌ Только администратор может установить дедлайн.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Укажите дедлайн. Например: /set_deadline 2025-12-31")
        return
    
    deadline = " ".join(context.args)
    data["games"][chat_id]["deadline"] = deadline
    save_data(data)
    
    await update.message.reply_text(f"✅ Дедлайн установлен: {deadline}")

async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Напоминание тем, кто не указал пожелания (админ)"""
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        await update.message.reply_text("❌ Эту команду нужно использовать в группе.")
        return
    
    data = load_data()
    chat_id = str(chat.id)
    
    if chat_id not in data["games"]:
        await update.message.reply_text("❌ В этом чате нет активной игры.")
        return
    
    if not is_admin(user.id, chat_id, data):
        await update.message.reply_text("❌ Только администратор может отправлять напоминания.")
        return
    
    game = data["games"][chat_id]
    missing_wishes = [uid for uid in game["participants"] if uid not in game["wishes"]]
    
    if not missing_wishes:
        await update.message.reply_text("✅ Все участники уже указали пожелания.")
        return
    
    reminded = 0
    for uid in missing_wishes:
        user_chat_id = data["user_chats"].get(uid)
        if user_chat_id:
            try:
                name = get_user_display_name(uid, data)
                await context.bot.send_message(
                    chat_id=user_chat_id,
                    text=f"⏰ Напоминание: вы ({name}) участвуете в игре «Тайный Санта», но ещё не указали пожелание. Используйте /set_wish (можно с именем: Имя: пожелание)."
                )
                reminded += 1
            except Exception as e:
                print(f"Не удалось отправить напоминание {uid}: {e}")
    
    await update.message.reply_text(f"✅ Напоминания отправлены {reminded} из {len(missing_wishes)} участников.")

async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Анонимный вопрос своему Санте (после жеребьёвки)"""
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type != "private":
        await update.message.reply_text("❌ Напишите мне в личные сообщения.")
        return
    
    data = load_data()
    user_id = str(user.id)
    
    data = update_user_info(user, data)
    
    # Находим игры, где пользователь является получателем
    santa_games = []
    for chat_id, game in data["games"].items():
        if game["status"] == "drawing" and user_id in game["assignments"].values():
            santa_games.append(chat_id)
    
    if not santa_games:
        await update.message.reply_text("❌ Сейчас вы не являетесь получателем ни в одной активной игре.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Напишите вопрос после команды. Например: /ask_question Какой цвет ты любишь?")
        return
    
    question = " ".join(context.args)
    
    if len(santa_games) == 1:
        chat_id = santa_games[0]
        game = data["games"][chat_id]
        # Находим Санту
        santa_id = None
        for giver, receiver in game["assignments"].items():
            if receiver == user_id:
                santa_id = giver
                break
        
        if santa_id:
            santa_chat_id = data["user_chats"].get(santa_id)
            if santa_chat_id:
                try:
                    await context.bot.send_message(
                        chat_id=santa_chat_id,
                        text=f"❓ Анонимный вопрос от того, кому ты даришь подарок:\n\n{question}"
                    )
                    await update.message.reply_text("✅ Ваш вопрос отправлен Санте!")
                except Exception:
                    await update.message.reply_text("❌ Не удалось отправить вопрос. Возможно, Санта не начинал диалог со мной.")
            else:
                await update.message.reply_text("❌ Санта ещё не общался со мной. Попросите его написать /start.")
        else:
            await update.message.reply_text("❌ Ошибка: не найден Санта.")
    else:
        keyboard = []
        for chat_id in santa_games:
            keyboard.append([InlineKeyboardButton(f"Чат {chat_id}", callback_data=f"ask_{chat_id}_{question}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("В какой игре задать вопрос?", reply_markup=reply_markup)

async def ask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора игры для вопроса"""
    query = update.callback_query
    await query.answer()
    
    _, chat_id, question = query.data.split("_", 2)
    user_id = str(query.from_user.id)
    
    data = load_data()
    if chat_id not in data["games"]:
        await query.edit_message_text("❌ Игра уже не существует.")
        return
    
    game = data["games"][chat_id]
    if user_id not in game["assignments"].values():
        await query.edit_message_text("❌ Вы не являетесь получателем в этой игре.")
        return
    
    # Находим Санту
    santa_id = None
    for giver, receiver in game["assignments"].items():
        if receiver == user_id:
            santa_id = giver
            break
    
    if santa_id:
        santa_chat_id = data["user_chats"].get(santa_id)
        if santa_chat_id:
            try:
                await context.bot.send_message(
                    chat_id=santa_chat_id,
                    text=f"❓ Анонимный вопрос от того, кому ты даришь подарок:\n\n{question}"
                )
                await query.edit_message_text("✅ Ваш вопрос отправлен Санте!")
            except Exception:
                await query.edit_message_text("❌ Не удалось отправить вопрос. Возможно, Санта не начинал диалог со мной.")
        else:
            await query.edit_message_text("❌ Санта ещё не общался со мной. Попросите его написать /start.")
    else:
        await query.edit_message_text("❌ Ошибка: не найден Санта.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка обычных сообщений (игнорируем)"""
    pass

# ===== ЗАПУСК БОТА =====
def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new_game", new_game))
    application.add_handler(CommandHandler("join", join))
    application.add_handler(CommandHandler("set_wish", set_wish))
    application.add_handler(CommandHandler("start_draw", start_draw))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("set_budget", set_budget))
    application.add_handler(CommandHandler("set_deadline", set_deadline))
    application.add_handler(CommandHandler("remind", remind))
    application.add_handler(CommandHandler("ask_question", ask_question))
    
    application.add_handler(CallbackQueryHandler(join_callback, pattern="^join_"))
    application.add_handler(CallbackQueryHandler(wish_callback, pattern="^wish_"))
    application.add_handler(CallbackQueryHandler(ask_callback, pattern="^ask_"))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()

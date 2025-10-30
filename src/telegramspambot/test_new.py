import os
import json
import threading
import time
import telebot
import asyncio
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, FloodWaitError, PersistentTimestampOutdatedError
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from telethon.tl.functions.account import UpdateProfileRequest, UpdateUsernameRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.types import PeerUser, PeerChannel
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

bot = telebot.TeleBot("1951673158:AAErUxJElgBdkQB9XxVhigPArEpLCa2HCVM")
ACCOUNTS_FILE = 'accounts.json'
CONFIGS_FILE = 'session_configs.json'
SETTINGS_FILE = 'session_settings.json'
accounts = {}
configs = {}  # session_name -> config_name -> [chat_ids]
settings = {}  # session_name -> settings
tasks = {}  # session_name -> (thread, stop_event)
states = {}  # chat_id -> state

# Default settings
DEFAULT_SETTINGS = {
    'logging': {
        'enabled': True,
        'level': 'full',  # 'full' or 'minimal'
        'show_errors': True,
        'show_success': True,
        'show_progress': True
    },
    'limits': {
        'messages_per_minute': 20,  # Telegram limit
        'messages_per_hour': 500,   # Telegram limit
        'messages_per_day': 2000,   # Telegram limit
        'delay_between_messages': 3  # Minimum delay in seconds
    },
}

# Load/save

def load_accounts():
    global accounts, configs, settings
    if os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
            accounts = json.load(f)
    if os.path.exists(CONFIGS_FILE):
        with open(CONFIGS_FILE, 'r', encoding='utf-8') as f:
            configs = json.load(f)
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
    
    # Ensure all sessions have complete settings
    for session in accounts:
        if session not in settings:
            settings[session] = DEFAULT_SETTINGS.copy()
        else:
            # Merge with default settings to ensure all keys exist
            for category, default_values in DEFAULT_SETTINGS.items():
                if category not in settings[session]:
                    settings[session][category] = default_values.copy()
                else:
                    # Merge individual settings within category
                    for key, default_value in default_values.items():
                        if key not in settings[session][category]:
                            settings[session][category][key] = default_value
        
        # Ensure all sessions have a configs entry
        if session not in configs:
            configs[session] = {}

def save_accounts():
    global accounts, configs, settings
    with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)
    with open(CONFIGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(configs, f, indent=2, ensure_ascii=False)
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)

# Session refresh

async def refresh_session(account_name, chat_id):
    """Обновляет сессию аккаунта"""
    acc = accounts[account_name]
    client = TelegramClient(
        StringSession(),
        acc['api_id'],
        acc['api_hash'],
        device_model="iPhone 13 Pro Max",
        system_version="4.16.30-vxCUSTOM",
        app_version="8.4",
        lang_code="en",
        system_lang_code="en-US"
    )
    
    try:
        await client.connect()
        if not await client.is_user_authorized():
            bot.send_message(chat_id, '❌ Сессия устарела. Требуется повторная авторизация.')
            bot.send_message(chat_id, 'Введите номер телефона (+...):')
            states[chat_id] = {
                'step': 'refresh_phone',
                'account': account_name,
                'api_id': acc['api_id'],
                'api_hash': acc['api_hash']
            }
            return False
        return True
    except Exception as e:
        bot.send_message(chat_id, f'❌ Ошибка при проверке сессии: {str(e)}')
        return False
    finally:
        await client.disconnect()

# Broadcast worker

def broadcast_worker(name, chats, message, delay_msg, delay_iter, stop_event, chat_id):
    async def run():
        acc = accounts[name]
        client = TelegramClient(
            StringSession(acc['string_session']),
            acc['api_id'], acc['api_hash'],
            device_model="iPhone 13 Pro Max",
            system_version="4.16.30-vxCUSTOM",
            app_version="8.4",
            lang_code="en",
            system_lang_code="en-US"
        )
        await client.start()
        try:
            # Получаем все диалоги для кэширования сущностей
            log_message(chat_id, name, "⏳ Получаю информацию о чатах...", 'progress')
            try:
                await client.get_dialogs()
                log_message(chat_id, name, "✅ Информация о чатах получена", 'success')
            except PersistentTimestampOutdatedError:
                log_message(chat_id, name, "⚠️ Ошибка синхронизации при получении диалогов", 'progress')
                recovery_success = await handle_persistent_timestamp_error(client, chat_id, name, "получение диалогов")
                if not recovery_success:
                    log_message(chat_id, name, "❌ Не удалось восстановить синхронизацию. Останавливаю рассылку.", 'error')
                    return
                # Повторная попытка получения диалогов
                try:
                    await client.get_dialogs()
                    log_message(chat_id, name, "✅ Информация о чатах получена после восстановления", 'success')
                except Exception as e:
                    log_message(chat_id, name, f"❌ Не удалось получить диалоги: {str(e)}", 'error')
                    return

            messages_sent = 0
            start_time = time.time()
            last_message_time = 0
            last_check_time = 0
            
            while not stop_event.is_set():
                
                for target in chats:
                    if stop_event.is_set():
                        break
                    
                    # Проверяем лимиты
                    current_time = time.time()
                    time_since_last = current_time - last_message_time
                    min_delay = settings[name]['limits']['delay_between_messages']
                    
                    if time_since_last < min_delay:
                        await asyncio.sleep(min_delay - time_since_last)
                    
                    try:
                        # Преобразуем ID в правильный формат
                        original_target = target  # Сохраняем оригинальный формат
                        
                        # Получаем информацию о чате
                        try:
                            if isinstance(target, str):
                                if target.startswith('-100'):
                                    # Для групп и каналов с полным ID
                                    target_id = int(target[4:])
                                    entity = await client.get_entity(PeerChannel(target_id))
                                elif target.startswith('-'):
                                    # Для групп и каналов с коротким ID
                                    target_id = int(target[1:])
                                    entity = await client.get_entity(PeerChannel(target_id))
                                elif target.startswith('+'):
                                    # Для приватных ссылок-приглашений
                                    invite_hash = target[1:]  # Убираем +
                                    entity = await client.get_entity(invite_hash)
                                elif target.isdigit():
                                    # Для числовых ID пользователей
                                    target_id = int(target)
                                    entity = await client.get_entity(PeerUser(target_id))
                                else:
                                    # Для username
                                    entity = await client.get_entity(target)
                            else:
                                # Если target уже число
                                if target > 0:
                                    # Для пользователей
                                    entity = await client.get_entity(PeerUser(target))
                                else:
                                    # Для групп и каналов
                                    entity = await client.get_entity(PeerChannel(abs(target)))
                            
                            # Отправляем сообщение
                            sent_message = await client.send_message(entity, message)
                            messages_sent += 1
                            last_message_time = time.time()
                            
                            
                            log_message(chat_id, name, f"✅ Сообщение отправлено в {original_target}", 'success')
                            
                            # Проверяем лимиты
                            if messages_sent >= settings[name]['limits']['messages_per_minute']:
                                log_message(chat_id, name, "⏳ Достигнут лимит сообщений в минуту. Ожидание...", 'progress')
                                await asyncio.sleep(60)
                                messages_sent = 0
                            
                        except PersistentTimestampOutdatedError:
                            # Обрабатываем ошибку синхронизации
                            log_message(chat_id, name, f"⚠️ Ошибка синхронизации при отправке в {original_target}", 'progress')
                            recovery_success = await handle_persistent_timestamp_error(client, chat_id, name, f"отправка в {original_target}")
                            if recovery_success:
                                # Пробуем отправить сообщение снова после восстановления
                                try:
                                    sent_message = await client.send_message(entity, message)
                                    messages_sent += 1
                                    last_message_time = time.time()
                                    
                                    
                                    log_message(chat_id, name, f"✅ Сообщение отправлено в {original_target} после восстановления синхронизации", 'success')
                                except Exception as retry_error:
                                    log_message(chat_id, name, f"❌ Не удалось отправить сообщение в {original_target} после восстановления: {str(retry_error)}", 'error')
                            else:
                                log_message(chat_id, name, f"❌ Не удалось восстановить синхронизацию для {original_target}", 'error')
                            continue
                            
                        except Exception as e:
                            error_msg = str(e)
                            if "You're banned from sending messages in supergroups/channels" in error_msg:
                                log_message(chat_id, name, f"❌ Аккаунт забанен в чате {original_target}. Удаляю чат из списка...", 'error')
                                try:
                                    # Удаляем чат из списка, используя оригинальный формат
                                    if original_target in chats:
                                        chats.remove(original_target)
                                    # Если есть конфигурация, обновляем её
                                    for config_name, config_chats in configs.get(name, {}).items():
                                        if original_target in config_chats:
                                            config_chats.remove(original_target)
                                    save_accounts()
                                    log_message(chat_id, name, f"✅ Чат {original_target} удален из списка", 'success')
                                except Exception as remove_error:
                                    log_message(chat_id, name, f"❌ Ошибка при удалении чата: {str(remove_error)}", 'error')
                            else:
                                log_message(chat_id, name, f"❌ Ошибка при получении информации о чате {original_target}: {error_msg}", 'error')
                            continue
                            
                    except Exception as e:
                        log_message(chat_id, name, f"❌ Ошибка при отправке в {original_target}: {e}", 'error')
                    
                    await asyncio.sleep(delay_msg)
                await asyncio.sleep(delay_iter)
        finally:
            await client.disconnect()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run())

# Auto-subscribe worker

def auto_subscribe_worker(session_name, target_chats, message_text, delay_cycle, stop_event, chat_id):
    async def run():
        acc = accounts[session_name]
        client = TelegramClient(
            StringSession(acc['string_session']),
            acc['api_id'], acc['api_hash'],
            device_model="iPhone 13 Pro Max",
            system_version="4.16.30-vxCUSTOM",
            app_version="8.4",
            lang_code="en",
            system_lang_code="en-US"
        )
        await client.start()
        me = await client.get_me()

        def extract_urls_from_message(msg):
            urls = []
            try:
                if getattr(msg, 'reply_markup', None) and getattr(msg.reply_markup, 'rows', None):
                    for row in msg.reply_markup.rows:
                        for button in getattr(row, 'buttons', []) or []:
                            url = getattr(button, 'url', None)
                            if url:
                                urls.append(url)
            except Exception:
                pass
            return urls

        async def join_from_url(url):
            try:
                if 't.me/+' in url or 'joinchat/' in url:
                    if 't.me/+' in url:
                        invite_hash = url.split('t.me/+')[-1].split('?')[0]
                    else:
                        invite_hash = url.split('joinchat/')[-1].split('?')[0]
                    try:
                        await client(ImportChatInviteRequest(invite_hash))
                        return True
                    except Exception:
                        try:
                            await client(JoinChannelRequest(f"+{invite_hash}"))
                            return True
                        except Exception:
                            return False
                elif 't.me/' in url:
                    username = url.split('t.me/')[-1].split('?')[0]
                    await client(JoinChannelRequest(username))
                    return True
            except Exception:
                return False
            return False

        def looks_like_subscribe_prompt(text):
            if not text:
                return False
            t = text.lower()
            keywords = ['подпис', 'subscribe', 'подпишитесь', 'подписаться', 'join', 'канал', 'чат']
            return any(k in t for k in keywords)

        try:
            for target_chat in target_chats:
                if stop_event.is_set():
                    log_message(chat_id, session_name, "ℹ️ Задача остановлена пользователем.", 'progress')
                    break
                
                log_message(chat_id, session_name, f"▶️ Работаю с чатом: {target_chat}", 'progress')
                
                try:
                    if isinstance(target_chat, str):
                        if target_chat.startswith('-100'):
                            target_id = int(target_chat[4:])
                            entity = await client.get_entity(PeerChannel(target_id))
                        elif target_chat.startswith('-'):
                            target_id = int(target_chat[1:])
                            entity = await client.get_entity(PeerChannel(target_id))
                        elif target_chat.startswith('+'):
                            entity = await client.get_entity(target_chat[1:])
                        elif target_chat.isdigit():
                            target_id = int(target_chat)
                            entity = await client.get_entity(PeerUser(target_id))
                        else:
                            entity = await client.get_entity(target_chat)
                    else:
                        entity = await client.get_entity(target_chat)
                except Exception as e:
                    log_message(chat_id, session_name, f"❌ Не удалось получить чат {target_chat}: {e}", 'error')
                    continue

                try:
                    sent = await client.send_message(entity, message_text)
                    last_sent_id = sent.id
                    log_message(chat_id, session_name, f"✅ Сообщение отправлено в {target_chat}. Начинаю мониторинг…", 'success')
                except Exception as e:
                    log_message(chat_id, session_name, f"❌ Не удалось отправить сообщение в {target_chat}: {e}", 'error')
                    continue

                # Monitoring loop for the current chat
                monitoring_start_time = time.time()
                while not stop_event.is_set():
                    # Timeout for monitoring a single chat (e.g., 5 minutes)
                    if time.time() - monitoring_start_time > 300:
                        log_message(chat_id, session_name, f"⏳ Не найдено ответа в {target_chat} за 5 минут. Перехожу к следующему чату.", 'progress')
                        break

                    try:
                        msgs = await client.get_messages(entity, limit=50)
                        need_join = []
                        for m in msgs:
                            try:
                                is_reply_to_us = (getattr(m, 'reply_to_msg_id', None) == last_sent_id)
                                is_our_message = (getattr(m, 'sender_id', None) == me.id)
                                says_subscribe = looks_like_subscribe_prompt(getattr(m, 'message', '') or getattr(m, 'text', ''))
                                if is_reply_to_us or is_our_message or says_subscribe:
                                    need_join.extend(extract_urls_from_message(m))
                            except Exception:
                                continue

                        joined_any = False
                        for url in set(need_join):
                            ok = await join_from_url(url)
                            if ok:
                                joined_any = True
                                log_message(chat_id, session_name, f"✅ Успешно вступил в: {url}", 'success')
                                await asyncio.sleep(1)

                        if joined_any:
                            try:
                                await client.send_message(entity, message_text)
                                log_message(chat_id, session_name, f"✅ Подписки в {target_chat} выполнены, сообщение отправлено повторно.", 'success')
                            except Exception as e:
                                log_message(chat_id, session_name, f"❌ Ошибка при повторной отправке в {target_chat}: {e}", 'error')
                            break
                        
                        await asyncio.sleep(delay_cycle)

                    except PersistentTimestampOutdatedError:
                        recovery_success = await handle_persistent_timestamp_error(client, chat_id, session_name, f"мониторинг чата {target_chat}")
                        if not recovery_success:
                            log_message(chat_id, session_name, f"❌ Не удалось восстановить синхронизацию для {target_chat}. Пропускаю чат.", 'error')
                            break
                    except FloodWaitError as e:
                        log_message(chat_id, session_name, f"⏳ Получен FloodWait на {e.seconds} секунд. Ожидаю...", 'progress')
                        await asyncio.sleep(e.seconds)
                    except Exception as e:
                        log_message(chat_id, session_name, f"❌ Ошибка в цикле автоподписки для {target_chat}: {e}", 'error')
                        break
        finally:
            await client.disconnect()
            if tasks.pop(f"auto::{session_name}", None):
                 log_message(chat_id, session_name, f"⏹️ Задача автоподписки для {session_name} завершена.", 'success')


    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run())

# Keyboards

def main_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('➕ Добавить аккаунт'), KeyboardButton('➖ Удалить аккаунт'))
    kb.add(KeyboardButton('▶️ Запустить рассылку'), KeyboardButton('⏹️ Остановить рассылку'))
    kb.add(KeyboardButton('👤 Управление аккаунтом'), KeyboardButton('📋 Просмотр чатов'))
    kb.add(KeyboardButton('➕ Вступить в чаты'), KeyboardButton('⚙️ Настройки сессии'))
    kb.add(KeyboardButton('🤖 Автоподписка'))
    return kb

def sessions_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    for name in accounts.keys():
        kb.add(KeyboardButton(name))
    kb.add(KeyboardButton('Отмена'))
    return kb

def account_settings_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('📝 Изменить имя'), KeyboardButton('👤 Изменить username'))
    kb.add(KeyboardButton('📋 Изменить био'), KeyboardButton('🖼 Изменить аватар'))
    kb.add(KeyboardButton('Назад'))
    return kb

def chat_type_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('📢 Все каналы'), KeyboardButton('👥 Все группы'))
    kb.add(KeyboardButton('💬 Все личные чаты'), KeyboardButton('📋 Все чаты'))
    kb.add(KeyboardButton('➕ Добавить чаты вручную'), KeyboardButton('Отмена'))
    return kb

def chat_selection_keyboard(chats_info):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    for chat in chats_info:
        # Создаем кнопку с типом чата и его названием
        chat_type = chat.split(':')[0]
        chat_name = chat.split(':')[1].split('\n')[0].strip()
        button_text = f"{chat_type}: {chat_name}"
        kb.add(KeyboardButton(button_text))
    kb.add(KeyboardButton('✅ Подтвердить выбор'), KeyboardButton('Отмена'))
    return kb

def settings_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('📝 Настройки логирования'))
    kb.add(KeyboardButton('Назад'))
    return kb

def logging_settings_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('✅ Включить логирование'), KeyboardButton('❌ Отключить логирование'))
    kb.add(KeyboardButton('📋 Полное логирование'), KeyboardButton('📝 Минимальное логирование'))
    kb.add(KeyboardButton('Назад'))
    return kb


def broadcast_chats_method_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('Использовать сохраненную конфигурацию'))
    kb.add(KeyboardButton('Выбрать по типу'))
    kb.add(KeyboardButton('Ввести вручную'))
    kb.add(KeyboardButton('Отмена'))
    return kb

def configs_keyboard(session_name):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    if session_name in configs and configs[session_name]:
        for config_name in configs[session_name].keys():
            kb.add(KeyboardButton(config_name))
    kb.add(KeyboardButton('Назад'), KeyboardButton('Отмена'))
    return kb

def save_config_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('Да'), KeyboardButton('Нет'))
    kb.add(KeyboardButton('Отмена'))
    return kb


# Logging functions

def log_message(chat_id, session_name, message, level='info'):
    if session_name not in settings:
        settings[session_name] = DEFAULT_SETTINGS.copy()
    
    session_settings = settings[session_name]['logging']
    
    if not session_settings['enabled']:
        return
    
    if level == 'error' and not session_settings['show_errors']:
        return
    
    if level == 'success' and not session_settings['show_success']:
        return
    
    if level == 'progress' and not session_settings['show_progress']:
        return
    
    if session_settings['level'] == 'minimal' and level == 'progress':
        return
    
    bot.send_message(chat_id, message)




async def handle_persistent_timestamp_error(client, chat_id, session_name, operation_name="операция", max_retries=5):
    """Обрабатывает ошибку PersistentTimestampOutdatedError с улучшенной логикой восстановления"""
    for attempt in range(max_retries):
        try:
            log_message(chat_id, session_name, f"⚠️ Ошибка синхронизации Telegram при {operation_name} (попытка {attempt + 1}/{max_retries})", 'progress')
            
            # Корректно отключаемся
            try:
                await client.disconnect()
            except:
                pass
            
            # Увеличиваем время ожидания с каждой попыткой
            wait_time = 5 + attempt * 3
            log_message(chat_id, session_name, f"⏳ Ожидание {wait_time} секунд перед переподключением...", 'progress')
            await asyncio.sleep(wait_time)
            
            # Переподключаемся
            await client.connect()
            
            # Проверяем авторизацию
            if not await client.is_user_authorized():
                log_message(chat_id, session_name, f"❌ Ошибка авторизации после переподключения", 'error')
                continue
            
            # Пробуем разные способы восстановления синхронизации
            recovery_methods = [
                lambda: client.get_dialogs(),
                lambda: client.get_me(),
                lambda: client.get_entity('me')
            ]
            
            recovery_success = False
            for method in recovery_methods:
                try:
                    await method()
                    recovery_success = True
                    break
                except Exception as method_error:
                    log_message(chat_id, session_name, f"⚠️ Метод восстановления не сработал: {str(method_error)}", 'progress')
                    continue
            
            if recovery_success:
                # Дополнительная пауза для стабилизации
                await asyncio.sleep(3)
                log_message(chat_id, session_name, f"✅ Синхронизация восстановлена (попытка {attempt + 1})", 'success')
                return True
            else:
                log_message(chat_id, session_name, f"❌ Не удалось восстановить синхронизацию (попытка {attempt + 1})", 'error')
            
        except Exception as e:
            log_message(chat_id, session_name, f"❌ Попытка {attempt + 1} восстановления не удалась: {str(e)}", 'error')
            
        # Дополнительная пауза перед следующей попыткой
        if attempt < max_retries - 1:
            await asyncio.sleep(5)
    
    log_message(chat_id, session_name, f"❌ Все попытки восстановления синхронизации исчерпаны", 'error')
    return False




# Message handlers

def register_handlers(bot):
    # Command handlers
    bot.message_handler(commands=['start', 'help'])(cmd_start)
    
    # Main menu handlers
    bot.message_handler(func=lambda m: m.text == '➕ Добавить аккаунт')(lambda m: handle_main(m, 'add'))
    bot.message_handler(func=lambda m: m.text == '➖ Удалить аккаунт')(lambda m: handle_main(m, 'remove'))
    bot.message_handler(func=lambda m: m.text == '▶️ Запустить рассылку')(lambda m: handle_main(m, 'start'))
    bot.message_handler(func=lambda m: m.text == '⏹️ Остановить рассылку')(lambda m: handle_main(m, 'stop'))
    bot.message_handler(func=lambda m: m.text == '👤 Управление аккаунтом')(handle_account_settings)
    bot.message_handler(func=lambda m: m.text == '📋 Просмотр чатов')(handle_view_chats)
    bot.message_handler(func=lambda m: m.text == '➕ Вступить в чаты')(handle_join_chats)
    bot.message_handler(func=lambda m: m.text == '⚙️ Настройки сессии')(handle_session_settings)
    bot.message_handler(func=lambda m: m.text == '🤖 Автоподписка')(handle_auto_subscribe_start)
    
    # Cancel handler
    bot.message_handler(func=lambda m: m.text == 'Отмена')(handle_cancel)
    
    # State handlers
    bot.message_handler(func=lambda m: m.chat.id in states)(handle_states)

def handle_main(msg, action):
    chat_id = msg.chat.id
    if action == 'add':
        states[chat_id] = {'step': 'api_id'}
        bot.send_message(chat_id, 'Введите api_id:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
    elif action == 'remove':
        if not accounts:
            bot.send_message(chat_id, 'Нет аккаунтов для удаления.', reply_markup=main_keyboard())
        else:
            states[chat_id] = {'step': 'remove'}
            bot.send_message(chat_id, 'Выберите аккаунт для удаления:', reply_markup=sessions_keyboard())
    elif action == 'start':
        if not accounts:
            bot.send_message(chat_id, 'Нет аккаунтов.', reply_markup=main_keyboard())
        else:
            states[chat_id] = {'step': 'b_select_session'}
            bot.send_message(chat_id, 'Выберите сессию для рассылки:', reply_markup=sessions_keyboard())
    elif action == 'stop':
        if not tasks:
            bot.send_message(chat_id, 'Нет активных рассылок.', reply_markup=main_keyboard())
        else:
            states[chat_id] = {'step': 'stop'}
            bot.send_message(chat_id, 'Выберите сессию для остановки:', reply_markup=sessions_keyboard())

def handle_states(msg):
    chat_id = msg.chat.id
    state = states.get(chat_id)
    text = msg.text.strip()

    if state is None:
        # If no state, just return (or handle as a regular command/message if needed elsewhere)
        return

    if text == 'Отмена':
        states.pop(chat_id, None)
        bot.send_message(chat_id, 'Операция отменена.', reply_markup=main_keyboard())
        return

    step = state['step']

    # Map of step handlers
    step_handlers = {
        'select_account_settings': handle_account_settings_selection,
        'account_settings_menu': handle_account_settings_menu_selection,
        'session_settings': handle_settings_menu,
        'logging_settings': handle_logging_settings,
        'change_first_name': handle_change_first_name_input,
        'change_username': handle_change_username_input,
        'change_bio': handle_change_bio_input,
        'change_avatar': handle_change_avatar_input,
        'b_select_session': handle_broadcast_session_selection,
        'b_select_method': handle_broadcast_method_selection,
        'b_select_config': handle_broadcast_config_selection,
        'b_select_type': handle_broadcast_type_selection,
        'b_manual_input_chats': handle_broadcast_manual_chats_input,
        'b_message': handle_broadcast_message_input,
        'b_delay_msg': handle_broadcast_delay_msg_input,
        'b_delay_iter': handle_broadcast_delay_iter_input,
        'b_save_config': handle_broadcast_save_config_prompt,
        'b_enter_config_name': handle_broadcast_config_name_input,
        'stop': handle_stop_broadcast_selection,
        'api_id': handle_api_id_input,
        'api_hash': handle_api_hash_input,
        'phone': handle_phone_input,
        'code': handle_code_input,
        'password': handle_password_input,
        'session_name': handle_session_name_input,
        'remove': handle_remove_account,
        'select_account_chats': handle_account_chats_selection,
        'select_account_join': handle_account_join_selection,
        'join_chats_input': handle_join_chats_input,
        'auto_select_session': handle_auto_select_session,
        'auto_target_chats': handle_auto_target_chats_input,
        'auto_message': handle_auto_message,
        'auto_delay': handle_auto_delay,
    }

    # Call appropriate handler if exists
    if step in step_handlers:
        step_handlers[step](msg)
    else:
        # Handle steps that are implemented directly in handle_states
        # (should be minimal now with dedicated handlers)
        bot.send_message(chat_id, 'Неизвестное состояние.', reply_markup=main_keyboard())
        states.pop(chat_id)

# --- New handlers for broadcast flow --- #

def handle_broadcast_session_selection(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    text = msg.text.strip()

    if text not in accounts:
        bot.send_message(chat_id, 'Неверная сессия.', reply_markup=main_keyboard())
        states.pop(chat_id)
        return
    state['name'] = text
    state['step'] = 'b_select_method'
    bot.send_message(chat_id, 'Выберите метод выбора чатов:', reply_markup=broadcast_chats_method_keyboard())

def handle_broadcast_method_selection(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    text = msg.text.strip()
    session_name = state['name']

    if text == 'Использовать сохраненную конфигурацию':
        if session_name in configs and configs[session_name]:
            state['step'] = 'b_select_config'
            bot.send_message(chat_id, 'Выберите конфигурацию:', reply_markup=configs_keyboard(session_name))
        else:
            bot.send_message(chat_id, 'Для этой сессии нет сохраненных конфигураций.', reply_markup=broadcast_chats_method_keyboard())
    elif text == 'Выбрать по типу':
        state['step'] = 'b_select_type'
        bot.send_message(chat_id, 'Выберите тип чатов:', reply_markup=chat_type_keyboard())
    elif text == 'Ввести вручную':
        state['step'] = 'b_manual_input_chats'
        bot.send_message(chat_id, 'Введите чаты через новую строку (каждый чат с новой строки):', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
    elif text == 'Назад':
         states[chat_id] = {'step': 'b_select_session'}
         bot.send_message(chat_id, 'Выберите сессию для рассылки:', reply_markup=sessions_keyboard())
    else:
         bot.send_message(chat_id, 'Неверный выбор.', reply_markup=broadcast_chats_method_keyboard())

def handle_broadcast_config_selection(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    text = msg.text.strip()
    session_name = state['name']

    if session_name in configs and text in configs[session_name]:
        state['chats'] = configs[session_name][text]
        state['step'] = 'b_message'
        bot.send_message(chat_id, 'Введите текст сообщения:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
    elif text == 'Назад':
        state['step'] = 'b_select_method'
        bot.send_message(chat_id, 'Выберите метод выбора чатов:', reply_markup=broadcast_chats_method_keyboard())
    else:
        bot.send_message(chat_id, 'Неверная конфигурация.', reply_markup=configs_keyboard(session_name))

def handle_broadcast_type_selection(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    text = msg.text.strip()
    session_name = state['name']
    selected_type = text

    if selected_type not in ['📢 Все каналы', '👥 Все группы', '💬 Все личные чаты', '📋 Все чаты', 'Назад']:
         bot.send_message(chat_id, 'Неверный тип чата.', reply_markup=chat_type_keyboard())
         return

    if selected_type == 'Назад':
        state['step'] = 'b_select_method'
        bot.send_message(chat_id, 'Выберите метод выбора чатов:', reply_markup=broadcast_chats_method_keyboard())
        return

    bot.send_message(chat_id, '⏳ Получаю список чатов...')

    async def get_and_filter_chats():
        client = TelegramClient(
            StringSession(accounts[session_name]['string_session']),
            accounts[session_name]['api_id'],
            accounts[session_name]['api_hash'],
            device_model="iPhone 13 Pro Max",
            system_version="4.16.30-vxCUSTOM",
            app_version="8.4",
            lang_code="en",
            system_lang_code="en-US"
        )
        try:
            await client.connect()
            if not await client.is_user_authorized():
                bot.send_message(chat_id, '❌ Ошибка авторизации аккаунта', reply_markup=main_keyboard())
                return

            dialogs = await client.get_dialogs()
            filtered_chats = []
            for dialog in dialogs:
                chat = dialog.entity
                if hasattr(chat, 'id'):
                    chat_type = "Канал" if hasattr(chat, 'broadcast') and chat.broadcast else \
                              "Группа" if hasattr(chat, 'megagroup') and chat.megagroup else \
                              "Супергруппа" if hasattr(chat, 'gigagroup') and chat.gigagroup else \
                              "Личный чат"

                    should_add = False
                    if selected_type == '📋 Все чаты':
                        should_add = True
                    elif selected_type == '📢 Все каналы' and chat_type == 'Канал':
                        should_add = True
                    elif selected_type == '👥 Все группы' and (chat_type == 'Группа' or chat_type == 'Супергруппа'):
                        should_add = True
                    elif selected_type == '💬 Все личные чаты' and chat_type == 'Личный чат':
                        should_add = True

                    if should_add:
                        formatted_id = chat.id
                        if chat_type in ["Канал", "Группа", "Супергруппа"]:
                            if str(formatted_id).startswith('100'):
                                formatted_id = f"-{formatted_id}"
                            else:
                                formatted_id = f"-100{formatted_id}"
                        
                        filtered_chats.append(str(formatted_id)) # Store as string ID

            if filtered_chats:
                state['chats'] = filtered_chats
                state['step'] = 'b_message'
                bot.send_message(chat_id, f'✅ Найдено {len(filtered_chats)} чатов выбранного типа. Введите текст сообщения:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
            else:
                bot.send_message(chat_id, "Не найдено чатов выбранного типа.", reply_markup=chat_type_keyboard())
                # Stay in b_select_type state

        except Exception as e:
            bot.send_message(chat_id, f'❌ Ошибка при получении чатов: {str(e)}', reply_markup=broadcast_chats_method_keyboard())
            state['step'] = 'b_select_method' # Go back to method selection on error
        finally:
            await client.disconnect()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Run the async function in a separate thread
    threading.Thread(target=lambda: loop.run_until_complete(get_and_filter_chats())).start()

def handle_broadcast_manual_chats_input(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    text = msg.text.strip()

    try:
        chats = []
        # Разбиваем по переносам строк
        for c in text.split('\n'):
            c = c.strip()
            if c:
                # Обрабатываем ссылки t.me
                if 't.me/' in c:
                    # Извлекаем username из ссылки
                    if '+' in c:
                        # Приватная ссылка-приглашение
                        invite_hash = c.split('t.me/+')[-1].split('?')[0].strip()
                        chats.append(f"+{invite_hash}")
                    else:
                        # Публичная ссылка
                        username = c.split('t.me/')[-1].split('?')[0].strip()
                        chats.append(username)
                # Обрабатываем @username
                elif c.startswith('@'):
                    chats.append(c[1:])  # Убираем @
                # Обрабатываем числовые ID
                elif c.startswith('-100'):
                    chats.append(c)
                elif c.startswith('-'):
                    chats.append(f"-100{c[1:]}")
                elif c.isdigit():
                    chats.append(c)
                # Обрабатываем обычные username (без @)
                else:
                    chats.append(c)

        if not chats:
             bot.send_message(chat_id, 'Список чатов пуст. Введите чаты через новую строку:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
             return

        state['chats'] = chats
        state['step'] = 'b_message'
        bot.send_message(chat_id, 'Введите текст сообщения:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
    except Exception as e:
        bot.send_message(chat_id, f'❌ Ошибка при обработке списка чатов: {e}', reply_markup=broadcast_chats_method_keyboard())
        states.pop(chat_id)

def handle_broadcast_message_input(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    text = msg.text.strip()

    state['message'] = text
    state['step'] = 'b_delay_msg'
    bot.send_message(chat_id, 'Пауза между сообщениями (сек):', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))

def handle_broadcast_delay_msg_input(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    text = msg.text.strip()

    try:
        delay_msg = float(text)
        if delay_msg < 0:
            raise ValueError("Задержка не может быть отрицательной")
        state['delay_msg'] = delay_msg
        state['step'] = 'b_delay_iter'
        bot.send_message(chat_id, 'Пауза между итерациями (сек):', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
    except ValueError:
         bot.send_message(chat_id, '❌ Неверное значение. Введите число больше 0:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))

def handle_broadcast_delay_iter_input(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    text = msg.text.strip()

    try:
        delay_iter = float(text)
        if delay_iter < 0:
            raise ValueError("Пауза не может быть отрицательной")
        state['delay_iter'] = delay_iter
        state['step'] = 'b_save_config'
        bot.send_message(chat_id, 'Сохранить этот список чатов как конфигурацию?', reply_markup=save_config_keyboard())
    except ValueError:
        bot.send_message(chat_id, '❌ Неверное значение. Введите число больше 0:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))

def handle_broadcast_save_config_prompt(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    text = msg.text.strip()

    if text == 'Да':
        state['step'] = 'b_enter_config_name'
        bot.send_message(chat_id, 'Введите название конфигурации:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
    elif text == 'Нет':
        # Proceed to start broadcast without saving
        name = state['name']
        stop_event = threading.Event()
        thread = threading.Thread(
            target=broadcast_worker,
            args=(name, state['chats'], state['message'], state['delay_msg'], state['delay_iter'], stop_event, chat_id),
            daemon=True
        )
        tasks[name] = (thread, stop_event)
        thread.start()
        bot.send_message(chat_id, f'▶️ Рассылка запущена для {name}', reply_markup=main_keyboard())
        states.pop(chat_id)
    elif text == 'Назад':
         state['step'] = 'b_delay_iter'
         bot.send_message(chat_id, 'Введите паузу между итерациями (сек):', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
    else:
         bot.send_message(chat_id, 'Неверный выбор. Сохранить конфигурацию?', reply_markup=save_config_keyboard())

def handle_broadcast_config_name_input(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    text = msg.text.strip()
    config_name = text
    session_name = state['name']

    if not config_name:
        bot.send_message(chat_id, '❌ Название конфигурации не может быть пустым. Введите название:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
        return

    if session_name not in configs:
        configs[session_name] = {}

    configs[session_name][config_name] = state['chats']
    save_accounts() # Save configs

    bot.send_message(chat_id, f'✅ Конфигурация "{config_name}" сохранена для сессии {session_name}.', reply_markup=main_keyboard())

    # Proceed to start broadcast
    name = state['name']
    stop_event = threading.Event()
    thread = threading.Thread(
        target=broadcast_worker,
        args=(name, state['chats'], state['message'], state['delay_msg'], state['delay_iter'], stop_event, chat_id),
        daemon=True
    )
    tasks[name] = (thread, stop_event)
    thread.start()
    bot.send_message(chat_id, f'▶️ Рассылка запущена для {name}', reply_markup=main_keyboard())
    states.pop(chat_id)

def handle_stop_broadcast_selection(msg):
    chat_id = msg.chat.id
    text = msg.text.strip()

    # stop for both broadcast and auto-subscribe
    if text in tasks:
        thread, stop_event = tasks.pop(text)
        stop_event.set()
        bot.send_message(chat_id, f'⏹️ Рассылка остановлена для {text}', reply_markup=main_keyboard())
    elif f"auto::{text}" in tasks:
        thread, stop_event = tasks.pop(f"auto::{text}")
        stop_event.set()
        bot.send_message(chat_id, f'⏹️ Автоподписка остановлена для {text}', reply_markup=main_keyboard())
    else:
        bot.send_message(chat_id, 'Нет активной рассылки для этой сессии.', reply_markup=main_keyboard())
    states.pop(chat_id)

def handle_account_settings(msg):
    if not accounts:
        bot.send_message(msg.chat.id, 'Нет аккаунтов для управления.', reply_markup=main_keyboard())
        return
    
    states[msg.chat.id] = {'step': 'select_account_settings', 'action': 'account_management'}
    bot.send_message(msg.chat.id, 'Выберите аккаунт для управления:', reply_markup=sessions_keyboard())

def handle_account_settings_selection(msg):
    chat_id = msg.chat.id
    if msg.text not in accounts:
        bot.send_message(chat_id, 'Неверный аккаунт.', reply_markup=main_keyboard())
        states.pop(chat_id)
        return

    account_name = msg.text
    state = states[chat_id]
    action = state.get('action') # Get the action from the state

    if action == 'account_management':
        states[chat_id] = {
            'step': 'account_settings_menu',
            'session': account_name
        }
        bot.send_message(chat_id, f'Настройки аккаунта "{account_name}":', reply_markup=account_settings_keyboard())
    elif action == 'session_settings':
        states[chat_id] = {
            'step': 'session_settings', # This state still exists for logging
            'session': account_name
        }
        bot.send_message(chat_id, f'Настройки сессии "{account_name}":', reply_markup=settings_keyboard())
    else:
        # Should not happen, but handle defensively
        bot.send_message(chat_id, 'Неизвестное действие.', reply_markup=main_keyboard())
        states.pop(chat_id)

def handle_settings_menu(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    session_name = state['session']
    
    if msg.text == '📝 Настройки логирования':
        state['step'] = 'logging_settings'
        bot.send_message(chat_id, 'Настройки логирования:', reply_markup=logging_settings_keyboard())
    elif msg.text == 'Назад':
        # Go back to account selection for settings
        states[chat_id] = {'step': 'select_account_settings'}
        bot.send_message(chat_id, 'Выберите аккаунт для настройки:', reply_markup=sessions_keyboard())

def handle_logging_settings(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    session_name = state['session']
    
    if session_name not in settings:
        settings[session_name] = DEFAULT_SETTINGS.copy()
    
    if msg.text == '✅ Включить логирование':
        settings[session_name]['logging']['enabled'] = True
        bot.send_message(chat_id, '✅ Логирование включено', reply_markup=logging_settings_keyboard())
    elif msg.text == '❌ Отключить логирование':
        settings[session_name]['logging']['enabled'] = False
        bot.send_message(chat_id, '❌ Логирование отключено', reply_markup=logging_settings_keyboard())
    elif msg.text == '📋 Полное логирование':
        settings[session_name]['logging']['level'] = 'full'
        bot.send_message(chat_id, '✅ Установлено полное логирование', reply_markup=logging_settings_keyboard())
    elif msg.text == '📝 Минимальное логирование':
        settings[session_name]['logging']['level'] = 'minimal'
        bot.send_message(chat_id, '✅ Установлено минимальное логирование', reply_markup=logging_settings_keyboard())
    elif msg.text == 'Назад':
        state['step'] = 'session_settings'
        bot.send_message(chat_id, 'Настройки сессии:', reply_markup=settings_keyboard())
    
    save_accounts()


def handle_view_chats(msg):
    if not accounts:
        bot.send_message(msg.chat.id, 'Нет аккаунтов для просмотра чатов.', reply_markup=main_keyboard())
        return
    
    states[msg.chat.id] = {'step': 'select_account_chats'}
    bot.send_message(msg.chat.id, 'Выберите аккаунт для просмотра чатов:', reply_markup=sessions_keyboard())

def cmd_start(msg):
    bot.send_message(msg.chat.id, '👋 Выберите действие:', reply_markup=main_keyboard())

def handle_join_chats(msg):
    if not accounts:
        bot.send_message(msg.chat.id, 'Нет аккаунтов для вступления в чаты.', reply_markup=main_keyboard())
        return
    
    states[msg.chat.id] = {'step': 'select_account_join'}
    bot.send_message(msg.chat.id, 'Выберите аккаунт для вступления в чаты:', reply_markup=sessions_keyboard())

def handle_session_settings(msg):
    if not accounts:
        bot.send_message(msg.chat.id, 'Нет аккаунтов для настройки.', reply_markup=main_keyboard())
        return
    
    states[msg.chat.id] = {'step': 'select_account_settings', 'action': 'session_settings'}
    bot.send_message(msg.chat.id, 'Выберите аккаунт для настройки:', reply_markup=sessions_keyboard())

def handle_cancel(msg):
    states.pop(msg.chat.id, None)
    bot.send_message(msg.chat.id, 'Операция отменена.', reply_markup=main_keyboard())

def handle_auto_subscribe_start(msg):
    if not accounts:
        bot.send_message(msg.chat.id, 'Нет аккаунтов для автоподписки.', reply_markup=main_keyboard())
        return
    states[msg.chat.id] = {'step': 'auto_select_session'}
    bot.send_message(msg.chat.id, 'Выберите аккаунт для автоподписки:', reply_markup=sessions_keyboard())

def handle_auto_select_session(msg):
    chat_id = msg.chat.id
    text = msg.text.strip()
    if text not in accounts:
        bot.send_message(chat_id, '❌ Аккаунт не найден. Выберите существующий аккаунт:', reply_markup=sessions_keyboard())
        return
    states[chat_id] = {
        'step': 'auto_target_chats',
        'session': text
    }
    bot.send_message(chat_id, 'Укажите целевые чаты для автоподписки (каждый с новой строки):', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))

def handle_auto_target_chats_input(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    text = msg.text.strip()
    try:
        chats = []
        # Разбиваем по переносам строк
        for c in text.split('\n'):
            c = c.strip()
            if c:
                # Обрабатываем ссылки t.me
                if 't.me/' in c:
                    # Извлекаем username из ссылки
                    if '+' in c:
                        # Приватная ссылка-приглашение
                        invite_hash = c.split('t.me/+')[-1].split('?')[0].strip()
                        chats.append(f"+{invite_hash}")
                    else:
                        # Публичная ссылка
                        username = c.split('t.me/')[-1].split('?')[0].strip()
                        chats.append(username)
                # Обрабатываем @username
                elif c.startswith('@'):
                    chats.append(c[1:])  # Убираем @
                # Обрабатываем числовые ID
                elif c.startswith('-100'):
                    chats.append(c)
                elif c.startswith('-'):
                    chats.append(f"-100{c[1:]}")
                elif c.isdigit():
                    chats.append(c)
                # Обрабатываем обычные username (без @)
                else:
                    chats.append(c)

        if not chats:
             bot.send_message(chat_id, 'Список чатов пуст. Введите чаты (каждый с новой строки):', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
             return

        state['target_chats'] = chats
        state['step'] = 'auto_message'
        bot.send_message(chat_id, 'Введите текст сообщения для рассылки:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
    except Exception as e:
        bot.send_message(chat_id, f'❌ Ошибка при обработке списка чатов: {e}', reply_markup=main_keyboard())
        states.pop(chat_id)

def handle_auto_message(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    state['auto_text'] = msg.text.strip()
    state['step'] = 'auto_delay'
    bot.send_message(chat_id, 'Введите задержку между проверками (сек):', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))

def handle_auto_delay(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    try:
        delay_sec = float(msg.text.strip())
        if delay_sec < 0:
            raise ValueError()
        session_name = state['session']
        targets = state['target_chats']
        message_text = state['auto_text']
        stop_event = threading.Event()
        thread = threading.Thread(
            target=auto_subscribe_worker,
            args=(session_name, targets, message_text, delay_sec, stop_event, chat_id),
            daemon=True
        )
        tasks[f"auto::{session_name}"] = (thread, stop_event)
        thread.start()
        bot.send_message(chat_id, f'▶️ Автоподписка запущена для {session_name}', reply_markup=main_keyboard())
        states.pop(chat_id)
    except Exception:
        bot.send_message(chat_id, '❌ Неверное значение. Введите число больше 0:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
def handle_change_first_name_input(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    
    if msg.text == 'Отмена':
        states[chat_id]['step'] = 'account_settings_menu'
        bot.send_message(chat_id, 'Изменение имени отменено.', reply_markup=account_settings_keyboard())
        return

    async def update_name():
        account_name = state['session']
        client = TelegramClient(
            StringSession(accounts[account_name]['string_session']),
            accounts[account_name]['api_id'],
            accounts[account_name]['api_hash'],
            device_model="iPhone 13 Pro Max",
            system_version="4.16.30-vxCUSTOM",
            app_version="8.4",
            lang_code="en",
            system_lang_code="en-US"
        )
        await client.start()
        try:
            names = msg.text.split(' ', 1)
            first_name = names[0]
            last_name = names[1] if len(names) > 1 else ''
            await client(UpdateProfileRequest(
                first_name=first_name,
                last_name=last_name
            ))
            bot.send_message(chat_id, '✅ Имя успешно обновлено', reply_markup=account_settings_keyboard())
        except Exception as e:
            bot.send_message(chat_id, f'❌ Ошибка при обновлении имени: {e}', reply_markup=account_settings_keyboard())
        finally:
            await client.disconnect()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(update_name())
    loop.close()
    states[chat_id]['step'] = 'account_settings_menu' # Set step back to account settings menu

def handle_change_username_input(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    
    if msg.text == 'Отмена':
        states[chat_id]['step'] = 'account_settings_menu'
        bot.send_message(chat_id, 'Изменение username отменено.', reply_markup=account_settings_keyboard())
        return

    async def update_username():
        account_name = state['session']
        client = TelegramClient(
            StringSession(accounts[account_name]['string_session']),
            accounts[account_name]['api_id'],
            accounts[account_name]['api_hash'],
            device_model="iPhone 13 Pro Max",
            system_version="4.16.30-vxCUSTOM",
            app_version="8.4",
            lang_code="en",
            system_lang_code="en-US"
        )
        await client.start()
        try:
            await client(UpdateUsernameRequest(msg.text))
            bot.send_message(chat_id, '✅ Username успешно обновлен', reply_markup=account_settings_keyboard())
        except Exception as e:
            bot.send_message(chat_id, f'❌ Ошибка при обновлении username: {e}', reply_markup=account_settings_keyboard())
        finally:
            await client.disconnect()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(update_username())
    loop.close()
    states[chat_id]['step'] = 'account_settings_menu' # Set step back to account settings menu

def handle_change_bio_input(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    
    if msg.text == 'Отмена':
        states[chat_id]['step'] = 'account_settings_menu'
        bot.send_message(chat_id, 'Изменение био отменено.', reply_markup=account_settings_keyboard())
        return

    async def update_bio():
        account_name = state['session']
        client = TelegramClient(
            StringSession(accounts[account_name]['string_session']),
            accounts[account_name]['api_id'],
            accounts[account_name]['api_hash'],
            device_model="iPhone 13 Pro Max",
            system_version="4.16.30-vxCUSTOM",
            app_version="8.4",
            lang_code="en",
            system_lang_code="en-US"
        )
        await client.start()
        try:
            await client(UpdateProfileRequest(about=msg.text))
            bot.send_message(chat_id, '✅ Био успешно обновлено', reply_markup=account_settings_keyboard())
        except Exception as e:
            bot.send_message(chat_id, f'❌ Ошибка при обновлении био: {e}', reply_markup=account_settings_keyboard())
        finally:
            await client.disconnect()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(update_bio())
    loop.close()
    states[chat_id]['step'] = 'account_settings_menu' # Set step back to account settings menu

def handle_account_settings_menu_selection(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    session_name = state['session']
    
    if msg.text == '📝 Изменить имя':
        state['step'] = 'change_first_name'
        bot.send_message(chat_id, 'Введите новое имя (и фамилию через пробел, если есть):')
    elif msg.text == '👤 Изменить username':
        state['step'] = 'change_username'
        bot.send_message(chat_id, 'Введите новый username:')
    elif msg.text == '📋 Изменить био':
        state['step'] = 'change_bio'
        bot.send_message(chat_id, 'Введите новое описание:')
    elif msg.text == '🖼 Изменить аватар':
        state['step'] = 'change_avatar'
        bot.send_message(chat_id, 'Отправьте новое фото аватара:')
    elif msg.text == 'Назад':
        # Go back to account selection for account management
        states[chat_id] = {'step': 'select_account_settings', 'action': 'account_management'}
        bot.send_message(chat_id, 'Выберите аккаунт для управления:', reply_markup=sessions_keyboard())

def handle_change_avatar_input(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    
    if msg.text == 'Отмена':
        states[chat_id]['step'] = 'account_settings_menu'
        bot.send_message(chat_id, 'Изменение аватара отменено.', reply_markup=account_settings_keyboard())
        return
        
    # Check if the message contains a photo
    if not msg.photo:
        bot.send_message(chat_id, '❌ Пожалуйста, отправьте фото.', reply_markup=account_settings_keyboard())
        # Keep the state as change_avatar to allow retrying
        return

    account_name = state['session']
    file_info = bot.get_file(msg.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    # Save the photo temporarily
    photo_path = f'{account_name}_avatar.jpg'
    with open(photo_path, 'wb') as new_file:
        new_file.write(downloaded_file)

    async def update_avatar():
        client = TelegramClient(
            StringSession(accounts[account_name]['string_session']),
            accounts[account_name]['api_id'],
            accounts[account_name]['api_hash'],
            device_model="iPhone 13 Pro Max",
            system_version="4.16.30-vxCUSTOM",
            app_version="8.4",
            lang_code="en",
            system_lang_code="en-US"
        )
        await client.start()
        try:
            # Upload the photo
            photo = await client.upload_file(photo_path)
            
            # Delete existing photos first (optional, but good practice)
            try:
                existing_photos = await client.get_profile_photos('me')
                await client(DeletePhotosRequest(id=[p.photo.id for p in existing_photos]))
            except Exception as e:
                print(f"Error deleting existing photos: {e}") # Log the error, but don't stop

            # Update the profile photo
            await client(UploadProfilePhotoRequest(photo))

            bot.send_message(chat_id, '✅ Аватар успешно обновлен', reply_markup=account_settings_keyboard())
        except Exception as e:
            bot.send_message(chat_id, f'❌ Ошибка при обновлении аватара: {e}', reply_markup=account_settings_keyboard())
        finally:
            await client.disconnect()
            # Clean up the temporary photo file
            if os.path.exists(photo_path):
                os.remove(photo_path)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Use threading to run the async function without blocking the bot's polling loop
    threading.Thread(target=lambda: loop.run_until_complete(update_avatar())).start()
    
    # Set step back to account settings menu after initiating the process
    states[chat_id]['step'] = 'account_settings_menu'

def handle_api_id_input(msg):
    chat_id = msg.chat.id
    text = msg.text.strip()
    
    try:
        api_id = int(text)
        states[chat_id] = {
            'step': 'api_hash',
            'api_id': api_id
        }
        bot.send_message(chat_id, 'Введите api_hash:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
    except ValueError:
        bot.send_message(chat_id, '❌ Неверный формат api_id. Введите число:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))

def handle_api_hash_input(msg):
    chat_id = msg.chat.id
    text = msg.text.strip()
    
    states[chat_id] = {
        'step': 'phone',
        'api_id': states[chat_id]['api_id'],
        'api_hash': text
    }
    bot.send_message(chat_id, 'Введите номер телефона (+...):', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))

def handle_phone_input(msg):
    chat_id = msg.chat.id
    text = msg.text.strip()
    
    if not text.startswith('+'):
        bot.send_message(chat_id, '❌ Неверный формат номера. Введите номер в формате +...:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
        return
    
    states[chat_id] = {
        'step': 'session_name',
        'api_id': states[chat_id]['api_id'],
        'api_hash': states[chat_id]['api_hash'],
        'phone': text
    }
    bot.send_message(chat_id, 'Введите название для сессии:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))

def handle_session_name_input(msg):
    chat_id = msg.chat.id
    text = msg.text.strip()
    
    if text in accounts:
        bot.send_message(chat_id, '❌ Сессия с таким названием уже существует. Введите другое название:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
        return
    
    # Создаем новый цикл событий для текущего потока
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Создаем клиент с новым циклом событий
    client = TelegramClient(
        StringSession(),
        states[chat_id]['api_id'],
        states[chat_id]['api_hash'],
        device_model="iPhone 13 Pro Max",
        system_version="4.16.30-vxCUSTOM",
        app_version="8.4",
        lang_code="en",
        system_lang_code="en-US",
        loop=loop
    )
    
    states[chat_id].update({
        'step': 'code',
        'session_name': text,
        'client': client,
        'loop': loop
    })
    
    async def send_code():
        await client.connect()
        await client.send_code_request(states[chat_id]['phone'])
    
    try:
        loop.run_until_complete(send_code())
        bot.send_message(chat_id, 'Код отправлен. Введите его:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
    except Exception as e:
        bot.send_message(chat_id, f'Ошибка при отправке кода: {e}', reply_markup=main_keyboard())
        try:
            loop.run_until_complete(client.disconnect())
        except:
            pass
        finally:
            loop.close()
        states.pop(chat_id)

def handle_code_input(msg):
    chat_id = msg.chat.id
    text = msg.text.strip()
    state = states[chat_id]
    client = state['client']
    loop = state['loop']
    
    async def sign_in():
        await client.sign_in(state['phone'], text)
    
    try:
        loop.run_until_complete(sign_in())
    except SessionPasswordNeededError:
        state['step'] = 'password'
        bot.send_message(chat_id, 'Введите пароль двухфакторной аутентификации:', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
        return
    except Exception as e:
        bot.send_message(chat_id, f'❌ Ошибка при входе: {str(e)}', reply_markup=main_keyboard())
        try:
            loop.run_until_complete(client.disconnect())
        except:
            pass
        finally:
            loop.close()
        states.pop(chat_id)
        return
    
    # Save account
    session_name = state['session_name']
    accounts[session_name] = {
        'api_id': state['api_id'],
        'api_hash': state['api_hash'],
        'string_session': client.session.save(),
        'phone': state['phone']
    }
    save_accounts()
    
    try:
        loop.run_until_complete(client.disconnect())
    except:
        pass
    finally:
        loop.close()
    
    bot.send_message(chat_id, f'✅ Аккаунт {session_name} успешно добавлен', reply_markup=main_keyboard())
    states.pop(chat_id)

def handle_password_input(msg):
    chat_id = msg.chat.id
    text = msg.text.strip()
    state = states[chat_id]
    client = state['client']
    loop = state['loop']
    
    async def sign_in_password():
        try:
            await client.sign_in(password=text)
            session_name = state['session_name']
            accounts[session_name] = {
                'api_id': state['api_id'],
                'api_hash': state['api_hash'],
                'string_session': client.session.save(),
                'phone': state['phone']
            }
            save_accounts()
            
            try:
                await client.disconnect()
            except:
                pass
            finally:
                loop.close()
            
            bot.send_message(chat_id, f'✅ Аккаунт {session_name} успешно добавлен', reply_markup=main_keyboard())
        except Exception as e:
            bot.send_message(chat_id, f'❌ Ошибка авторизации: {e}\nПопробуйте еще раз или нажмите "Отмена"', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))
            return
    
    loop.run_until_complete(sign_in_password())
    states.pop(chat_id)

def handle_remove_account(msg):
    chat_id = msg.chat.id
    text = msg.text.strip()
    
    if text not in accounts:
        bot.send_message(chat_id, '❌ Аккаунт не найден. Выберите существующий аккаунт:', reply_markup=sessions_keyboard())
        return
    
    # Stop any running tasks for this account
    if text in tasks:
        thread, stop_event = tasks.pop(text)
        stop_event.set()
    if f"auto::{text}" in tasks:
        thread, stop_event = tasks.pop(f"auto::{text}")
        stop_event.set()
    
    # Remove account and its related data
    del accounts[text]
    if text in configs:
        del configs[text]
    if text in settings:
        del settings[text]
    
    save_accounts()
    bot.send_message(chat_id, f'✅ Аккаунт {text} успешно удален', reply_markup=main_keyboard())
    states.pop(chat_id)

def handle_account_chats_selection(msg):
    chat_id = msg.chat.id
    text = msg.text.strip()
    
    if text not in accounts:
        bot.send_message(chat_id, '❌ Аккаунт не найден. Выберите существующий аккаунт:', reply_markup=sessions_keyboard())
        return
    
    async def get_chats():
        client = TelegramClient(
            StringSession(accounts[text]['string_session']),
            accounts[text]['api_id'],
            accounts[text]['api_hash'],
            device_model="iPhone 13 Pro Max",
            system_version="4.16.30-vxCUSTOM",
            app_version="8.4",
            lang_code="en",
            system_lang_code="en-US"
        )
        try:
            await client.connect()
            if not await client.is_user_authorized():
                bot.send_message(chat_id, '❌ Ошибка авторизации аккаунта', reply_markup=main_keyboard())
                return

            dialogs = await client.get_dialogs()
            chat_list = []
            for dialog in dialogs:
                chat = dialog.entity
                if hasattr(chat, 'id'):
                    chat_type = "Канал" if hasattr(chat, 'broadcast') and chat.broadcast else \
                              "Группа" if hasattr(chat, 'megagroup') and chat.megagroup else \
                              "Супергруппа" if hasattr(chat, 'gigagroup') and chat.gigagroup else \
                              "Личный чат"
                    
                    chat_name = getattr(chat, 'title', None) or getattr(chat, 'first_name', None) or str(chat.id)
                    
                    # Форматируем ID чата
                    formatted_id = chat.id
                    if chat_type in ["Канал", "Группа", "Супергруппа"]:
                        if str(formatted_id).startswith('100'):
                            formatted_id = f"-{formatted_id}"
                        else:
                            formatted_id = f"-100{formatted_id}"
                    
                    chat_list.append(f"{chat_type}: {chat_name}\nID: {formatted_id}")
            
            if chat_list:
                message = "Список чатов:\n\n" + "\n\n".join(chat_list)
                # Split message if it's too long
                if len(message) > 4000:
                    parts = [message[i:i+4000] for i in range(0, len(message), 4000)]
                    for part in parts:
                        bot.send_message(chat_id, part)
                else:
                    bot.send_message(chat_id, message)
            else:
                bot.send_message(chat_id, "Нет доступных чатов.")
            
            bot.send_message(chat_id, "Выберите действие:", reply_markup=main_keyboard())
        except Exception as e:
            bot.send_message(chat_id, f'❌ Ошибка при получении чатов: {str(e)}', reply_markup=main_keyboard())
        finally:
            await client.disconnect()
            states.pop(chat_id)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(get_chats())

def handle_account_join_selection(msg):
    chat_id = msg.chat.id
    text = msg.text.strip()
    
    if text not in accounts:
        bot.send_message(chat_id, '❌ Аккаунт не найден. Выберите существующий аккаунт:', reply_markup=sessions_keyboard())
        return
    
    states[chat_id] = {
        'step': 'join_chats_input',
        'session': text
    }
    bot.send_message(chat_id, 'Введите ссылки на чаты через новую строку (каждый чат с новой строки):', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('Отмена')))

def handle_join_chats_input(msg):
    chat_id = msg.chat.id
    state = states[chat_id]
    text = msg.text.strip()
    session_name = state['session']
    
    if text == 'Отмена':
        states.pop(chat_id)
        bot.send_message(chat_id, 'Операция отменена.', reply_markup=main_keyboard())
        return
    
    async def join_chats():
        client = TelegramClient(
            StringSession(accounts[session_name]['string_session']),
            accounts[session_name]['api_id'],
            accounts[session_name]['api_hash'],
            device_model="iPhone 13 Pro Max",
            system_version="4.16.30-vxCUSTOM",
            app_version="8.4",
            lang_code="en",
            system_lang_code="en-US"
        )
        try:
            await client.connect()
            if not await client.is_user_authorized():
                bot.send_message(chat_id, '❌ Ошибка авторизации аккаунта', reply_markup=main_keyboard())
                return

            # Разбиваем текст на строки и фильтруем пустые строки
            chat_links = [link.strip() for link in text.split('\n') if link.strip()]
            success_count = 0
            fail_count = 0
            already_joined_count = 0
            
            # Получаем список уже присоединенных чатов
            dialogs = await client.get_dialogs()
            joined_chats = set()
            for dialog in dialogs:
                if hasattr(dialog.entity, 'username') and dialog.entity.username:
                    joined_chats.add(dialog.entity.username.lower())
            
            for link in chat_links:
                try:
                    # Извлекаем username или invite_hash из ссылки
                    username = None
                    invite_hash = None
                    
                    if 't.me/' in link:
                        # Обработка публичных ссылок
                        if '+' in link:
                            # Это приватная ссылка-приглашение
                            invite_hash = link.split('t.me/+')[-1].split('?')[0].lower()
                        else:
                            # Это публичная ссылка
                            username = link.split('t.me/')[-1].split('?')[0].lower()
                    elif '@' in link:
                        # Это username
                        username = link.split('@')[-1].split('?')[0].lower()
                    
                    if not username and not invite_hash:
                        bot.send_message(chat_id, f'❌ Неверный формат ссылки: {link}')
                        fail_count += 1
                        continue
                    
                    # Проверяем, не присоединены ли мы уже к этому чату (только для публичных чатов)
                    if username and username in joined_chats:
                        already_joined_count += 1
                        bot.send_message(chat_id, f'ℹ️ Уже состоим в чате {link}')
                        continue
                    
                    # Присоединяемся к чату
                    if invite_hash:
                        # Для приватных ссылок используем специальный метод
                        try:
                            await client(ImportChatInviteRequest(invite_hash))
                            success_count += 1
                            bot.send_message(chat_id, f'✅ Успешно вступил в приватный чат {link}')
                        except Exception as invite_error:
                            # Если не получилось через ImportChatInviteRequest, пробуем через JoinChannelRequest
                            try:
                                await client(JoinChannelRequest(f"+{invite_hash}"))
                                success_count += 1
                                bot.send_message(chat_id, f'✅ Успешно вступил в приватный чат {link}')
                            except Exception as join_error:
                                raise Exception(f"Не удалось вступить через оба метода: {str(invite_error)} / {str(join_error)}")
                    else:
                        # Для публичных чатов используем стандартный метод
                        await client(JoinChannelRequest(username))
                        success_count += 1
                        bot.send_message(chat_id, f'✅ Успешно вступил в {link}')
                    
                except FloodWaitError as e:
                    wait_time = e.seconds
                    bot.send_message(chat_id, f'⏳ Достигнут лимит. Нужно подождать {wait_time} секунд.')
                    bot.send_message(chat_id, f'⏳ Ожидание {wait_time} секунд...')
                    
                    # Ждем указанное время
                    await asyncio.sleep(wait_time)
                    
                    # Пробуем снова присоединиться
                    try:
                        if invite_hash:
                            await client(ImportChatInviteRequest(invite_hash))
                        else:
                            await client(JoinChannelRequest(username))
                        success_count += 1
                        bot.send_message(chat_id, f'✅ Успешно вступил в {link} после ожидания')
                    except Exception as retry_error:
                        fail_count += 1
                        bot.send_message(chat_id, f'❌ Ошибка при повторной попытке вступления в {link}: {str(retry_error)}')
                
                except Exception as e:
                    fail_count += 1
                    bot.send_message(chat_id, f'❌ Ошибка при вступлении в {link}: {str(e)}')
                
                # Небольшая пауза между попытками вступления
                await asyncio.sleep(2)
            
            # Отправляем итоговую статистику
            stats_message = f'Итоги:\n✅ Успешно: {success_count}\n❌ Ошибок: {fail_count}'
            if already_joined_count > 0:
                stats_message += f'\nℹ️ Уже состоим: {already_joined_count}'
            bot.send_message(chat_id, stats_message, reply_markup=main_keyboard())
            
        except Exception as e:
            bot.send_message(chat_id, f'❌ Ошибка при подключении: {str(e)}', reply_markup=main_keyboard())
        finally:
            await client.disconnect()
            states.pop(chat_id)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(join_chats())


# Run bot

def main():
    load_accounts()
    
    # Register command handlers
    bot.message_handler(commands=['start', 'help'])(cmd_start)
    
    # Register main menu handlers
    bot.message_handler(func=lambda m: m.text == '➕ Добавить аккаунт')(lambda m: handle_main(m, 'add'))
    bot.message_handler(func=lambda m: m.text == '➖ Удалить аккаунт')(lambda m: handle_main(m, 'remove'))
    bot.message_handler(func=lambda m: m.text == '▶️ Запустить рассылку')(lambda m: handle_main(m, 'start'))
    bot.message_handler(func=lambda m: m.text == '⏹️ Остановить рассылку')(lambda m: handle_main(m, 'stop'))
    bot.message_handler(func=lambda m: m.text == '👤 Управление аккаунтом')(handle_account_settings)
    bot.message_handler(func=lambda m: m.text == '📋 Просмотр чатов')(handle_view_chats)
    bot.message_handler(func=lambda m: m.text == '➕ Вступить в чаты')(handle_join_chats)
    bot.message_handler(func=lambda m: m.text == '⚙️ Настройки сессии')(handle_session_settings)
    bot.message_handler(func=lambda m: m.text == '🤖 Автоподписка')(handle_auto_subscribe_start)
    
    # Register cancel handler
    bot.message_handler(func=lambda m: m.text == 'Отмена')(handle_cancel)
    
    # Register state handler
    bot.message_handler(func=lambda m: m.chat.id in states)(handle_states)
    
    bot.infinity_polling()

if __name__ == '__main__':
    main() 
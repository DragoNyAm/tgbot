"""Обработчики состояний для рассылки"""

import asyncio
import threading
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import PeerChannel
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

from .. import storage
from ..keyboards import (
    main_keyboard, sessions_keyboard, cancel_keyboard,
    broadcast_chats_method_keyboard, chat_type_keyboard,
    save_config_keyboard, configs_keyboard
)
from ..config import DEVICE_CONFIG
from ..workers.broadcast import broadcast_worker


def handle_broadcast_session_selection(msg, bot):
    chat_id = msg.chat.id
    state = storage.states[chat_id]
    text = msg.text.strip()

    if text not in storage.accounts:
        bot.send_message(chat_id, 'Неверная сессия.', reply_markup=main_keyboard())
        storage.states.pop(chat_id)
        return
    state['name'] = text
    state['step'] = 'b_select_method'
    bot.send_message(chat_id, 'Выберите метод выбора чатов:', reply_markup=broadcast_chats_method_keyboard())


def handle_broadcast_method_selection(msg, bot):
    chat_id = msg.chat.id
    state = storage.states[chat_id]
    text = msg.text.strip()
    session_name = state['name']

    if text == 'Использовать сохраненную конфигурацию':
        if session_name in storage.configs and storage.configs[session_name]:
            state['step'] = 'b_select_config'
            bot.send_message(chat_id, 'Выберите конфигурацию:', reply_markup=configs_keyboard(session_name))
        else:
            bot.send_message(chat_id, 'Для этой сессии нет сохраненных конфигураций.', reply_markup=broadcast_chats_method_keyboard())
    elif text == 'Выбрать по типу':
        state['step'] = 'b_select_type'
        bot.send_message(chat_id, 'Выберите тип чатов:', reply_markup=chat_type_keyboard())
    elif text == 'Ввести вручную':
        state['step'] = 'b_manual_input_chats'
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(chat_id, 'Введите чаты через новую строку (каждый чат с новой строки):', reply_markup=kb)
    elif text == 'Назад':
        storage.states[chat_id] = {'step': 'b_select_session'}
        bot.send_message(chat_id, 'Выберите сессию для рассылки:', reply_markup=sessions_keyboard())
    else:
        bot.send_message(chat_id, 'Неверный выбор.', reply_markup=broadcast_chats_method_keyboard())


def handle_broadcast_config_selection(msg, bot):
    chat_id = msg.chat.id
    state = storage.states[chat_id]
    text = msg.text.strip()
    session_name = state['name']

    if session_name in storage.configs and text in storage.configs[session_name]:
        state['chats'] = storage.configs[session_name][text]
        state['step'] = 'b_select_message_type'
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('📝 Текстовое сообщение'), KeyboardButton('📤 Пересылка из канала'))
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(
            chat_id, 
            '📨 Выберите тип сообщения для рассылки:', 
            reply_markup=kb
        )
    elif text == 'Назад':
        state['step'] = 'b_select_method'
        bot.send_message(chat_id, 'Выберите метод выбора чатов:', reply_markup=broadcast_chats_method_keyboard())
    else:
        bot.send_message(chat_id, 'Неверная конфигурация.', reply_markup=configs_keyboard(session_name))


def handle_broadcast_type_selection(msg, bot):
    chat_id = msg.chat.id
    state = storage.states[chat_id]
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
            StringSession(storage.accounts[session_name]['string_session']),
            storage.accounts[session_name]['api_id'],
            storage.accounts[session_name]['api_hash'],
            **DEVICE_CONFIG
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
                        
                        filtered_chats.append(str(formatted_id))

            if filtered_chats:
                state['chats'] = filtered_chats
                state['step'] = 'b_select_message_type'
                kb = ReplyKeyboardMarkup(resize_keyboard=True)
                kb.add(KeyboardButton('📝 Текстовое сообщение'), KeyboardButton('📤 Пересылка из канала'))
                kb.add(KeyboardButton('Отмена'))
                bot.send_message(
                    chat_id, 
                    f'✅ Найдено {len(filtered_chats)} чатов выбранного типа.\n\n'
                    f'📨 Выберите тип сообщения для рассылки:', 
                    reply_markup=kb
                )
            else:
                bot.send_message(chat_id, "Не найдено чатов выбранного типа.", reply_markup=chat_type_keyboard())

        except Exception as e:
            bot.send_message(chat_id, f'❌ Ошибка при получении чатов: {str(e)}', reply_markup=broadcast_chats_method_keyboard())
            state['step'] = 'b_select_method'
        finally:
            await client.disconnect()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    threading.Thread(target=lambda: loop.run_until_complete(get_and_filter_chats())).start()


def handle_broadcast_manual_chats_input(msg, bot):
    chat_id = msg.chat.id
    state = storage.states[chat_id]
    text = msg.text.strip()

    try:
        chats = []
        for c in text.split('\n'):
            c = c.strip()
            if c:
                if 't.me/' in c:
                    if '+' in c:
                        invite_hash = c.split('t.me/+')[-1].split('?')[0].strip()
                        chats.append(f"+{invite_hash}")
                    else:
                        username = c.split('t.me/')[-1].split('?')[0].strip()
                        chats.append(username)
                elif c.startswith('@'):
                    chats.append(c[1:])
                elif c.startswith('-100'):
                    chats.append(c)
                elif c.startswith('-'):
                    chats.append(f"-100{c[1:]}")
                elif c.isdigit():
                    chats.append(c)
                else:
                    chats.append(c)

        if not chats:
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.add(KeyboardButton('Отмена'))
            bot.send_message(chat_id, 'Список чатов пуст. Введите чаты через новую строку:', reply_markup=kb)
            return

        state['chats'] = chats
        state['step'] = 'b_select_message_type'
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('📝 Текстовое сообщение'), KeyboardButton('📤 Пересылка из канала'))
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(
            chat_id, 
            '📨 Выберите тип сообщения для рассылки:', 
            reply_markup=kb
        )
    except Exception as e:
        bot.send_message(chat_id, f'❌ Ошибка при обработке списка чатов: {e}', reply_markup=broadcast_chats_method_keyboard())
        storage.states.pop(chat_id)


def handle_broadcast_message_type_selection(msg, bot):
    """Обработка выбора типа сообщения для рассылки"""
    chat_id = msg.chat.id
    state = storage.states[chat_id]
    text = msg.text.strip()
    
    if text == '📝 Текстовое сообщение':
        state['is_forward'] = False
        state['step'] = 'b_message'
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(chat_id, '📝 Введите текстовое сообщение для рассылки:', reply_markup=kb)
        
    elif text == '📤 Пересылка из канала':
        state['is_forward'] = True
        state['step'] = 'b_enter_forward_channel'
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(
            chat_id,
            '📢 Введите ID или username канала:\n\n'
            'Например: @channelname или -1001234567890\n\n'
            'Бот возьмет последнее сообщение из этого канала и будет его пересылать.',
            reply_markup=kb
        )
    else:
        bot.send_message(chat_id, '❌ Неверный выбор. Выберите один из вариантов.')


def handle_broadcast_forward_channel_input(msg, bot):
    """Обработка ввода ID канала для пересылки"""
    chat_id = msg.chat.id
    state = storage.states[chat_id]
    channel_id = msg.text.strip()
    session_name = state['name']
    
    # Проверяем канал и получаем последнее сообщение
    import asyncio
    
    async def get_last_message():
        acc = storage.accounts[session_name]
        client = TelegramClient(
            StringSession(acc['string_session']),
            acc['api_id'], acc['api_hash'],
            **DEVICE_CONFIG
        )
        await client.start()
        
        try:
            # Получаем entity канала
            entity = await client.get_entity(channel_id)
            
            # Получаем последнее сообщение
            messages = await client.get_messages(entity, limit=1)
            
            if not messages or len(messages) == 0:
                return None, None, None, "В канале нет сообщений"
            
            last_msg = messages[0]
            channel_title = getattr(entity, 'title', getattr(entity, 'username', 'Unknown'))
            
            # Сохраняем channel_id в исходном формате
            return channel_id, entity, last_msg.id, channel_title
            
        except Exception as e:
            return None, None, None, str(e)
        finally:
            await client.disconnect()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    forward_from_chat_id, entity, forward_message_id, result = loop.run_until_complete(get_last_message())
    loop.close()
    
    if forward_from_chat_id and forward_message_id and entity:
        state['forward_from_chat_id'] = forward_from_chat_id
        state['forward_message_id'] = forward_message_id
        state['step'] = 'b_delay_msg'
        
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(
            chat_id,
            f'✅ Последнее сообщение получено!\n'
            f'Канал: {result}\n'
            f'ID сообщения: {forward_message_id}\n\n'
            f'Пауза между сообщениями (сек):',
            reply_markup=kb
        )
    else:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(
            chat_id,
            f'❌ Ошибка при получении сообщения из канала:\n{result}\n\n'
            f'Проверьте правильность ID канала и попробуйте снова.',
            reply_markup=kb
        )


def handle_broadcast_message_input(msg, bot):
    """Обработка ввода текстового сообщения"""
    chat_id = msg.chat.id
    state = storage.states[chat_id]

    if not msg.text:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(
            chat_id,
            '❌ Пожалуйста, отправьте текстовое сообщение.',
            reply_markup=kb
        )
        return
    
    state['message'] = msg.text.strip()
    state['step'] = 'b_delay_msg'
    
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('Отмена'))
    bot.send_message(chat_id, 'Пауза между сообщениями (сек):', reply_markup=kb)


def handle_broadcast_delay_msg_input(msg, bot):
    chat_id = msg.chat.id
    state = storage.states[chat_id]
    text = msg.text.strip()

    try:
        delay_msg = float(text)
        if delay_msg < 0:
            raise ValueError("Задержка не может быть отрицательной")
        state['delay_msg'] = delay_msg
        state['step'] = 'b_delay_iter'
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(chat_id, 'Пауза между итерациями (сек):', reply_markup=kb)
    except ValueError:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(chat_id, '❌ Неверное значение. Введите число больше 0:', reply_markup=kb)


def handle_broadcast_delay_iter_input(msg, bot):
    chat_id = msg.chat.id
    state = storage.states[chat_id]
    text = msg.text.strip()

    try:
        delay_iter = float(text)
        if delay_iter < 0:
            raise ValueError("Пауза не может быть отрицательной")
        state['delay_iter'] = delay_iter
        state['step'] = 'b_save_config'
        bot.send_message(chat_id, 'Сохранить этот список чатов как конфигурацию?', reply_markup=save_config_keyboard())
    except ValueError:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(chat_id, '❌ Неверное значение. Введите число больше 0:', reply_markup=kb)


def handle_broadcast_save_config_prompt(msg, bot):
    chat_id = msg.chat.id
    state = storage.states[chat_id]
    text = msg.text.strip()

    if text == 'Да':
        state['step'] = 'b_enter_config_name'
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(chat_id, 'Введите название конфигурации:', reply_markup=kb)
    elif text == 'Нет':
        name = state['name']
        is_forward = state.get('is_forward', False)
        forward_from_chat_id = state.get('forward_from_chat_id')
        forward_message_id = state.get('forward_message_id')
        
        stop_event = threading.Event()
        thread = threading.Thread(
            target=broadcast_worker,
            args=(name, state['chats'], state.get('message'), state['delay_msg'], state['delay_iter'], stop_event, chat_id, is_forward, forward_from_chat_id, forward_message_id),
            daemon=True
        )
        storage.tasks[name] = (thread, stop_event)
        thread.start()
        
        message_type = '📤 Пересылка' if is_forward else '📝 Текст'
        bot.send_message(chat_id, f'▶️ Рассылка запущена для {name}\nТип: {message_type}', reply_markup=main_keyboard())
        storage.states.pop(chat_id)
    elif text == 'Назад':
        state['step'] = 'b_delay_iter'
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(chat_id, 'Введите паузу между итерациями (сек):', reply_markup=kb)
    else:
        bot.send_message(chat_id, 'Неверный выбор. Сохранить конфигурацию?', reply_markup=save_config_keyboard())


def handle_broadcast_config_name_input(msg, bot):
    chat_id = msg.chat.id
    state = storage.states[chat_id]
    text = msg.text.strip()
    config_name = text
    session_name = state['name']

    if not config_name:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(chat_id, '❌ Название конфигурации не может быть пустым. Введите название:', reply_markup=kb)
        return

    if session_name not in storage.configs:
        storage.configs[session_name] = {}

    storage.configs[session_name][config_name] = state['chats']
    storage.save_accounts()

    bot.send_message(chat_id, f'✅ Конфигурация "{config_name}" сохранена для сессии {session_name}.', reply_markup=main_keyboard())

    name = state['name']
    is_forward = state.get('is_forward', False)
    forward_from_chat_id = state.get('forward_from_chat_id')
    forward_message_id = state.get('forward_message_id')
    
    stop_event = threading.Event()
    thread = threading.Thread(
        target=broadcast_worker,
        args=(name, state['chats'], state.get('message'), state['delay_msg'], state['delay_iter'], stop_event, chat_id, is_forward, forward_from_chat_id, forward_message_id),
        daemon=True
    )
    storage.tasks[name] = (thread, stop_event)
    thread.start()
    
    message_type = '📤 Пересылка' if is_forward else '📝 Текст'
    bot.send_message(chat_id, f'▶️ Рассылка запущена для {name}\nТип: {message_type}', reply_markup=main_keyboard())
    storage.states.pop(chat_id)


def handle_stop_broadcast_selection(msg, bot):
    chat_id = msg.chat.id
    text = msg.text.strip()

    if text in storage.tasks:
        thread, stop_event = storage.tasks.pop(text)
        stop_event.set()
        bot.send_message(chat_id, f'⏹️ Рассылка остановлена для {text}', reply_markup=main_keyboard())
    elif f"auto::{text}" in storage.tasks:
        thread, stop_event = storage.tasks.pop(f"auto::{text}")
        stop_event.set()
        bot.send_message(chat_id, f'⏹️ Автоподписка остановлена для {text}', reply_markup=main_keyboard())
    else:
        bot.send_message(chat_id, 'Нет активной рассылки для этой сессии.', reply_markup=main_keyboard())
    storage.states.pop(chat_id)


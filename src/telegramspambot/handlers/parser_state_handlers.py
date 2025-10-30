"""Обработчики состояний для парсинга"""

import threading
import asyncio
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

from ..keyboards import main_keyboard, cancel_keyboard
from ..config import DEVICE_CONFIG
from .. import storage


def handle_parser_states(bot, msg):
    """Обработка состояний парсинга
    
    Returns:
        bool: True если состояние обработано, False иначе
    """
    state = storage.states.get(msg.chat.id, {}).get('step')
    
    # Выбор сессии
    if state == 'parser_select_session':
        if msg.text not in storage.accounts:
            bot.send_message(msg.chat.id, '❌ Неверная сессия.')
            return True
        
        storage.states[msg.chat.id] = {
            'step': 'parser_enter_chat_id',
            'session': msg.text
        }
        bot.send_message(
            msg.chat.id,
            '📝 Введите ID или username чата для парсинга:\n\n'
            'Например: -1001234567890 или @channelname',
            reply_markup=cancel_keyboard()
        )
        return True
    
    # Ввод ID чата для парсинга
    elif state == 'parser_enter_chat_id':
        chat_id_to_parse = msg.text.strip()
        
        storage.states[msg.chat.id]['chat_id_to_parse'] = chat_id_to_parse
        storage.states[msg.chat.id]['step'] = 'parser_enter_message_limit'
        
        bot.send_message(
            msg.chat.id,
            '🔢 Введите количество последних сообщений для парсинга:\n\n'
            'Рекомендуется: 100-500\n'
            'Больше сообщений = больше пользователей, но дольше обработка',
            reply_markup=cancel_keyboard()
        )
        return True
    
    # Ввод количества сообщений
    elif state == 'parser_enter_message_limit':
        try:
            message_limit = int(msg.text.strip())
            if message_limit <= 0:
                bot.send_message(msg.chat.id, '❌ Число должно быть положительным.')
                return True
            
            if message_limit > 1000:
                bot.send_message(
                    msg.chat.id, 
                    '⚠️ Слишком большое число! Рекомендуется не более 1000 сообщений.\n'
                    'Введите другое значение:'
                )
                return True
            
            storage.states[msg.chat.id]['message_limit'] = message_limit
            storage.states[msg.chat.id]['step'] = 'parser_select_message_type'
            
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.add(KeyboardButton('📝 Текстовое сообщение'), KeyboardButton('📤 Пересылка из канала'))
            kb.add(KeyboardButton('Отмена'))
            
            bot.send_message(
                msg.chat.id,
                '📨 Выберите тип сообщения для рассылки:',
                reply_markup=kb
            )
            return True
            
        except ValueError:
            bot.send_message(msg.chat.id, '❌ Введите корректное число.')
            return True
    
    # Выбор типа сообщения
    elif state == 'parser_select_message_type':
        if msg.text == '📝 Текстовое сообщение':
            storage.states[msg.chat.id]['is_forward'] = False
            storage.states[msg.chat.id]['step'] = 'parser_enter_broadcast_message'
            
            bot.send_message(
                msg.chat.id,
                '📝 Введите текстовое сообщение для рассылки:',
                reply_markup=cancel_keyboard()
            )
            return True
            
        elif msg.text == '📤 Пересылка из канала':
            storage.states[msg.chat.id]['is_forward'] = True
            storage.states[msg.chat.id]['step'] = 'parser_enter_forward_channel'
            
            bot.send_message(
                msg.chat.id,
                '📢 Введите ID или username канала:\n\n'
                'Например: @channelname или -1001234567890\n\n'
                'Бот возьмет последнее сообщение из этого канала и будет его пересылать.',
                reply_markup=cancel_keyboard()
            )
            return True
        else:
            bot.send_message(msg.chat.id, '❌ Неверный выбор. Выберите один из вариантов.')
            return True
    
    # Ввод ID канала для пересылки
    elif state == 'parser_enter_forward_channel':
        channel_id = msg.text.strip()
        session_name = storage.states[msg.chat.id]['session']
        
        # Проверяем канал и получаем последнее сообщение
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
                
                # Сохраняем channel_id в исходном формате (как ввел пользователь)
                # Это гарантирует, что мы сможем получить entity снова
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
            storage.states[msg.chat.id]['forward_from_chat_id'] = forward_from_chat_id
            storage.states[msg.chat.id]['forward_message_id'] = forward_message_id
            storage.states[msg.chat.id]['step'] = 'parser_enter_delay'
            
            bot.send_message(
                msg.chat.id,
                f'✅ Последнее сообщение получено!\n'
                f'Канал: {result}\n'
                f'ID сообщения: {forward_message_id}\n\n'
                f'⏱️ Введите задержку между сообщениями (в секундах):\n\n'
                f'Минимум: 3 секунды (рекомендуется для безопасности)\n'
                f'Рекомендуется: 5-10 секунд',
                reply_markup=cancel_keyboard()
            )
        else:
            bot.send_message(
                msg.chat.id,
                f'❌ Ошибка при получении сообщения из канала:\n{result}\n\n'
                f'Проверьте правильность ID канала и попробуйте снова.',
                reply_markup=cancel_keyboard()
            )
        return True
    
    # Ввод текстового сообщения
    elif state == 'parser_enter_broadcast_message':
        if not msg.text:
            bot.send_message(
                msg.chat.id,
                '❌ Пожалуйста, отправьте текстовое сообщение.',
                reply_markup=cancel_keyboard()
            )
            return True
        
        storage.states[msg.chat.id]['broadcast_message'] = msg.text
        storage.states[msg.chat.id]['step'] = 'parser_enter_delay'
        
        bot.send_message(
            msg.chat.id,
            '⏱️ Введите задержку между сообщениями (в секундах):\n\n'
            'Минимум: 3 секунды (рекомендуется для безопасности)\n'
            'Рекомендуется: 5-10 секунд',
            reply_markup=cancel_keyboard()
        )
        return True
    
    # Ввод задержки
    elif state == 'parser_enter_delay':
        try:
            delay = float(msg.text.strip())
            if delay < 3:
                bot.send_message(
                    msg.chat.id, 
                    '⚠️ Задержка меньше 3 секунд может привести к бану!\n'
                    'Введите значение не менее 3 секунд:'
                )
                return True
            
            state_data = storage.states[msg.chat.id]
            session_name = state_data['session']
            chat_id_to_parse = state_data['chat_id_to_parse']
            message_limit = state_data['message_limit']
            is_forward = state_data.get('is_forward', False)
            
            # Получаем данные сообщения в зависимости от типа
            if is_forward:
                forward_from_chat_id = state_data['forward_from_chat_id']
                forward_message_id = state_data['forward_message_id']
                broadcast_message = None
            else:
                broadcast_message = state_data['broadcast_message']
                forward_from_chat_id = None
                forward_message_id = None
            
            # Проверяем, не запущена ли уже рассылка для этого аккаунта
            if session_name in storage.tasks:
                bot.send_message(
                    msg.chat.id,
                    f'❌ Для аккаунта {session_name} уже запущена рассылка.',
                    reply_markup=main_keyboard()
                )
                storage.states.pop(msg.chat.id, None)
                return True
            
            # Запускаем воркер
            from ..workers.user_parser import parser_broadcast_worker
            
            stop_event = threading.Event()
            thread = threading.Thread(
                target=parser_broadcast_worker,
                args=(session_name, chat_id_to_parse, message_limit, broadcast_message, delay, stop_event, msg.chat.id, is_forward, forward_from_chat_id, forward_message_id)
            )
            thread.start()
            
            storage.add_task(session_name, thread, stop_event)
            
            message_type = '📤 Пересылка' if is_forward else '📝 Текстовое сообщение'
            bot.send_message(
                msg.chat.id,
                f'✅ Запущен парсинг и рассылка!\n\n'
                f'📱 Аккаунт: {session_name}\n'
                f'💬 Чат для парсинга: {chat_id_to_parse}\n'
                f'📊 Сообщений для анализа: {message_limit}\n'
                f'📨 Тип сообщения: {message_type}\n'
                f'⏱️ Задержка: {delay} сек\n\n'
                f'⏳ Сначала будет выполнен парсинг пользователей,\n'
                f'затем начнется рассылка.',
                reply_markup=main_keyboard()
            )
            
            storage.states.pop(msg.chat.id, None)
            return True
            
        except ValueError:
            bot.send_message(msg.chat.id, '❌ Введите корректное число.')
            return True
    
    return False


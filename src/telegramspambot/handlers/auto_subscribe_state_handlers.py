"""Обработчики состояний для автоподписки"""

import threading
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

from .. import storage
from ..keyboards import main_keyboard
from ..workers.auto_subscribe import auto_subscribe_worker


def handle_auto_select_session(msg, bot):
    chat_id = msg.chat.id
    text = msg.text.strip()
    if text not in storage.accounts:
        bot.send_message(chat_id, '❌ Аккаунт не найден. Выберите существующий аккаунт:', reply_markup=main_keyboard())
        return
    storage.states[chat_id] = {
        'step': 'auto_target_chats',
        'session': text
    }
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('Отмена'))
    bot.send_message(chat_id, 'Укажите целевые чаты для автоподписки (каждый с новой строки):', reply_markup=kb)


def handle_auto_target_chats_input(msg, bot):
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
            bot.send_message(chat_id, 'Список чатов пуст. Введите чаты (каждый с новой строки):', reply_markup=kb)
            return

        state['target_chats'] = chats
        state['step'] = 'auto_message'
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(chat_id, 'Введите текст сообщения для рассылки:', reply_markup=kb)
    except Exception as e:
        bot.send_message(chat_id, f'❌ Ошибка при обработке списка чатов: {e}', reply_markup=main_keyboard())
        storage.states.pop(chat_id)


def handle_auto_message(msg, bot):
    chat_id = msg.chat.id
    state = storage.states[chat_id]
    state['auto_text'] = msg.text.strip()
    state['step'] = 'auto_delay'
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('Отмена'))
    bot.send_message(chat_id, 'Введите задержку между проверками (сек):', reply_markup=kb)


def handle_auto_delay(msg, bot):
    chat_id = msg.chat.id
    state = storage.states[chat_id]
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
        storage.tasks[f"auto::{session_name}"] = (thread, stop_event)
        thread.start()
        bot.send_message(chat_id, f'▶️ Автоподписка запущена для {session_name}', reply_markup=main_keyboard())
        storage.states.pop(chat_id)
    except Exception:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(chat_id, '❌ Неверное значение. Введите число больше 0:', reply_markup=kb)


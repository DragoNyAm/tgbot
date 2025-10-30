"""Обработчики состояний для настроек"""

from .. import storage
from ..keyboards import main_keyboard, sessions_keyboard, settings_keyboard, logging_settings_keyboard


def handle_settings_menu(msg, bot):
    chat_id = msg.chat.id
    state = storage.states[chat_id]
    session_name = state['session']
    
    if msg.text == '📝 Настройки логирования':
        state['step'] = 'logging_settings'
        bot.send_message(chat_id, 'Настройки логирования:', reply_markup=logging_settings_keyboard())
    elif msg.text == 'Назад':
        storage.states[chat_id] = {'step': 'select_account_settings', 'action': 'session_settings'}
        bot.send_message(chat_id, 'Выберите аккаунт для настройки:', reply_markup=sessions_keyboard())


def handle_logging_settings(msg, bot):
    chat_id = msg.chat.id
    state = storage.states[chat_id]
    session_name = state['session']
    
    if session_name not in storage.settings:
        import copy
        from ..config import DEFAULT_SETTINGS
        storage.settings[session_name] = copy.deepcopy(DEFAULT_SETTINGS)
    
    if msg.text == '✅ Включить логирование':
        storage.settings[session_name]['logging']['enabled'] = True
        bot.send_message(chat_id, '✅ Логирование включено', reply_markup=logging_settings_keyboard())
    elif msg.text == '❌ Отключить логирование':
        storage.settings[session_name]['logging']['enabled'] = False
        bot.send_message(chat_id, '❌ Логирование отключено', reply_markup=logging_settings_keyboard())
    elif msg.text == '📋 Полное логирование':
        storage.settings[session_name]['logging']['level'] = 'full'
        bot.send_message(chat_id, '✅ Установлено полное логирование', reply_markup=logging_settings_keyboard())
    elif msg.text == '📝 Минимальное логирование':
        storage.settings[session_name]['logging']['level'] = 'minimal'
        bot.send_message(chat_id, '✅ Установлено минимальное логирование', reply_markup=logging_settings_keyboard())
    elif msg.text == 'Назад':
        state['step'] = 'session_settings'
        bot.send_message(chat_id, 'Настройки сессии:', reply_markup=settings_keyboard())
    
    storage.save_accounts()


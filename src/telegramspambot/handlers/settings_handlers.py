"""Обработчики настроек"""

from ..keyboards import main_keyboard, sessions_keyboard
from .. import storage


def register_settings_handlers(bot):
    """Регистрация обработчиков настроек"""
    
    @bot.message_handler(func=lambda m: m.text == '⚙️ Настройки сессии')
    def handle_session_settings(msg):
        if not storage.accounts:
            bot.send_message(msg.chat.id, 'Нет аккаунтов для настройки.', reply_markup=main_keyboard())
            return
        
        storage.states[msg.chat.id] = {'step': 'select_account_settings', 'action': 'session_settings'}
        bot.send_message(msg.chat.id, 'Выберите аккаунт для настройки:', reply_markup=sessions_keyboard())


"""Обработчики автоподписки"""

from ..keyboards import main_keyboard, sessions_keyboard
from .. import storage


def register_auto_subscribe_handlers(bot):
    """Регистрация обработчиков автоподписки"""
    
    @bot.message_handler(func=lambda m: m.text == '🤖 Автоподписка')
    def handle_auto_subscribe_start(msg):
        if not storage.accounts:
            bot.send_message(msg.chat.id, 'Нет аккаунтов для автоподписки.', reply_markup=main_keyboard())
            return
        storage.states[msg.chat.id] = {'step': 'auto_select_session'}
        bot.send_message(msg.chat.id, 'Выберите аккаунт для автоподписки:', reply_markup=sessions_keyboard())


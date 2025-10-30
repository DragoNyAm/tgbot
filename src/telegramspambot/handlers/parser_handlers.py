"""Обработчики парсинга пользователей"""

from ..keyboards import main_keyboard, sessions_keyboard
from .. import storage


def register_parser_handlers(bot):
    """Регистрация обработчиков парсинга"""
    
    @bot.message_handler(func=lambda m: m.text == '🔍 Спам по спаршенным пользователям')
    def handle_parser_spam(msg):
        """Начало процесса парсинга и рассылки"""
        if not storage.accounts:
            bot.send_message(msg.chat.id, '❌ Нет добавленных аккаунтов.', reply_markup=main_keyboard())
        else:
            storage.states[msg.chat.id] = {'step': 'parser_select_session'}
            bot.send_message(
                msg.chat.id, 
                '📱 Выберите аккаунт для парсинга и рассылки:',
                reply_markup=sessions_keyboard()
            )


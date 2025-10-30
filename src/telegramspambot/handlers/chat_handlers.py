"""Обработчики для работы с чатами"""

from ..keyboards import main_keyboard, sessions_keyboard
from .. import storage


def register_chat_handlers(bot):
    """Регистрация обработчиков для работы с чатами"""
    
    @bot.message_handler(func=lambda m: m.text == '📋 Просмотр чатов')
    def handle_view_chats(msg):
        if not storage.accounts:
            bot.send_message(msg.chat.id, 'Нет аккаунтов для просмотра чатов.', reply_markup=main_keyboard())
            return
        
        storage.states[msg.chat.id] = {'step': 'select_account_chats'}
        bot.send_message(msg.chat.id, 'Выберите аккаунт для просмотра чатов:', reply_markup=sessions_keyboard())
    
    @bot.message_handler(func=lambda m: m.text == '➕ Вступить в чаты')
    def handle_join_chats(msg):
        if not storage.accounts:
            bot.send_message(msg.chat.id, 'Нет аккаунтов для вступления в чаты.', reply_markup=main_keyboard())
            return
        
        storage.states[msg.chat.id] = {'step': 'select_account_join'}
        bot.send_message(msg.chat.id, 'Выберите аккаунт для вступления в чаты:', reply_markup=sessions_keyboard())


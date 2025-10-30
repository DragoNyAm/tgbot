"""Основные обработчики меню"""

from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from ..keyboards import main_keyboard, sessions_keyboard
from .. import storage


def register_main_handlers(bot):
    """Регистрация основных обработчиков"""
    
    @bot.message_handler(commands=['start', 'help'])
    def cmd_start(msg):
        bot.send_message(msg.chat.id, '👋 Выберите действие:', reply_markup=main_keyboard())
    
    @bot.message_handler(func=lambda m: m.text == '➕ Добавить аккаунт')
    def handle_add_account(msg):
        storage.states[msg.chat.id] = {'step': 'api_id'}
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton('Отмена'))
        bot.send_message(msg.chat.id, 'Введите api_id:', reply_markup=kb)
    
    @bot.message_handler(func=lambda m: m.text == '➖ Удалить аккаунт')
    def handle_remove_account_start(msg):
        if not storage.accounts:
            bot.send_message(msg.chat.id, 'Нет аккаунтов для удаления.', reply_markup=main_keyboard())
        else:
            storage.states[msg.chat.id] = {'step': 'remove'}
            bot.send_message(msg.chat.id, 'Выберите аккаунт для удаления:', reply_markup=sessions_keyboard())
    
    @bot.message_handler(func=lambda m: m.text == '▶️ Запустить рассылку')
    def handle_start_broadcast(msg):
        if not storage.accounts:
            bot.send_message(msg.chat.id, 'Нет аккаунтов.', reply_markup=main_keyboard())
        else:
            storage.states[msg.chat.id] = {'step': 'b_select_session'}
            bot.send_message(msg.chat.id, 'Выберите сессию для рассылки:', reply_markup=sessions_keyboard())
    
    @bot.message_handler(func=lambda m: m.text == '⏹️ Остановить рассылку')
    def handle_stop_broadcast(msg):
        if not storage.tasks:
            bot.send_message(msg.chat.id, 'Нет активных рассылок.', reply_markup=main_keyboard())
        else:
            storage.states[msg.chat.id] = {'step': 'stop'}
            bot.send_message(msg.chat.id, 'Выберите сессию для остановки:', reply_markup=sessions_keyboard())
    
    @bot.message_handler(func=lambda m: m.text == 'Отмена')
    def handle_cancel(msg):
        storage.states.pop(msg.chat.id, None)
        bot.send_message(msg.chat.id, 'Операция отменена.', reply_markup=main_keyboard())


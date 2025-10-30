"""Обработчики управления аккаунтами"""

import asyncio
import threading
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from telethon.sync import TelegramClient
from telethon.errors import SessionPasswordNeededError

from ..keyboards import main_keyboard, sessions_keyboard, cancel_keyboard
from .. import storage
from ..config import DEVICE_CONFIG


def log(message):
    """Простое логирование"""
    print(f"[Bot] {message}")


def register_account_handlers(bot):
    """Регистрация обработчиков управления аккаунтами"""
    
    @bot.message_handler(func=lambda m: m.text == '👤 Управление аккаунтом')
    def handle_account_management(msg):
        chat_id = msg.chat.id
        log('👤 Управление аккаунтом')
        
        if not storage.accounts:
            bot.send_message(chat_id, '❌ Нет добавленных аккаунтов', reply_markup=main_keyboard())
        else:
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add(KeyboardButton('⚙️ Настройки аккаунта'))
            markup.add(KeyboardButton('🏠 Главное меню'))
            bot.send_message(chat_id, 'Выберите действие:', reply_markup=markup)
    
    @bot.message_handler(func=lambda m: m.text == '🏠 Главное меню')
    def handle_main_menu(msg):
        chat_id = msg.chat.id
        log('🏠 Главное меню')
        storage.states.pop(chat_id, None)
        bot.send_message(chat_id, 'Главное меню:', reply_markup=main_keyboard())
    
    @bot.message_handler(func=lambda m: m.text == '➕ Добавить аккаунт')
    def handle_add_account(msg):
        chat_id = msg.chat.id
        log('➕ Добавить аккаунт')
        
        storage.states[chat_id] = {'step': 'api_id'}
        bot.send_message(
            chat_id, 
            'Введите api_id:', 
            reply_markup=cancel_keyboard()
        )
    
    @bot.message_handler(func=lambda m: m.text == '❌ Удалить аккаунт')
    def handle_delete_account(msg):
        chat_id = msg.chat.id
        log('❌ Удалить аккаунт')
        
        if not storage.accounts:
            bot.send_message(chat_id, '❌ Нет добавленных аккаунтов', reply_markup=main_keyboard())
            return
        
        storage.states[chat_id] = {'step': 'remove'}
        bot.send_message(
            chat_id, 
            'Выберите аккаунт для удаления:', 
            reply_markup=sessions_keyboard()
        )
    
    @bot.message_handler(func=lambda m: m.text == '⚙️ Настройки аккаунта')
    def handle_settings_account(msg):
        chat_id = msg.chat.id
        log('⚙️ Настройки аккаунта')
        
        if not storage.accounts:
            bot.send_message(chat_id, '❌ Нет добавленных аккаунтов', reply_markup=main_keyboard())
            return
        
        storage.states[chat_id] = {'step': 'select_account_settings', 'action': 'account_management'}
        bot.send_message(
            chat_id,
            'Выберите аккаунт для настройки:',
            reply_markup=sessions_keyboard()
        )


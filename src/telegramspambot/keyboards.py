"""Клавиатуры для Telegram бота"""

from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from . import storage


def main_keyboard():
    """Главное меню"""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('➕ Добавить аккаунт'), KeyboardButton('➖ Удалить аккаунт'))
    kb.add(KeyboardButton('▶️ Запустить рассылку'), KeyboardButton('⏹️ Остановить рассылку'))
    kb.add(KeyboardButton('👤 Управление аккаунтом'), KeyboardButton('📋 Просмотр чатов'))
    kb.add(KeyboardButton('➕ Вступить в чаты'), KeyboardButton('⚙️ Настройки сессии'))
    kb.add(KeyboardButton('🤖 Автоподписка'), KeyboardButton('🔍 Спам по спаршенным пользователям'))
    return kb


def sessions_keyboard():
    """Клавиатура выбора сессии"""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    for name in storage.accounts.keys():
        kb.add(KeyboardButton(name))
    kb.add(KeyboardButton('Отмена'))
    return kb


def account_settings_keyboard():
    """Клавиатура настроек аккаунта"""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('📝 Изменить имя'), KeyboardButton('👤 Изменить username'))
    kb.add(KeyboardButton('📋 Изменить био'), KeyboardButton('🖼 Изменить аватар'))
    kb.add(KeyboardButton('Назад'))
    return kb


def chat_type_keyboard():
    """Клавиатура типов чатов"""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('📢 Все каналы'), KeyboardButton('👥 Все группы'))
    kb.add(KeyboardButton('💬 Все личные чаты'), KeyboardButton('📋 Все чаты'))
    kb.add(KeyboardButton('➕ Добавить чаты вручную'), KeyboardButton('Отмена'))
    return kb


def chat_selection_keyboard(chats_info):
    """Клавиатура выбора чатов"""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    for chat in chats_info:
        # Создаем кнопку с типом чата и его названием
        chat_type = chat.split(':')[0]
        chat_name = chat.split(':')[1].split('\n')[0].strip()
        button_text = f"{chat_type}: {chat_name}"
        kb.add(KeyboardButton(button_text))
    kb.add(KeyboardButton('✅ Подтвердить выбор'), KeyboardButton('Отмена'))
    return kb


def settings_keyboard():
    """Клавиатура настроек сессии"""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('📝 Настройки логирования'))
    kb.add(KeyboardButton('Назад'))
    return kb


def logging_settings_keyboard():
    """Клавиатура настроек логирования"""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('✅ Включить логирование'), KeyboardButton('❌ Отключить логирование'))
    kb.add(KeyboardButton('📋 Полное логирование'), KeyboardButton('📝 Минимальное логирование'))
    kb.add(KeyboardButton('Назад'))
    return kb


def broadcast_chats_method_keyboard():
    """Клавиатура методов выбора чатов для рассылки"""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('Использовать сохраненную конфигурацию'))
    kb.add(KeyboardButton('Выбрать по типу'))
    kb.add(KeyboardButton('Ввести вручную'))
    kb.add(KeyboardButton('Отмена'))
    return kb


def configs_keyboard(session_name):
    """Клавиатура конфигураций для сессии"""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    if session_name in storage.configs and storage.configs[session_name]:
        for config_name in storage.configs[session_name].keys():
            kb.add(KeyboardButton(config_name))
    kb.add(KeyboardButton('Назад'), KeyboardButton('Отмена'))
    return kb


def save_config_keyboard():
    """Клавиатура для подтверждения сохранения конфигурации"""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('Да'), KeyboardButton('Нет'))
    kb.add(KeyboardButton('Отмена'))
    return kb


def cancel_keyboard():
    """Простая клавиатура с кнопкой Отмена"""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('Отмена'))
    return kb


def broadcast_chats_method_keyboard():
    """Клавиатура методов выбора чатов для рассылки"""
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('Использовать сохраненную конфигурацию'))
    kb.add(KeyboardButton('Выбрать по типу'))
    kb.add(KeyboardButton('Ввести вручную'))
    kb.add(KeyboardButton('Отмена'))
    return kb

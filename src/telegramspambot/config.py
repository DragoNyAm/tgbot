"""Конфигурация и константы приложения"""

import os
from pathlib import Path

# Токен бота
BOT_TOKEN = os.getenv('BOT_TOKEN', '7990277461:AAEhVvRmFKch7e1YrGF-fkuLqC6y4-4PMrM')

# Директории
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / 'data'

# Создаем директории если их нет
DATA_DIR.mkdir(exist_ok=True)

# Файлы данных
ACCOUNTS_FILE = str(DATA_DIR / 'accounts.json')
CONFIGS_FILE = str(DATA_DIR / 'session_configs.json')
SETTINGS_FILE = str(DATA_DIR / 'session_settings.json')

# Параметры устройства для Telethon
DEVICE_CONFIG = {
    'device_model': "iPhone 13 Pro Max",
    'system_version': "4.16.30-vxCUSTOM",
    'app_version': "8.4",
    'lang_code': "en",
    'system_lang_code': "en-US"
}

# Настройки по умолчанию
DEFAULT_SETTINGS = {
    'logging': {
        'enabled': True,
        'level': 'full',  # 'full' or 'minimal'
        'show_errors': True,
        'show_success': True,
        'show_progress': True
    },
    'limits': {
        'messages_per_minute': 20,  # Telegram limit
        'messages_per_hour': 500,   # Telegram limit
        'messages_per_day': 2000,   # Telegram limit
        'delay_between_messages': 3  # Minimum delay in seconds
    },
}


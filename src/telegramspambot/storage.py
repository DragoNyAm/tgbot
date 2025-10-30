"""Управление хранением данных"""

import os
import json
import copy
from .config import ACCOUNTS_FILE, CONFIGS_FILE, SETTINGS_FILE, DEFAULT_SETTINGS

# Глобальные переменные для хранения данных
accounts = {}  # session_name -> {api_id, api_hash, string_session, phone}
configs = {}   # session_name -> config_name -> [chat_ids]
settings = {}  # session_name -> settings
tasks = {}     # session_name -> (thread, stop_event)
states = {}    # chat_id -> state


def _create_empty_file(filepath):
    """Создать пустой JSON файл если его нет"""
    if not os.path.exists(filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({}, f)


def load_accounts():
    """Загрузить все данные из файлов"""
    global accounts, configs, settings
    
    # Создаем файлы если их нет
    _create_empty_file(ACCOUNTS_FILE)
    _create_empty_file(CONFIGS_FILE)
    _create_empty_file(SETTINGS_FILE)
    
    with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
        content = f.read().strip()
        accounts = json.loads(content) if content else {}
    
    with open(CONFIGS_FILE, 'r', encoding='utf-8') as f:
        content = f.read().strip()
        configs = json.loads(content) if content else {}
    
    with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
        content = f.read().strip()
        settings = json.loads(content) if content else {}
    
    # Ensure all sessions have complete settings
    for session in accounts:
        # Добавляем string_session если его нет (для обратной совместимости)
        if 'string_session' not in accounts[session]:
            accounts[session]['string_session'] = ''
        
        if session not in settings:
            settings[session] = copy.deepcopy(DEFAULT_SETTINGS)
        else:
            # Merge with default settings to ensure all keys exist
            for category, default_values in DEFAULT_SETTINGS.items():
                if category not in settings[session]:
                    settings[session][category] = copy.deepcopy(default_values)
                else:
                    # Merge individual settings within category
                    for key, default_value in default_values.items():
                        if key not in settings[session][category]:
                            settings[session][category][key] = default_value
        
        # Ensure all sessions have a configs entry
        if session not in configs:
            configs[session] = {}


def save_accounts():
    """Сохранить все данные в файлы"""
    global accounts, configs, settings
    
    with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)
    
    with open(CONFIGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(configs, f, indent=2, ensure_ascii=False)
    
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def add_account(name, api_id, api_hash, phone, string_session=''):
    """Добавить новый аккаунт"""
    global accounts, settings, configs
    
    accounts[name] = {
        'api_id': api_id,
        'api_hash': api_hash,
        'phone': phone,
        'string_session': string_session
    }
    
    # Инициализируем настройки и конфиги
    if name not in settings:
        settings[name] = copy.deepcopy(DEFAULT_SETTINGS)
    if name not in configs:
        configs[name] = {}
    
    save_accounts()


def remove_account(name):
    """Удалить аккаунт"""
    global accounts, settings, configs, tasks
    
    if name in accounts:
        del accounts[name]
    if name in settings:
        del settings[name]
    if name in configs:
        del configs[name]
    if name in tasks:
        # Останавливаем задачу если она запущена
        _, stop_event = tasks[name]
        stop_event.set()
        del tasks[name]
    
    save_accounts()


def get_account(name):
    """Получить данные аккаунта"""
    return accounts.get(name)


def add_task(name, thread, stop_event):
    """Добавить задачу"""
    global tasks
    tasks[name] = (thread, stop_event)


def remove_task(name):
    """Удалить задачу"""
    global tasks
    if name in tasks:
        del tasks[name]


def stop_task(name):
    """Остановить задачу"""
    global tasks
    if name in tasks:
        _, stop_event = tasks[name]
        stop_event.set()


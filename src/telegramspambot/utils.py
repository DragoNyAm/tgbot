"""Утилиты и вспомогательные функции"""

import asyncio
from langdetect import detect, LangDetectException
from .config import DEFAULT_SETTINGS
from . import storage


def log_message(chat_id, session_name, message, level='info'):
    """Логирование сообщения с учетом настроек сессии
    
    Args:
        chat_id: ID чата для отправки сообщения
        session_name: Имя сессии
        message: Текст сообщения
        level: Уровень логирования ('info', 'error', 'success', 'progress')
    """
    from .bot_instance import bot
    
    if session_name not in storage.settings:
        storage.settings[session_name] = DEFAULT_SETTINGS.copy()
    
    session_settings = storage.settings[session_name]['logging']
    
    if not session_settings['enabled']:
        return
    
    if level == 'error' and not session_settings['show_errors']:
        return
    
    if level == 'success' and not session_settings['show_success']:
        return
    
    if level == 'progress' and not session_settings['show_progress']:
        return
    
    if session_settings['level'] == 'minimal' and level == 'progress':
        return
    
    bot.send_message(chat_id, message)


async def handle_persistent_timestamp_error(client, chat_id, session_name, operation_name="операция", max_retries=5):
    """Обрабатывает ошибку PersistentTimestampOutdatedError с улучшенной логикой восстановления
    
    Args:
        client: Telethon клиент
        chat_id: ID чата для логирования
        session_name: Имя сессии
        operation_name: Название операции для логов
        max_retries: Максимальное количество попыток
        
    Returns:
        bool: True если восстановление успешно, False иначе
    """
    for attempt in range(max_retries):
        try:
            log_message(chat_id, session_name, f"⚠️ Ошибка синхронизации Telegram при {operation_name} (попытка {attempt + 1}/{max_retries})", 'progress')
            
            # Корректно отключаемся
            try:
                await client.disconnect()
            except:
                pass
            
            # Увеличиваем время ожидания с каждой попыткой
            wait_time = 5 + attempt * 3
            log_message(chat_id, session_name, f"⏳ Ожидание {wait_time} секунд перед переподключением...", 'progress')
            await asyncio.sleep(wait_time)
            
            # Переподключаемся
            await client.connect()
            
            # Проверяем авторизацию
            if not await client.is_user_authorized():
                log_message(chat_id, session_name, f"❌ Ошибка авторизации после переподключения", 'error')
                continue
            
            # Пробуем разные способы восстановления синхронизации
            recovery_methods = [
                lambda: client.get_dialogs(),
                lambda: client.get_me(),
                lambda: client.get_entity('me')
            ]
            
            recovery_success = False
            for method in recovery_methods:
                try:
                    await method()
                    recovery_success = True
                    break
                except Exception as method_error:
                    log_message(chat_id, session_name, f"⚠️ Метод восстановления не сработал: {str(method_error)}", 'progress')
                    continue
            
            if recovery_success:
                # Дополнительная пауза для стабилизации
                await asyncio.sleep(3)
                log_message(chat_id, session_name, f"✅ Синхронизация восстановлена (попытка {attempt + 1})", 'success')
                return True
            else:
                log_message(chat_id, session_name, f"❌ Не удалось восстановить синхронизацию (попытка {attempt + 1})", 'error')
            
        except Exception as e:
            log_message(chat_id, session_name, f"❌ Попытка {attempt + 1} восстановления не удалась: {str(e)}", 'error')
            
        # Дополнительная пауза перед следующей попыткой
        if attempt < max_retries - 1:
            await asyncio.sleep(5)
    
    log_message(chat_id, session_name, f"❌ Все попытки восстановления синхронизации исчерпаны", 'error')
    return False


def is_russian_phone(phone):
    """Проверяет, является ли номер телефона русским
    
    Args:
        phone: Номер телефона (строка)
        
    Returns:
        bool: True если номер русский, False иначе
    """
    if not phone:
        return False
    
    # Убираем все символы кроме цифр
    phone = ''.join(filter(str.isdigit, phone))
    
    # Проверяем, начинается ли номер с +7 или 8 (российские коды)
    if phone.startswith('7') or phone.startswith('8'):
        return True
    
    return False


def detect_language(text):
    """Определяет язык текста
    
    Args:
        text: Текст для анализа
        
    Returns:
        str: Код языка ('ru', 'en', и т.д.) или None при ошибке
    """
    if not text or len(text.strip()) < 3:
        return None
    
    try:
        # Удаляем emojis и специальные символы для более точного определения
        cleaned_text = ''.join(char for char in text if char.isalpha() or char.isspace())
        if len(cleaned_text.strip()) < 3:
            return None
        
        language = detect(cleaned_text)
        return language
    except LangDetectException:
        return None


def is_non_russian_text(text):
    """Проверяет, написан ли текст не на русском языке
    
    Args:
        text: Текст для анализа
        
    Returns:
        bool: True если текст не на русском, False если на русском или не удалось определить
    """
    lang = detect_language(text)
    if lang is None:
        return False
    
    return lang != 'ru'


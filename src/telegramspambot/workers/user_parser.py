"""Воркер для парсинга пользователей и рассылки"""

import asyncio
import time
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import PersistentTimestampOutdatedError
from telethon.tl.types import PeerUser, PeerChannel, PeerChat, User

from ..config import DEVICE_CONFIG
from .. import storage
from ..utils import log_message, handle_persistent_timestamp_error, is_russian_phone, is_non_russian_text


async def parse_users_from_chat(client, chat_id_to_parse, message_limit, bot_chat_id, session_name):
    """Парсинг пользователей из чата с фильтрацией по языку/номеру
    
    Args:
        client: Telethon клиент
        chat_id_to_parse: ID чата для парсинга
        message_limit: Количество сообщений для анализа
        bot_chat_id: ID чата для отправки логов
        session_name: Имя сессии
        
    Returns:
        list: Список ID пользователей, которые прошли фильтрацию
    """
    filtered_users = []
    user_messages = {}  # user_id -> последнее сообщение
    
    try:
        log_message(bot_chat_id, session_name, f"⏳ Начинаю парсинг чата {chat_id_to_parse}...", 'progress')
        
        # Получаем entity чата
        try:
            if isinstance(chat_id_to_parse, str):
                if chat_id_to_parse.startswith('-100'):
                    # Супергруппа или канал
                    chat_id_int = int(chat_id_to_parse[4:])
                    chat_entity = await client.get_entity(PeerChannel(chat_id_int))
                elif chat_id_to_parse.startswith('-'):
                    # Обычная группа
                    chat_id_int = int(chat_id_to_parse[1:])
                    chat_entity = await client.get_entity(PeerChat(chat_id_int))
                else:
                    # Username или другой формат - пусть API сам определит
                    chat_entity = await client.get_entity(chat_id_to_parse)
            else:
                # Числовой ID
                if str(chat_id_to_parse).startswith('-100'):
                    # Супергруппа или канал
                    chat_entity = await client.get_entity(PeerChannel(int(str(abs(chat_id_to_parse))[3:])))
                elif chat_id_to_parse < 0:
                    # Обычная группа
                    chat_entity = await client.get_entity(PeerChat(abs(chat_id_to_parse)))
                else:
                    # Username или ID пользователя
                    chat_entity = await client.get_entity(chat_id_to_parse)
        except Exception as e:
            log_message(bot_chat_id, session_name, f"❌ Не удалось получить информацию о чате: {str(e)}", 'error')
            return []
        
        log_message(bot_chat_id, session_name, f"✅ Чат найден: {getattr(chat_entity, 'title', 'Unknown')}", 'success')
        
        # Получаем сообщения
        log_message(bot_chat_id, session_name, f"⏳ Получаю последние {message_limit} сообщений...", 'progress')
        messages = await client.get_messages(chat_entity, limit=message_limit)
        
        log_message(bot_chat_id, session_name, f"✅ Получено {len(messages)} сообщений", 'success')
        
        # Собираем сообщения от пользователей
        for message in messages:
            if message.sender_id and not message.sender_id in user_messages:
                # Сохраняем только первое (самое свежее) сообщение от каждого пользователя
                if message.text:
                    user_messages[message.sender_id] = message.text
        
        log_message(bot_chat_id, session_name, f"✅ Найдено {len(user_messages)} уникальных пользователей", 'success')
        log_message(bot_chat_id, session_name, f"⏳ Начинаю фильтрацию пользователей...", 'progress')
        
        # Фильтруем пользователей
        processed = 0
        for user_id, user_text in user_messages.items():
            processed += 1
            
            try:
                # Получаем информацию о пользователе
                user = await client.get_entity(PeerUser(user_id))
                
                # Проверяем, является ли это пользователем (не ботом)
                if not isinstance(user, User):
                    continue
                
                if user.bot:
                    continue
                
                # Проверяем номер телефона если он открыт
                if user.phone:
                    if is_russian_phone(user.phone):
                        # Русский номер - пропускаем
                        log_message(bot_chat_id, session_name, 
                                  f"🇷🇺 Пользователь {user_id} ({user.first_name or 'Unknown'}) имеет русский номер - пропущен", 
                                  'progress')
                        continue
                    else:
                        # Не русский номер - добавляем
                        filtered_users.append(user_id)
                        log_message(bot_chat_id, session_name, 
                                  f"✅ Пользователь {user_id} ({user.first_name or 'Unknown'}) добавлен (иностранный номер)", 
                                  'success')
                        continue
                
                # Номер скрыт - проверяем язык текста
                if is_non_russian_text(user_text):
                    filtered_users.append(user_id)
                    log_message(bot_chat_id, session_name, 
                              f"✅ Пользователь {user_id} ({user.first_name or 'Unknown'}) добавлен (не русский язык)", 
                              'success')
                else:
                    log_message(bot_chat_id, session_name, 
                              f"🇷🇺 Пользователь {user_id} ({user.first_name or 'Unknown'}) пишет на русском - пропущен", 
                              'progress')
                
                # Небольшая задержка чтобы не получить флуд
                if processed % 10 == 0:
                    await asyncio.sleep(1)
                    
            except Exception as e:
                log_message(bot_chat_id, session_name, 
                          f"⚠️ Ошибка при обработке пользователя {user_id}: {str(e)}", 
                          'progress')
                continue
        
        log_message(bot_chat_id, session_name, 
                  f"✅ Фильтрация завершена! Найдено {len(filtered_users)} не русских пользователей из {len(user_messages)}", 
                  'success')
        
    except PersistentTimestampOutdatedError:
        log_message(bot_chat_id, session_name, "⚠️ Ошибка синхронизации при парсинге", 'progress')
        recovery_success = await handle_persistent_timestamp_error(client, bot_chat_id, session_name, "парсинг чата")
        if not recovery_success:
            log_message(bot_chat_id, session_name, "❌ Не удалось восстановить синхронизацию", 'error')
            return []
    except Exception as e:
        log_message(bot_chat_id, session_name, f"❌ Ошибка при парсинге: {str(e)}", 'error')
        return []
    
    return filtered_users


def parser_broadcast_worker(name, chat_id_to_parse, message_limit, broadcast_message, delay_msg, stop_event, bot_chat_id, is_forward=False, forward_from_chat_id=None, forward_message_id=None):
    """Воркер для парсинга пользователей и рассылки по ним
    
    Args:
        name: Имя сессии
        chat_id_to_parse: ID чата для парсинга
        message_limit: Количество сообщений для анализа
        broadcast_message: Текст сообщения (если не пересылка)
        delay_msg: Задержка между сообщениями
        stop_event: Событие остановки
        bot_chat_id: ID чата бота для логов
        is_forward: Флаг пересылки
        forward_from_chat_id: ID чата с пересланным сообщением
        forward_message_id: ID пересланного сообщения
    """
    async def run():
        acc = storage.accounts[name]
        client = TelegramClient(
            StringSession(acc['string_session']),
            acc['api_id'], acc['api_hash'],
            **DEVICE_CONFIG
        )
        await client.start()
        
        try:
            # Получаем диалоги для кэширования
            log_message(bot_chat_id, name, "⏳ Инициализация...", 'progress')
            try:
                await client.get_dialogs()
                log_message(bot_chat_id, name, "✅ Инициализация завершена", 'success')
            except PersistentTimestampOutdatedError:
                log_message(bot_chat_id, name, "⚠️ Ошибка синхронизации при инициализации", 'progress')
                recovery_success = await handle_persistent_timestamp_error(client, bot_chat_id, name, "инициализация")
                if not recovery_success:
                    log_message(bot_chat_id, name, "❌ Не удалось восстановить синхронизацию. Останавливаю.", 'error')
                    return
            
            # Если это пересылка - получаем и кэшируем entity источника
            if is_forward:
                try:
                    source_entity = await client.get_entity(forward_from_chat_id)
                    log_message(bot_chat_id, name, f"✅ Канал для пересылки получен", 'success')
                except Exception as e:
                    log_message(bot_chat_id, name, f"❌ Не удалось получить канал для пересылки: {str(e)}", 'error')
                    return
            else:
                source_entity = None
            
            # Парсим пользователей
            users_to_message = await parse_users_from_chat(
                client, chat_id_to_parse, message_limit, bot_chat_id, name
            )
            
            if not users_to_message:
                log_message(bot_chat_id, name, "❌ Не найдено пользователей для рассылки", 'error')
                return
            
            log_message(bot_chat_id, name, 
                      f"✅ Готово к рассылке! Начинаю отправку {len(users_to_message)} пользователям...", 
                      'success')
            
            # Начинаем рассылку
            messages_sent = 0
            last_message_time = 0
            
            for user_id in users_to_message:
                if stop_event.is_set():
                    log_message(bot_chat_id, name, "⏹️ Рассылка остановлена пользователем", 'progress')
                    break
                
                # Проверяем лимиты
                current_time = time.time()
                time_since_last = current_time - last_message_time
                min_delay = storage.settings[name]['limits']['delay_between_messages']
                
                if time_since_last < min_delay:
                    await asyncio.sleep(min_delay - time_since_last)
                
                try:
                    # Отправляем или пересылаем сообщение
                    user_entity = await client.get_entity(PeerUser(user_id))
                    
                    if is_forward:
                        # Пересылаем сообщение из оригинального источника (source_entity уже получен)
                        try:
                            # Пересылаем сообщение: await client.forward_messages(куда, ID_сообщения, откуда)
                            await client.forward_messages(user_entity, forward_message_id, source_entity)
                        except Exception as forward_error:
                            log_message(bot_chat_id, name, 
                                      f"⚠️ Ошибка при пересылке: {str(forward_error)}", 
                                      'progress')
                            # Если пересылка не удалась - пробуем отправить как обычное сообщение
                            raise
                    else:
                        # Отправляем текстовое сообщение
                        await client.send_message(user_entity, broadcast_message)
                    
                    messages_sent += 1
                    last_message_time = time.time()
                    
                    action = "переслано" if is_forward else "отправлено"
                    log_message(bot_chat_id, name, 
                              f"✅ Сообщение {messages_sent}/{len(users_to_message)} {action} пользователю {user_id}", 
                              'success')
                    
                    # Проверяем лимиты
                    if messages_sent >= storage.settings[name]['limits']['messages_per_minute']:
                        log_message(bot_chat_id, name, 
                                  "⏳ Достигнут лимит сообщений в минуту. Ожидание 60 секунд...", 
                                  'progress')
                        await asyncio.sleep(60)
                        messages_sent = 0
                    
                except PersistentTimestampOutdatedError:
                    log_message(bot_chat_id, name, f"⚠️ Ошибка синхронизации при отправке пользователю {user_id}", 'progress')
                    recovery_success = await handle_persistent_timestamp_error(client, bot_chat_id, name, f"отправка {user_id}")
                    if recovery_success:
                        # Пробуем снова
                        try:
                            if is_forward:
                                # source_entity уже получен ранее
                                await client.forward_messages(user_entity, forward_message_id, source_entity)
                            else:
                                await client.send_message(user_entity, broadcast_message)
                            messages_sent += 1
                            last_message_time = time.time()
                            action = "переслано" if is_forward else "отправлено"
                            log_message(bot_chat_id, name, 
                                      f"✅ Сообщение {action} пользователю {user_id} после восстановления", 
                                      'success')
                        except Exception as retry_error:
                            log_message(bot_chat_id, name, 
                                      f"❌ Не удалось отправить пользователю {user_id}: {str(retry_error)}", 
                                      'error')
                    continue
                    
                except Exception as e:
                    error_msg = str(e)
                    log_message(bot_chat_id, name, 
                              f"❌ Ошибка при отправке пользователю {user_id}: {error_msg}", 
                              'error')
                
                # Задержка между сообщениями
                await asyncio.sleep(delay_msg)
            
            log_message(bot_chat_id, name, 
                      f"🎉 Рассылка завершена! Отправлено {messages_sent} сообщений из {len(users_to_message)}", 
                      'success')
            
        finally:
            await client.disconnect()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run())


"""Воркер для рассылки сообщений"""

import asyncio
import time
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import PersistentTimestampOutdatedError
from telethon.tl.types import PeerUser, PeerChannel

from ..config import DEVICE_CONFIG
from .. import storage
from ..utils import log_message, handle_persistent_timestamp_error


def broadcast_worker(name, chats, message, delay_msg, delay_iter, stop_event, chat_id, is_forward=False, forward_from_chat_id=None, forward_message_id=None):
    """Воркер для рассылки сообщений по чатам
    
    Args:
        name: Имя сессии
        chats: Список чатов для рассылки
        message: Текст сообщения (если не пересылка)
        delay_msg: Задержка между сообщениями
        delay_iter: Задержка между итерациями
        stop_event: Событие остановки
        chat_id: ID чата бота для логов
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
            # Получаем все диалоги для кэширования сущностей
            log_message(chat_id, name, "⏳ Получаю информацию о чатах...", 'progress')
            try:
                await client.get_dialogs()
                log_message(chat_id, name, "✅ Информация о чатах получена", 'success')
            except PersistentTimestampOutdatedError:
                log_message(chat_id, name, "⚠️ Ошибка синхронизации при получении диалогов", 'progress')
                recovery_success = await handle_persistent_timestamp_error(client, chat_id, name, "получение диалогов")
                if not recovery_success:
                    log_message(chat_id, name, "❌ Не удалось восстановить синхронизацию. Останавливаю рассылку.", 'error')
                    return
                # Повторная попытка получения диалогов
                try:
                    await client.get_dialogs()
                    log_message(chat_id, name, "✅ Информация о чатах получена после восстановления", 'success')
                except Exception as e:
                    log_message(chat_id, name, f"❌ Не удалось получить диалоги: {str(e)}", 'error')
                    return
            
            # Если это пересылка - получаем и кэшируем entity источника
            if is_forward:
                try:
                    source_entity = await client.get_entity(forward_from_chat_id)
                    log_message(chat_id, name, f"✅ Канал для пересылки получен", 'success')
                except Exception as e:
                    log_message(chat_id, name, f"❌ Не удалось получить канал для пересылки: {str(e)}", 'error')
                    return
            else:
                source_entity = None

            messages_sent = 0
            last_message_time = 0
            
            while not stop_event.is_set():
                
                for target in chats:
                    if stop_event.is_set():
                        break
                    
                    # Проверяем лимиты
                    current_time = time.time()
                    time_since_last = current_time - last_message_time
                    min_delay = storage.settings[name]['limits']['delay_between_messages']
                    
                    if time_since_last < min_delay:
                        await asyncio.sleep(min_delay - time_since_last)
                    
                    try:
                        # Преобразуем ID в правильный формат
                        original_target = target  # Сохраняем оригинальный формат
                        
                        # Получаем информацию о чате
                        try:
                            if isinstance(target, str):
                                if target.startswith('-100'):
                                    # Для групп и каналов с полным ID
                                    target_id = int(target[4:])
                                    entity = await client.get_entity(PeerChannel(target_id))
                                elif target.startswith('-'):
                                    # Для групп и каналов с коротким ID
                                    target_id = int(target[1:])
                                    entity = await client.get_entity(PeerChannel(target_id))
                                elif target.startswith('+'):
                                    # Для приватных ссылок-приглашений
                                    invite_hash = target[1:]  # Убираем +
                                    entity = await client.get_entity(invite_hash)
                                elif target.isdigit():
                                    # Для числовых ID пользователей
                                    target_id = int(target)
                                    entity = await client.get_entity(PeerUser(target_id))
                                else:
                                    # Для username
                                    entity = await client.get_entity(target)
                            else:
                                # Если target уже число
                                if target > 0:
                                    # Для пользователей
                                    entity = await client.get_entity(PeerUser(target))
                                else:
                                    # Для групп и каналов
                                    entity = await client.get_entity(PeerChannel(abs(target)))
                            
                            # Отправляем или пересылаем сообщение
                            if is_forward:
                                # Пересылаем сообщение из оригинального источника (source_entity уже получен)
                                try:
                                    # Пересылаем: await client.forward_messages(куда, ID_сообщения, откуда)
                                    await client.forward_messages(entity, forward_message_id, source_entity)
                                except Exception as forward_error:
                                    log_message(chat_id, name, 
                                              f"⚠️ Ошибка при пересылке в {original_target}: {str(forward_error)}", 
                                              'progress')
                                    raise
                            else:
                                # Отправляем текстовое сообщение
                                await client.send_message(entity, message)
                            
                            messages_sent += 1
                            last_message_time = time.time()
                            
                            action = "переслано" if is_forward else "отправлено"
                            log_message(chat_id, name, f"✅ Сообщение {action} в {original_target}", 'success')
                            
                            # Проверяем лимиты
                            if messages_sent >= storage.settings[name]['limits']['messages_per_minute']:
                                log_message(chat_id, name, "⏳ Достигнут лимит сообщений в минуту. Ожидание...", 'progress')
                                await asyncio.sleep(60)
                                messages_sent = 0
                            
                        except PersistentTimestampOutdatedError:
                            # Обрабатываем ошибку синхронизации
                            log_message(chat_id, name, f"⚠️ Ошибка синхронизации при отправке в {original_target}", 'progress')
                            recovery_success = await handle_persistent_timestamp_error(client, chat_id, name, f"отправка в {original_target}")
                            if recovery_success:
                                # Пробуем отправить сообщение снова после восстановления
                                try:
                                    if is_forward:
                                        # source_entity уже получен ранее
                                        await client.forward_messages(entity, forward_message_id, source_entity)
                                    else:
                                        await client.send_message(entity, message)
                                    
                                    messages_sent += 1
                                    last_message_time = time.time()
                                    
                                    action = "переслано" if is_forward else "отправлено"
                                    log_message(chat_id, name, f"✅ Сообщение {action} в {original_target} после восстановления синхронизации", 'success')
                                except Exception as retry_error:
                                    log_message(chat_id, name, f"❌ Не удалось отправить сообщение в {original_target} после восстановления: {str(retry_error)}", 'error')
                            else:
                                log_message(chat_id, name, f"❌ Не удалось восстановить синхронизацию для {original_target}", 'error')
                            continue
                            
                        except Exception as e:
                            error_msg = str(e)
                            if "You're banned from sending messages in supergroups/channels" in error_msg:
                                log_message(chat_id, name, f"❌ Аккаунт забанен в чате {original_target}. Удаляю чат из списка...", 'error')
                                try:
                                    # Удаляем чат из списка, используя оригинальный формат
                                    if original_target in chats:
                                        chats.remove(original_target)
                                    # Если есть конфигурация, обновляем её
                                    for config_name, config_chats in storage.configs.get(name, {}).items():
                                        if original_target in config_chats:
                                            config_chats.remove(original_target)
                                    storage.save_accounts()
                                    log_message(chat_id, name, f"✅ Чат {original_target} удален из списка", 'success')
                                except Exception as remove_error:
                                    log_message(chat_id, name, f"❌ Ошибка при удалении чата: {str(remove_error)}", 'error')
                            else:
                                log_message(chat_id, name, f"❌ Ошибка при получении информации о чате {original_target}: {error_msg}", 'error')
                            continue
                            
                    except Exception as e:
                        log_message(chat_id, name, f"❌ Ошибка при отправке в {original_target}: {e}", 'error')
                    
                    await asyncio.sleep(delay_msg)
                await asyncio.sleep(delay_iter)
        finally:
            await client.disconnect()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run())


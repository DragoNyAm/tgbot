"""Воркер для автоматической подписки на каналы"""

import asyncio
import time
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import PersistentTimestampOutdatedError, FloodWaitError
from telethon.tl.types import PeerUser, PeerChannel
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

from ..config import DEVICE_CONFIG
from .. import storage
from ..utils import log_message, handle_persistent_timestamp_error


def auto_subscribe_worker(session_name, target_chats, message_text, delay_cycle, stop_event, chat_id):
    """Воркер для автоматической подписки на обязательные каналы"""
    async def run():
        acc = storage.accounts[session_name]
        client = TelegramClient(
            StringSession(acc['string_session']),
            acc['api_id'], acc['api_hash'],
            **DEVICE_CONFIG
        )
        await client.start()
        me = await client.get_me()

        def extract_urls_from_message(msg):
            """Извлечь URL из сообщения"""
            urls = []
            try:
                if getattr(msg, 'reply_markup', None) and getattr(msg.reply_markup, 'rows', None):
                    for row in msg.reply_markup.rows:
                        for button in getattr(row, 'buttons', []) or []:
                            url = getattr(button, 'url', None)
                            if url:
                                urls.append(url)
            except Exception:
                pass
            return urls

        async def join_from_url(url):
            """Вступить в чат по URL"""
            try:
                if 't.me/+' in url or 'joinchat/' in url:
                    if 't.me/+' in url:
                        invite_hash = url.split('t.me/+')[-1].split('?')[0]
                    else:
                        invite_hash = url.split('joinchat/')[-1].split('?')[0]
                    try:
                        await client(ImportChatInviteRequest(invite_hash))
                        return True
                    except Exception:
                        try:
                            await client(JoinChannelRequest(f"+{invite_hash}"))
                            return True
                        except Exception:
                            return False
                elif 't.me/' in url:
                    username = url.split('t.me/')[-1].split('?')[0]
                    await client(JoinChannelRequest(username))
                    return True
            except Exception:
                return False
            return False

        def looks_like_subscribe_prompt(text):
            """Проверить, похож ли текст на запрос подписки"""
            if not text:
                return False
            t = text.lower()
            keywords = ['подпис', 'subscribe', 'подпишитесь', 'подписаться', 'join', 'канал', 'чат']
            return any(k in t for k in keywords)

        try:
            for target_chat in target_chats:
                if stop_event.is_set():
                    log_message(chat_id, session_name, "ℹ️ Задача остановлена пользователем.", 'progress')
                    break
                
                log_message(chat_id, session_name, f"▶️ Работаю с чатом: {target_chat}", 'progress')
                
                try:
                    if isinstance(target_chat, str):
                        if target_chat.startswith('-100'):
                            target_id = int(target_chat[4:])
                            entity = await client.get_entity(PeerChannel(target_id))
                        elif target_chat.startswith('-'):
                            target_id = int(target_chat[1:])
                            entity = await client.get_entity(PeerChannel(target_id))
                        elif target_chat.startswith('+'):
                            entity = await client.get_entity(target_chat[1:])
                        elif target_chat.isdigit():
                            target_id = int(target_chat)
                            entity = await client.get_entity(PeerUser(target_id))
                        else:
                            entity = await client.get_entity(target_chat)
                    else:
                        entity = await client.get_entity(target_chat)
                except Exception as e:
                    log_message(chat_id, session_name, f"❌ Не удалось получить чат {target_chat}: {e}", 'error')
                    continue

                try:
                    sent = await client.send_message(entity, message_text)
                    last_sent_id = sent.id
                    log_message(chat_id, session_name, f"✅ Сообщение отправлено в {target_chat}. Начинаю мониторинг…", 'success')
                except Exception as e:
                    log_message(chat_id, session_name, f"❌ Не удалось отправить сообщение в {target_chat}: {e}", 'error')
                    continue

                # Monitoring loop for the current chat
                monitoring_start_time = time.time()
                while not stop_event.is_set():
                    # Timeout for monitoring a single chat (e.g., 5 minutes)
                    if time.time() - monitoring_start_time > 300:
                        log_message(chat_id, session_name, f"⏳ Не найдено ответа в {target_chat} за 5 минут. Перехожу к следующему чату.", 'progress')
                        break

                    try:
                        msgs = await client.get_messages(entity, limit=50)
                        need_join = []
                        for m in msgs:
                            try:
                                is_reply_to_us = (getattr(m, 'reply_to_msg_id', None) == last_sent_id)
                                is_our_message = (getattr(m, 'sender_id', None) == me.id)
                                says_subscribe = looks_like_subscribe_prompt(getattr(m, 'message', '') or getattr(m, 'text', ''))
                                if is_reply_to_us or is_our_message or says_subscribe:
                                    need_join.extend(extract_urls_from_message(m))
                            except Exception:
                                continue

                        joined_any = False
                        for url in set(need_join):
                            ok = await join_from_url(url)
                            if ok:
                                joined_any = True
                                log_message(chat_id, session_name, f"✅ Успешно вступил в: {url}", 'success')
                                await asyncio.sleep(1)

                        if joined_any:
                            try:
                                await client.send_message(entity, message_text)
                                log_message(chat_id, session_name, f"✅ Подписки в {target_chat} выполнены, сообщение отправлено повторно.", 'success')
                            except Exception as e:
                                log_message(chat_id, session_name, f"❌ Ошибка при повторной отправке в {target_chat}: {e}", 'error')
                            break
                        
                        await asyncio.sleep(delay_cycle)

                    except PersistentTimestampOutdatedError:
                        recovery_success = await handle_persistent_timestamp_error(client, chat_id, session_name, f"мониторинг чата {target_chat}")
                        if not recovery_success:
                            log_message(chat_id, session_name, f"❌ Не удалось восстановить синхронизацию для {target_chat}. Пропускаю чат.", 'error')
                            break
                    except FloodWaitError as e:
                        log_message(chat_id, session_name, f"⏳ Получен FloodWait на {e.seconds} секунд. Ожидаю...", 'progress')
                        await asyncio.sleep(e.seconds)
                    except Exception as e:
                        log_message(chat_id, session_name, f"❌ Ошибка в цикле автоподписки для {target_chat}: {e}", 'error')
                        break
        finally:
            await client.disconnect()
            if storage.tasks.pop(f"auto::{session_name}", None):
                 log_message(chat_id, session_name, f"⏹️ Задача автоподписки для {session_name} завершена.", 'success')


    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run())


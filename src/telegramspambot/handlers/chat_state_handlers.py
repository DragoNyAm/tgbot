"""Обработчики состояний для работы с чатами"""

import asyncio
import threading
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import PeerUser, PeerChannel
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import FloodWaitError
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

from .. import storage
from ..keyboards import main_keyboard
from ..config import DEVICE_CONFIG


def handle_account_chats_selection(msg, bot):
    chat_id = msg.chat.id
    text = msg.text.strip()
    
    if text not in storage.accounts:
        bot.send_message(chat_id, '❌ Аккаунт не найден. Выберите существующий аккаунт:', reply_markup=main_keyboard())
        return
    
    async def get_chats():
        client = TelegramClient(
            StringSession(storage.accounts[text]['string_session']),
            storage.accounts[text]['api_id'],
            storage.accounts[text]['api_hash'],
            **DEVICE_CONFIG
        )
        try:
            await client.connect()
            if not await client.is_user_authorized():
                bot.send_message(chat_id, '❌ Ошибка авторизации аккаунта', reply_markup=main_keyboard())
                return

            dialogs = await client.get_dialogs()
            chat_list = []
            for dialog in dialogs:
                chat = dialog.entity
                if hasattr(chat, 'id'):
                    chat_type = "Канал" if hasattr(chat, 'broadcast') and chat.broadcast else \
                              "Группа" if hasattr(chat, 'megagroup') and chat.megagroup else \
                              "Супергруппа" if hasattr(chat, 'gigagroup') and chat.gigagroup else \
                              "Личный чат"
                    
                    chat_name = getattr(chat, 'title', None) or getattr(chat, 'first_name', None) or str(chat.id)
                    
                    formatted_id = chat.id
                    if chat_type in ["Канал", "Группа", "Супергруппа"]:
                        if str(formatted_id).startswith('100'):
                            formatted_id = f"-{formatted_id}"
                        else:
                            formatted_id = f"-100{formatted_id}"
                    
                    chat_list.append(f"{chat_type}: {chat_name}\nID: {formatted_id}")
            
            if chat_list:
                message = "Список чатов:\n\n" + "\n\n".join(chat_list)
                if len(message) > 4000:
                    parts = [message[i:i+4000] for i in range(0, len(message), 4000)]
                    for part in parts:
                        bot.send_message(chat_id, part)
                else:
                    bot.send_message(chat_id, message)
            else:
                bot.send_message(chat_id, "Нет доступных чатов.")
            
            bot.send_message(chat_id, "Выберите действие:", reply_markup=main_keyboard())
        except Exception as e:
            bot.send_message(chat_id, f'❌ Ошибка при получении чатов: {str(e)}', reply_markup=main_keyboard())
        finally:
            await client.disconnect()
            storage.states.pop(chat_id)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(get_chats())


def handle_account_join_selection(msg, bot):
    chat_id = msg.chat.id
    text = msg.text.strip()
    
    if text not in storage.accounts:
        bot.send_message(chat_id, '❌ Аккаунт не найден. Выберите существующий аккаунт:', reply_markup=main_keyboard())
        return
    
    storage.states[chat_id] = {
        'step': 'join_chats_input',
        'session': text
    }
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton('Отмена'))
    bot.send_message(chat_id, 'Введите ссылки на чаты через новую строку (каждый чат с новой строки):', reply_markup=kb)


def handle_join_chats_input(msg, bot):
    chat_id = msg.chat.id
    state = storage.states[chat_id]
    text = msg.text.strip()
    session_name = state['session']
    
    if text == 'Отмена':
        storage.states.pop(chat_id)
        bot.send_message(chat_id, 'Операция отменена.', reply_markup=main_keyboard())
        return
    
    async def join_chats():
        client = TelegramClient(
            StringSession(storage.accounts[session_name]['string_session']),
            storage.accounts[session_name]['api_id'],
            storage.accounts[session_name]['api_hash'],
            **DEVICE_CONFIG
        )
        try:
            await client.connect()
            if not await client.is_user_authorized():
                bot.send_message(chat_id, '❌ Ошибка авторизации аккаунта', reply_markup=main_keyboard())
                return

            chat_links = [link.strip() for link in text.split('\n') if link.strip()]
            success_count = 0
            fail_count = 0
            already_joined_count = 0
            
            dialogs = await client.get_dialogs()
            joined_chats = set()
            for dialog in dialogs:
                if hasattr(dialog.entity, 'username') and dialog.entity.username:
                    joined_chats.add(dialog.entity.username.lower())
            
            for link in chat_links:
                try:
                    username = None
                    invite_hash = None
                    
                    if 't.me/' in link:
                        if '+' in link:
                            invite_hash = link.split('t.me/+')[-1].split('?')[0].lower()
                        else:
                            username = link.split('t.me/')[-1].split('?')[0].lower()
                    elif '@' in link:
                        username = link.split('@')[-1].split('?')[0].lower()
                    
                    if not username and not invite_hash:
                        bot.send_message(chat_id, f'❌ Неверный формат ссылки: {link}')
                        fail_count += 1
                        continue
                    
                    if username and username in joined_chats:
                        already_joined_count += 1
                        bot.send_message(chat_id, f'ℹ️ Уже состоим в чате {link}')
                        continue
                    
                    if invite_hash:
                        try:
                            await client(ImportChatInviteRequest(invite_hash))
                            success_count += 1
                            bot.send_message(chat_id, f'✅ Успешно вступил в приватный чат {link}')
                        except Exception as invite_error:
                            try:
                                await client(JoinChannelRequest(f"+{invite_hash}"))
                                success_count += 1
                                bot.send_message(chat_id, f'✅ Успешно вступил в приватный чат {link}')
                            except Exception as join_error:
                                raise Exception(f"Не удалось вступить через оба метода: {str(invite_error)} / {str(join_error)}")
                    else:
                        await client(JoinChannelRequest(username))
                        success_count += 1
                        bot.send_message(chat_id, f'✅ Успешно вступил в {link}')
                    
                except FloodWaitError as e:
                    wait_time = e.seconds
                    bot.send_message(chat_id, f'⏳ Достигнут лимит. Нужно подождать {wait_time} секунд.')
                    bot.send_message(chat_id, f'⏳ Ожидание {wait_time} секунд...')
                    
                    await asyncio.sleep(wait_time)
                    
                    try:
                        if invite_hash:
                            await client(ImportChatInviteRequest(invite_hash))
                        else:
                            await client(JoinChannelRequest(username))
                        success_count += 1
                        bot.send_message(chat_id, f'✅ Успешно вступил в {link} после ожидания')
                    except Exception as retry_error:
                        fail_count += 1
                        bot.send_message(chat_id, f'❌ Ошибка при повторной попытке вступления в {link}: {str(retry_error)}')
                
                except Exception as e:
                    fail_count += 1
                    bot.send_message(chat_id, f'❌ Ошибка при вступлении в {link}: {str(e)}')
                
                await asyncio.sleep(2)
            
            stats_message = f'Итоги:\n✅ Успешно: {success_count}\n❌ Ошибок: {fail_count}'
            if already_joined_count > 0:
                stats_message += f'\nℹ️ Уже состоим: {already_joined_count}'
            bot.send_message(chat_id, stats_message, reply_markup=main_keyboard())
            
        except Exception as e:
            bot.send_message(chat_id, f'❌ Ошибка при подключении: {str(e)}', reply_markup=main_keyboard())
        finally:
            await client.disconnect()
            storage.states.pop(chat_id)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(join_chats())


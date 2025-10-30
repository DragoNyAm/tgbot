"""Роутер состояний для обработки многошаговых диалогов"""

import asyncio
import threading
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

from .. import storage
from ..keyboards import main_keyboard, cancel_keyboard, account_settings_keyboard, sessions_keyboard
from ..config import DEVICE_CONFIG

# Импорт обработчиков из модулей
from .broadcast_state_handlers import (
    handle_broadcast_session_selection,
    handle_broadcast_method_selection,
    handle_broadcast_config_selection,
    handle_broadcast_type_selection,
    handle_broadcast_manual_chats_input,
    handle_broadcast_message_type_selection,
    handle_broadcast_forward_channel_input,
    handle_broadcast_message_input,
    handle_broadcast_delay_msg_input,
    handle_broadcast_delay_iter_input,
    handle_broadcast_save_config_prompt,
    handle_broadcast_config_name_input,
    handle_stop_broadcast_selection
)
from .chat_state_handlers import (
    handle_account_chats_selection,
    handle_account_join_selection,
    handle_join_chats_input
)
from .auto_subscribe_state_handlers import (
    handle_auto_select_session,
    handle_auto_target_chats_input,
    handle_auto_message,
    handle_auto_delay
)
from .settings_state_handlers import (
    handle_settings_menu,
    handle_logging_settings
)
from .parser_state_handlers import handle_parser_states


def log(message):
    """Простое логирование"""
    print(f"[Bot] {message}")


def register_state_router(bot):
    """Регистрация роутера состояний"""
    
    # Обработчики для добавления аккаунта
    def handle_api_id_input(msg):
        chat_id = msg.chat.id
        text = msg.text.strip()
        
        try:
            api_id = int(text)
            storage.states[chat_id] = {
                'step': 'api_hash',
                'api_id': api_id
            }
            bot.send_message(
                chat_id, 
                'Введите api_hash:', 
                reply_markup=cancel_keyboard()
            )
        except ValueError:
            bot.send_message(
                chat_id, 
                '❌ Неверный формат api_id. Введите число:', 
                reply_markup=cancel_keyboard()
            )
    
    def handle_api_hash_input(msg):
        chat_id = msg.chat.id
        text = msg.text.strip()
        
        storage.states[chat_id] = {
            'step': 'phone',
            'api_id': storage.states[chat_id]['api_id'],
            'api_hash': text
        }
        bot.send_message(
            chat_id, 
            'Введите номер телефона (+...):', 
            reply_markup=cancel_keyboard()
        )
    
    def handle_phone_input(msg):
        chat_id = msg.chat.id
        text = msg.text.strip()
        
        if not text.startswith('+'):
            bot.send_message(
                chat_id, 
                '❌ Неверный формат номера. Введите номер в формате +...:', 
                reply_markup=cancel_keyboard()
            )
            return
        
        storage.states[chat_id] = {
            'step': 'session_name',
            'api_id': storage.states[chat_id]['api_id'],
            'api_hash': storage.states[chat_id]['api_hash'],
            'phone': text
        }
        bot.send_message(
            chat_id, 
            'Введите название для сессии:', 
            reply_markup=cancel_keyboard()
        )
    
    def handle_session_name_input(msg):
        chat_id = msg.chat.id
        text = msg.text.strip()
        
        if text in storage.accounts:
            bot.send_message(
                chat_id,
                '❌ Сессия с таким названием уже существует. Введите другое название:',
                reply_markup=cancel_keyboard()
            )
            return
        
        storage.states[chat_id]['session_name'] = text
        
        def run_async():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Используем StringSession вместо файловой сессии
                client = TelegramClient(
                    StringSession(),
                    storage.states[chat_id]['api_id'],
                    storage.states[chat_id]['api_hash'],
                    device_model=DEVICE_CONFIG['device_model'],
                    system_version=DEVICE_CONFIG['system_version'],
                    app_version=DEVICE_CONFIG['app_version'],
                    lang_code=DEVICE_CONFIG['lang_code'],
                    system_lang_code=DEVICE_CONFIG['system_lang_code'],
                    loop=loop
                )
                
                storage.states[chat_id]['client'] = client
                storage.states[chat_id]['loop'] = loop
                
                async def send_code():
                    try:
                        await client.connect()
                        await client.send_code_request(storage.states[chat_id]['phone'])
                    except Exception as e:
                        log(f"❌ Ошибка отправки кода для {text}: {e}")
                        raise
                
                log(f"📞 Отправка кода для {text} ({storage.states[chat_id]['phone']})")
                loop.run_until_complete(send_code())
                storage.states[chat_id]['step'] = 'code'
                bot.send_message(
                    chat_id, 
                    'Введите код из Telegram:', 
                    reply_markup=cancel_keyboard()
                )
            except Exception as e:
                bot.send_message(
                    chat_id,
                    f'❌ Ошибка: {str(e)}',
                    reply_markup=main_keyboard()
                )
                storage.states.pop(chat_id, None)
                try:
                    loop.close()
                except:
                    pass
        
        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()
    
    def handle_code_input(msg):
        chat_id = msg.chat.id
        text = msg.text.strip()
        state = storage.states.get(chat_id)
        
        if not state or 'client' not in state or 'loop' not in state:
            return
        
        client = state['client']
        loop = state['loop']
        
        async def sign_in():
            need_2fa = False
            success = False
            try:
                log(f"🔐 Вход в аккаунт {state['session_name']} ({state['phone']})")
                await client.sign_in(state['phone'], text)
                session_name = state['session_name']
                
                # Получаем строку сессии
                string_session = client.session.save()
                
                # Уведомление об успешной авторизации
                bot.send_message(
                    chat_id,
                    '✅ Успешная авторизация! Вы вошли в аккаунт.',
                    reply_markup=cancel_keyboard()
                )
                
                # Сохраняем аккаунт со строкой сессии
                storage.add_account(
                    session_name,
                    state['api_id'],
                    state['api_hash'],
                    state['phone'],
                    string_session
                )
                
                await client.disconnect()
                bot.send_message(
                    chat_id,
                    f'✅ Аккаунт {session_name} успешно добавлен!',
                    reply_markup=main_keyboard()
                )
                storage.states.pop(chat_id, None)
                success = True
            except SessionPasswordNeededError:
                need_2fa = True
                storage.states[chat_id]['step'] = 'password'
                bot.send_message(
                    chat_id,
                    'Введите пароль 2FA:',
                    reply_markup=cancel_keyboard()
                )
            except Exception as e:
                try:
                    await client.disconnect()
                except:
                    pass
                bot.send_message(
                    chat_id,
                    f'❌ Ошибка входа: {str(e)}',
                    reply_markup=main_keyboard()
                )
                storage.states.pop(chat_id, None)
            
            return need_2fa, success
        
        def run_async():
            try:
                need_2fa, success = loop.run_until_complete(sign_in())
                # Закрываем loop только если НЕ требуется 2FA и авторизация завершена (успешно или с ошибкой)
                if not need_2fa:
                    try:
                        loop.close()
                    except:
                        pass
            except Exception as e:
                log(f"❌ Ошибка в run_async: {e}")
                try:
                    loop.close()
                except:
                    pass
        
        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()
    
    def handle_password_input(msg):
        chat_id = msg.chat.id
        text = msg.text.strip()
        state = storage.states.get(chat_id)
        
        if not state or 'client' not in state or 'loop' not in state:
            return
        
        client = state['client']
        loop = state['loop']
        
        async def sign_in_password():
            try:
                log(f"🔐 Вход с 2FA для {state['session_name']}")
                await client.sign_in(password=text)
                session_name = state['session_name']
                
                # Получаем строку сессии
                string_session = client.session.save()
                
                # Уведомление об успешной авторизации с 2FA
                bot.send_message(
                    chat_id,
                    '✅ Успешная авторизация с 2FA! Вы вошли в аккаунт.',
                    reply_markup=cancel_keyboard()
                )
                
                # Сохраняем аккаунт со строкой сессии
                storage.add_account(
                    session_name,
                    state['api_id'],
                    state['api_hash'],
                    state['phone'],
                    string_session
                )
                
                await client.disconnect()
                bot.send_message(
                    chat_id,
                    f'✅ Аккаунт {session_name} успешно добавлен!',
                    reply_markup=main_keyboard()
                )
                storage.states.pop(chat_id, None)
            except Exception as e:
                try:
                    await client.disconnect()
                except:
                    pass
                bot.send_message(
                    chat_id,
                    f'❌ Ошибка входа с 2FA: {str(e)}',
                    reply_markup=main_keyboard()
                )
                storage.states.pop(chat_id, None)
        
        def run_async():
            try:
                loop.run_until_complete(sign_in_password())
            except Exception as e:
                log(f"❌ Ошибка в run_async (password): {e}")
            finally:
                # Всегда закрываем loop после обработки пароля
                try:
                    loop.close()
                except:
                    pass
        
        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()
    
    def handle_remove_account(msg):
        chat_id = msg.chat.id
        text = msg.text.strip()
        
        if text in storage.accounts:
            storage.remove_account(text)
            bot.send_message(
                chat_id,
                f'✅ Аккаунт {text} удалён',
                reply_markup=main_keyboard()
            )
        else:
            bot.send_message(
                chat_id,
                '❌ Аккаунт не найден',
                reply_markup=main_keyboard()
            )
        storage.states.pop(chat_id, None)
    
    # Обработчики настроек аккаунта
    def handle_account_settings_selection(msg):
        chat_id = msg.chat.id
        if msg.text not in storage.accounts:
            bot.send_message(chat_id, 'Неверный аккаунт.', reply_markup=main_keyboard())
            storage.states.pop(chat_id)
            return

        account_name = msg.text
        state = storage.states[chat_id]
        action = state.get('action')

        if action == 'account_management':
            storage.states[chat_id] = {
                'step': 'account_settings_menu',
                'session': account_name
            }
            bot.send_message(chat_id, f'Настройки аккаунта "{account_name}":', reply_markup=account_settings_keyboard())
        elif action == 'session_settings':
            from ..keyboards import settings_keyboard
            storage.states[chat_id] = {
                'step': 'session_settings',
                'session': account_name
            }
            bot.send_message(chat_id, f'Настройки сессии "{account_name}":', reply_markup=settings_keyboard())
        else:
            bot.send_message(chat_id, 'Неизвестное действие.', reply_markup=main_keyboard())
            storage.states.pop(chat_id)
    
    def handle_account_settings_menu_selection(msg):
        chat_id = msg.chat.id
        state = storage.states[chat_id]
        session_name = state['session']
        
        if msg.text == '📝 Изменить имя':
            state['step'] = 'change_first_name'
            bot.send_message(chat_id, 'Введите новое имя (и фамилию через пробел, если есть):')
        elif msg.text == '👤 Изменить username':
            state['step'] = 'change_username'
            bot.send_message(chat_id, 'Введите новый username:')
        elif msg.text == '📋 Изменить био':
            state['step'] = 'change_bio'
            bot.send_message(chat_id, 'Введите новое описание:')
        elif msg.text == '🖼 Изменить аватар':
            state['step'] = 'change_avatar'
            bot.send_message(chat_id, 'Отправьте новое фото аватара:')
        elif msg.text == 'Назад':
            storage.states[chat_id] = {'step': 'select_account_settings', 'action': 'account_management'}
            bot.send_message(chat_id, 'Выберите аккаунт для управления:', reply_markup=sessions_keyboard())
    
    def handle_change_first_name_input(msg):
        chat_id = msg.chat.id
        state = storage.states[chat_id]
        
        if msg.text == 'Отмена':
            storage.states[chat_id]['step'] = 'account_settings_menu'
            bot.send_message(chat_id, 'Изменение имени отменено.', reply_markup=account_settings_keyboard())
            return

        async def update_name():
            account_name = state['session']
            client = TelegramClient(
                StringSession(storage.accounts[account_name]['string_session']),
                storage.accounts[account_name]['api_id'],
                storage.accounts[account_name]['api_hash'],
                **DEVICE_CONFIG
            )
            await client.start()
            try:
                from telethon.tl.functions.account import UpdateProfileRequest
                names = msg.text.split(' ', 1)
                first_name = names[0]
                last_name = names[1] if len(names) > 1 else ''
                await client(UpdateProfileRequest(
                    first_name=first_name,
                    last_name=last_name
                ))
                bot.send_message(chat_id, '✅ Имя успешно обновлено', reply_markup=account_settings_keyboard())
            except Exception as e:
                bot.send_message(chat_id, f'❌ Ошибка при обновлении имени: {e}', reply_markup=account_settings_keyboard())
            finally:
                await client.disconnect()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(update_name())
        loop.close()
        storage.states[chat_id]['step'] = 'account_settings_menu'
    
    def handle_change_username_input(msg):
        chat_id = msg.chat.id
        state = storage.states[chat_id]
        
        if msg.text == 'Отмена':
            storage.states[chat_id]['step'] = 'account_settings_menu'
            bot.send_message(chat_id, 'Изменение username отменено.', reply_markup=account_settings_keyboard())
            return

        async def update_username():
            account_name = state['session']
            client = TelegramClient(
                StringSession(storage.accounts[account_name]['string_session']),
                storage.accounts[account_name]['api_id'],
                storage.accounts[account_name]['api_hash'],
                **DEVICE_CONFIG
            )
            await client.start()
            try:
                from telethon.tl.functions.account import UpdateUsernameRequest
                await client(UpdateUsernameRequest(msg.text))
                bot.send_message(chat_id, '✅ Username успешно обновлен', reply_markup=account_settings_keyboard())
            except Exception as e:
                bot.send_message(chat_id, f'❌ Ошибка при обновлении username: {e}', reply_markup=account_settings_keyboard())
            finally:
                await client.disconnect()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(update_username())
        loop.close()
        storage.states[chat_id]['step'] = 'account_settings_menu'
    
    def handle_change_bio_input(msg):
        chat_id = msg.chat.id
        state = storage.states[chat_id]
        
        if msg.text == 'Отмена':
            storage.states[chat_id]['step'] = 'account_settings_menu'
            bot.send_message(chat_id, 'Изменение био отменено.', reply_markup=account_settings_keyboard())
            return

        async def update_bio():
            account_name = state['session']
            client = TelegramClient(
                StringSession(storage.accounts[account_name]['string_session']),
                storage.accounts[account_name]['api_id'],
                storage.accounts[account_name]['api_hash'],
                **DEVICE_CONFIG
            )
            await client.start()
            try:
                from telethon.tl.functions.account import UpdateProfileRequest
                await client(UpdateProfileRequest(about=msg.text))
                bot.send_message(chat_id, '✅ Био успешно обновлено', reply_markup=account_settings_keyboard())
            except Exception as e:
                bot.send_message(chat_id, f'❌ Ошибка при обновлении био: {e}', reply_markup=account_settings_keyboard())
            finally:
                await client.disconnect()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(update_bio())
        loop.close()
        storage.states[chat_id]['step'] = 'account_settings_menu'
    
    def handle_change_avatar_input(msg):
        chat_id = msg.chat.id
        state = storage.states[chat_id]
        
        if msg.text == 'Отмена':
            storage.states[chat_id]['step'] = 'account_settings_menu'
            bot.send_message(chat_id, 'Изменение аватара отменено.', reply_markup=account_settings_keyboard())
            return
            
        if not msg.photo:
            bot.send_message(chat_id, '❌ Пожалуйста, отправьте фото.', reply_markup=account_settings_keyboard())
            return

        account_name = state['session']
        file_info = bot.get_file(msg.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        photo_path = f'{account_name}_avatar.jpg'
        with open(photo_path, 'wb') as new_file:
            new_file.write(downloaded_file)

        async def update_avatar():
            client = TelegramClient(
                StringSession(storage.accounts[account_name]['string_session']),
                storage.accounts[account_name]['api_id'],
                storage.accounts[account_name]['api_hash'],
                **DEVICE_CONFIG
            )
            await client.start()
            try:
                from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
                import os
                photo = await client.upload_file(photo_path)
                
                try:
                    existing_photos = await client.get_profile_photos('me')
                    await client(DeletePhotosRequest(id=[p.photo.id for p in existing_photos]))
                except Exception:
                    pass

                await client(UploadProfilePhotoRequest(photo))
                bot.send_message(chat_id, '✅ Аватар успешно обновлен', reply_markup=account_settings_keyboard())
            except Exception as e:
                bot.send_message(chat_id, f'❌ Ошибка при обновлении аватара: {e}', reply_markup=account_settings_keyboard())
            finally:
                await client.disconnect()
                if os.path.exists(photo_path):
                    os.remove(photo_path)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        threading.Thread(target=lambda: loop.run_until_complete(update_avatar())).start()
        storage.states[chat_id]['step'] = 'account_settings_menu'
    
    @bot.message_handler(func=lambda m: m.chat.id in storage.states)
    def handle_states(msg):
        """Главный роутер для обработки состояний"""
        chat_id = msg.chat.id
        state = storage.states.get(chat_id)
        text = msg.text.strip()

        if state is None:
            return

        if text == 'Отмена':
            # Закрываем клиент если он есть
            if 'client' in state and 'loop' in state:
                try:
                    client = state['client']
                    loop = state['loop']
                    loop.run_until_complete(client.disconnect())
                    loop.close()
                except:
                    pass
            
            storage.states.pop(chat_id, None)
            bot.send_message(chat_id, 'Операция отменена.', reply_markup=main_keyboard())
            return

        step = state['step']

        # Map of step handlers
        step_handlers = {
            # Account management
            'api_id': handle_api_id_input,
            'api_hash': handle_api_hash_input,
            'phone': handle_phone_input,
            'session_name': handle_session_name_input,
            'code': handle_code_input,
            'password': handle_password_input,
            'remove': handle_remove_account,
            
            # Account settings
            'select_account_settings': handle_account_settings_selection,
            'account_settings_menu': handle_account_settings_menu_selection,
            'change_first_name': handle_change_first_name_input,
            'change_username': handle_change_username_input,
            'change_bio': handle_change_bio_input,
            'change_avatar': handle_change_avatar_input,
        }
        
        # Обработчики с передачей bot
        step_handlers_with_bot = {
            # Session settings
            'session_settings': handle_settings_menu,
            'logging_settings': handle_logging_settings,
            
            # Broadcast
            'b_select_session': handle_broadcast_session_selection,
            'b_select_method': handle_broadcast_method_selection,
            'b_select_config': handle_broadcast_config_selection,
            'b_select_type': handle_broadcast_type_selection,
            'b_manual_input_chats': handle_broadcast_manual_chats_input,
            'b_select_message_type': handle_broadcast_message_type_selection,
            'b_enter_forward_channel': handle_broadcast_forward_channel_input,
            'b_message': handle_broadcast_message_input,
            'b_delay_msg': handle_broadcast_delay_msg_input,
            'b_delay_iter': handle_broadcast_delay_iter_input,
            'b_save_config': handle_broadcast_save_config_prompt,
            'b_enter_config_name': handle_broadcast_config_name_input,
            
            # Stop
            'stop': handle_stop_broadcast_selection,
            
            # Chat management
            'select_account_chats': handle_account_chats_selection,
            'select_account_join': handle_account_join_selection,
            'join_chats_input': handle_join_chats_input,
            
            # Auto subscribe
            'auto_select_session': handle_auto_select_session,
            'auto_target_chats': handle_auto_target_chats_input,
            'auto_message': handle_auto_message,
            'auto_delay': handle_auto_delay,
        }

        # Call appropriate handler if exists
        if step in step_handlers:
            step_handlers[step](msg)
        elif step in step_handlers_with_bot:
            step_handlers_with_bot[step](msg, bot)
        # Обработка состояний парсинга
        elif handle_parser_states(bot, msg):
            return
        else:
            bot.send_message(chat_id, 'Неизвестное состояние.', reply_markup=main_keyboard())
            storage.states.pop(chat_id)


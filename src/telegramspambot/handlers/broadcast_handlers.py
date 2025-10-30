"""Обработчики рассылки"""

# Импортируем обработчики из test_new.py
from ..test_new import (
    handle_broadcast_session_selection,
    handle_broadcast_method_selection,
    handle_broadcast_config_selection,
    handle_broadcast_type_selection,
    handle_broadcast_manual_chats_input,
    handle_broadcast_message_input,
    handle_broadcast_delay_msg_input,
    handle_broadcast_delay_iter_input,
    handle_broadcast_save_config_prompt,
    handle_broadcast_config_name_input,
    handle_stop_broadcast_selection
)


def register_broadcast_handlers(bot):
    """Регистрация обработчиков рассылки"""
    # Обработчики регистрируются через state_router
    pass


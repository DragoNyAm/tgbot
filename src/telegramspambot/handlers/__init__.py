"""Обработчики сообщений бота"""

from .main_handlers import register_main_handlers
from .account_handlers import register_account_handlers
from .broadcast_handlers import register_broadcast_handlers
from .chat_handlers import register_chat_handlers
from .settings_handlers import register_settings_handlers
from .auto_subscribe_handlers import register_auto_subscribe_handlers
from .parser_handlers import register_parser_handlers
from .state_router import register_state_router


def register_all_handlers(bot):
    """Регистрация всех обработчиков"""
    register_main_handlers(bot)
    register_account_handlers(bot)
    register_broadcast_handlers(bot)
    register_chat_handlers(bot)
    register_settings_handlers(bot)
    register_auto_subscribe_handlers(bot)
    register_parser_handlers(bot)
    # State router должен быть последним
    register_state_router(bot)


"""Telegram Spam Bot - модульная структура"""

from . import storage
from .bot_instance import bot

__all__ = ['bot', 'storage']


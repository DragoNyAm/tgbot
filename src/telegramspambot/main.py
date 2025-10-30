"""Главный модуль приложения"""

from .bot_instance import bot
from . import storage
from .handlers import register_all_handlers


def main():
    """Основная функция запуска бота"""
    print("=" * 60)
    print("🤖 TELEGRAM SPAM BOT - ЗАПУСК")
    print("=" * 60)
    
    # Загрузка данных
    print("🚀 Загрузка данных...")
    storage.load_accounts()
    
    if storage.accounts:
        print(f"📋 Аккаунты: {', '.join(storage.accounts.keys())}")
    
    # Регистрация обработчиков
    print("📝 Регистрация обработчиков...")
    register_all_handlers(bot)
    print("✅ Обработчики зарегистрированы")
    
    print("=" * 60)
    print("✅ БОТ ЗАПУЩЕН И ГОТОВ К РАБОТЕ!")
    print("=" * 60)
    print("💡 Для остановки нажмите Ctrl+C")
    
    try:
        bot.infinity_polling()
    except KeyboardInterrupt:
        print("\n" + "=" * 60)
        print("⏹️  Остановка бота...")
        storage.save_accounts()
        print("✅ До свидания!")
        print("=" * 60)
    except Exception as e:
        print(f"💥 Критическая ошибка: {e}")
        raise


if __name__ == '__main__':
    main()


"""Скрипт запуска бота из корневой директории"""

import sys
from pathlib import Path

# Добавляем src в путь
src_path = Path(__file__).parent / 'src'
sys.path.insert(0, str(src_path))

# Импортируем и запускаем
from telegramspambot.main import main

if __name__ == '__main__':
    main()


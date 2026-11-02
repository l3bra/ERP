# Склад

Локальное приложение для учёта складских позиций. Интерфейс работает в браузере, API построен на FastAPI, данные хранятся в SQLite.

## Запуск в Windows

1. Установите Python 3.10 или новее.
2. Запустите `start_all.bat`.
3. Приложение откроется в браузере по адресу `http://127.0.0.1:8000/`.

Чтобы запускать только сервер при каждом входе в Windows, выполните один раз из папки проекта:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1
```

После входа в Windows сервер запустится в фоне, не открывая браузер. Откройте страницу вручную по адресу `http://127.0.0.1:8000/`.

Если зависимости ещё не установлены, создайте окружение и установите их из корня проекта:

```powershell
python -m venv backend\venv
backend\venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Для ручного запуска API:

```powershell
cd backend
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Интерфейс находится в `frontend/index.html` и также раздаётся сервером на `/`. Сборка фронтенда не требуется.

## Данные

При первом запуске API создаёт локальную базу `backend/warehouse.db`. Эта база, а также Excel-файлы с данными, исключены из Git и не публикуются вместе с исходным кодом. Делайте отдельные резервные копии базы, если в ней есть важные складские данные.

## Состав проекта

- `backend/main.py` — API и работа с SQLite.
- `backend/requirements.txt` — зависимости Python.
- `frontend/index.html` — интерфейс.
- `Styles/` — изображения-референсы оформления.
- `start_all.bat` — запуск приложения из каталога проекта.
- `start_server.bat` — запуск только API без браузера.
- `start_server_hidden.vbs` — скрытый запуск API для автозапуска Windows.
- `install_autostart.ps1` — регистрация запуска API при входе пользователя в Windows.

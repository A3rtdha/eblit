# Eblit

Приложение для раздельной маршрутизации в Windows. Сети Fastly, в том числе часть трафика Spotify, идут через Cloudflare WARP. Домены из настроек идут через выбранный сервер VLESS или Hysteria2. Остальной трафик идёт напрямую.

## Установка

Скачай `EblitSetup.exe` со страницы [релизов](https://github.com/A3rtdha/eblit/releases/latest). Установщик добавит Eblit и sing-box в `%ProgramFiles%\Eblit` и поставит Cloudflare WARP, если его ещё нет. Настройки и журналы приложения хранятся в `%LOCALAPPDATA%\Eblit`. Удалить Eblit можно через список установленных приложений Windows.

Для обновления нажми на номер версии внизу окна. Если доступна новая версия, появится кнопка «Обновить».

## Где что лежит

| Путь | Содержимое |
| --- | --- |
| [`app/`](app/) | Точка входа, связь окна с Python, трей и хранение данных |
| [`app/stack/`](app/stack/) | Подключение, маршруты, WARP, sing-box, серверы и подписки |
| [`app/web/`](app/web/) и [`app/assets/`](app/assets/) | HTML, CSS, JavaScript и иконки окна |
| [`app/setup/`](app/setup/) | Установка, обновление и удаление приложения |
| [`tools/core/`](tools/core/) | Сборка sing-box. Версии исходников, Go, патча и проверок закреплены в [манифесте](tools/core/manifest.json) |
| [`tools/packaging/`](tools/packaging/) | Спецификации PyInstaller для приложения и установщика |
| [`tests/`](tests/) | Проверки окна (`desktop`, `web`), стека (`stack`), установщика (`installer`) и сборки (`distribution`) |
| [`docs/behavior.md`](docs/behavior.md) | Как работают подключение, диагностика, настройки и обновления |
| [`config.example.json`](config.example.json) | Стартовая конфигурация без личных серверов |

## Запуск из исходников

Открой PowerShell в корне клона. Нужны Windows и Python 3.12. Для подключения через WARP нужен установленный клиент Cloudflare WARP.

```powershell
python -m pip install -r app/requirements.txt
if (-not (Test-Path config.json)) { Copy-Item config.example.json config.json }
python tools/core/build.py --work-dir "$env:TEMP/eblit-core" --output sing-box.exe
python -m app
```

Сборщик скачивает закреплённые исходники и Go, проверяет контрольные суммы и тестирует XHTTP и Hysteria2 локально. Готовый `sing-box.exe` лежит в корне клона.

Добавь сервер VLESS или URL подписки в настройках окна. При запуске из исходников `config.json` и остальные данные приложения лежат рядом с `config.example.json`. Ключи и ссылки подписок храни в локальных файлах.

Стеком можно управлять из терминала через `python -m app --stack`. Основные команды — `start`, `stop`, `reload` и `test`.

## Проверки

Установи зависимости из `app/requirements.txt` и запусти проверки из корня клона. Для тестов JavaScript подойдёт Node.js 24.

```powershell
python -m unittest discover
node --test "tests/web/*.test.js"
```

## Сборка установщика

Подготовь `config.json` и `sing-box.exe` по шагам выше. Затем запусти из корня клона следующие команды.

```powershell
python -m pip install -r requirements-build.txt
python -m app.pack
```

Готовое приложение появится в `dist/Eblit/`, установщик — в `dist/EblitSetup.exe`. Сборка проверяет SHA-256 ядра и кладёт в установщик очищенную копию конфигурации.

Для своих релизов в форке укажи `владелец/репозиторий` в `REPO` в [`app/version.py`](app/version.py). По этому адресу приложение проверяет обновления. [Workflow выпуска](.github/workflows/release.yml) запускает сборку по тегу `vX.Y.Z`. Для публикации создай релиз с тегом, который соответствует `VERSION`, и прикрепи к нему `EblitSetup.exe`. Пример описания есть в [`.github/release-notes.md`](.github/release-notes.md).

## Лицензия

Пользуйся как хочешь.

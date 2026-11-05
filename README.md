# Eblit

Windows-приложение: узкий split для Fastly/Spotify (через Cloudflare WARP) и выбранных доменов (через свой VLESS). Остальной трафик — игры, Discord, Google, Telegram — идёт мимо, как без него.

## Что делает

| Трафик | Куда |
|---|---|
| Сети Fastly (часть Spotify и другие сайты на этом CDN) | WARP SOCKS `:40000` |
| Домены из настроек (ИИ, Meta/Quest, …) | VLESS |
| Всё остальное | напрямую |

В TUN попадает только белый список адресов. Для Riot/Valorant закреплён прямой маршрут. В списке VPN допускаются полные домены; отдельные зоны вроде `com` отклоняются.

## Установка

Скачай `EblitSetup.exe` с [релизов](https://github.com/A3rtdha/eblit/releases/latest). Установщик поставит WARP (если его нет), sing-box и саму программу в `%ProgramFiles%\Eblit`.

Обновление из окна: цифра версии внизу по центру → если есть свежее, ещё раз нажать.

## Сборка из исходников

Нужны Python 3.12 и PyInstaller. Ядро собирается из закреплённой версии sing-box extended: XHTTP сохраняется, для Hysteria2 добавлена проверка отпечатка полного сертификата.

```powershell
pip install -r app/requirements.txt pyinstaller
copy config.example.json config.json
python tools/core/build.py --work-dir "$env:TEMP/eblit-core" --output sing-box.exe
```

Команда для PowerShell сама скачивает закреплённый Go и исходники, проверяет их контрольные суммы и собирает `sing-box.exe` рядом с проектом. Сборщик проверяет передачу трафика через XHTTP и Hysteria2 на локальном стенде и отказ при неверном отпечатке сертификата. Установщик использует эту сборку; упаковка проверяет её SHA-256. GitHub Actions проверяет сборку по тегу; релиз и установщик публикуются через учётную запись владельца.

В `config.json` подставь свои VLESS (uuid, public_key, хост). Живой файл в git не лежит.

```
python -m app            # окно
python -m app.pack       # dist/Eblit/ и dist/EblitSetup.exe
```

CLI стека: `python -m app --stack start|stop|reload|test`.

## Лицензия

Пользуйся как хочешь. Ключи чужих VPN в репозиторий не клади.


Настройки установленной программы хранятся в `%LOCALAPPDATA%\Eblit` и одинаково доступны обычному и административному запуску. Выход из окна или трея останавливает подключение; жёлтая кнопка оставляет приложение работать в трее.

Проверки: `python -m unittest discover` и `node --test app/web/node-parse.test.js app/web/power-state.test.js app/web/links.test.js`.

# Eblit

Windows-приложение: узкий split для Fastly/Spotify (через Cloudflare WARP) и выбранных доменов (через свой VLESS). Остальной трафик — игры, Discord, Google — идёт мимо, как без него.

## Что делает

| Трафик | Куда |
|---|---|
| Fastly (Spotify и соседние CDN) | WARP SOCKS `:40000` |
| Домены из настроек (ИИ, Meta/Quest, …) | VLESS / Lagom |
| Всё остальное | напрямую |

В TUN попадает только белый список адресов, не весь интернет.

## Установка

Скачай `EblitSetup.exe` с [релизов](https://github.com/A3rtdha/eblit/releases/latest). Установщик поставит WARP (если его нет), sing-box и саму программу в `%ProgramFiles%\Eblit`.

Обновление из окна: цифра версии внизу по центру → если есть свежее, ещё раз нажать.

## Сборка из исходников

Нужны Python 3.12, PyInstaller, `sing-box.exe` рядом с проектом.

```
pip install -r app/requirements.txt pyinstaller
copy config.example.json config.json
```

В `config.json` подставь свои VLESS (uuid, public_key, хост). Живой файл в git не лежит.

```
python -m app            # окно
python -m app.pack       # dist/Eblit/ и dist/EblitSetup.exe
```

CLI стека: `python -m app --stack start|stop|reload|test`.

## Лицензия

Пользуйся как хочешь. Ключи чужих VPN в репозиторий не клади.

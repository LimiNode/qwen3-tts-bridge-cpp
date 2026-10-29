# CLI библиотеки голосов

[English version](voice-library-cli.md)

Команды `qwen-tts voices` управляют переиспользуемыми профилями клонирования
Base-модели в пользовательском registry schema 1. Изменяемые данные не попадают
в sealed-каталог программы. Путь по умолчанию:

```text
%LOCALAPPDATA%\QwenTTSBridge\voices\registry.json
```

Путь можно задать как `voice_library.registry_path` в пользовательском config
schema 1. Относительный путь считается от каталога config.

## Основные команды

```powershell
qwen-tts voices add --id kraftwerk-ru --wav .\kraftwerk.wav `
  --text "Точный текст записи."
qwen-tts voices list --json
qwen-tts voices show kraftwerk-ru --json
qwen-tts voices verify kraftwerk-ru --backend python
qwen-tts voices prepare kraftwerk-ru --backend native `
  --native-profile q8-base-17b --json
qwen-tts voices verify kraftwerk-ru --backend native `
  --native-profile q8-base-17b
```

`voices add` проверяет WAV существующим Python preflight, сохраняет отдельную
managed-копию и SHA-256, а registry публикует атомарно. Исходный WAV пользователя
не меняется и не удаляется. Для режима без транскрипта служит
`--x-vector-only`. Без `--preserve-reference-text-whitespace` пробелы по краям
текста удаляются до фиксации профиля.

Python-совместимость не означает native-готовность. Например, допустимая для
Python запись 16 kHz регистрируется без ресемплирования, но native preparation
24 kHz её отклонит.

## Native preparation

Подготовку `.spk/.rvq` выполняет существующий native worker; Python CLI не
повторяет extraction, сериализацию или проверку формата. CLI ждёт `ready`,
проверяет ожидаемый `voice_id`, метрику `native_voice_reference_ready`, manifest,
хеши артефактов и точную привязку runtime/talker/codec. Только после этого он
обновляет основной registry с `prepare_if_missing: false`.

Для каждой точной комбинации runtime и моделей хранится отдельный элемент
`native_references` с digest-ключом. Смена модели не приводит к молчаливому
использованию старого reference. Повторная подготовка уже валидного профиля
идемпотентна и не запускает extraction. Повреждённый или устаревший exact
artifact отклоняется без автоматической перезаписи.

Статусы проверки различают `compatible`, `incompatible`, `unprepared`,
`prepared_valid`, `prepared_stale`, `prepared_corrupt` и `model_unavailable`.
Наличие одного `manifest.json` само по себе не считается успехом.

Для резервной копии переносите весь каталог `voices`, когда команды изменения
не выполняются. Managed WAV можно использовать как Python reference на другой
установке. Native `.spk/.rvq` действительны только для записанных в manifest
runtime/ABI и точных хешей моделей; они не являются Python prompt и не
переносятся между Q8_0, Q4 и другими моделями автоматически.

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

Синтез через поддерживаемый persistent Python-маршрут Base 1.7B:

```powershell
qwen-tts synth --voice-id kraftwerk-ru `
  --text "Привет! Это зарегистрированный голос Base." `
  --language Russian --out .\speech.wav
```

`synth` требует существующий Python-совместимый managed-профиль. Команда
передаёт authoritative registry и `voice_id` в `qwen_tts_save_wav` и persistent
worker, по умолчанию требует natural EOS, затем проверяет непустой WAV 24 kHz
mono PCM16 и result JSON schema 1 до последовательной публикации файлов.
`--allow-non-natural-eos` предназначен только для явной диагностической отмены
этого требования. Команда не скачивает модель, не создаёт и не изменяет запись
registry, не откатывается к прямому WAV и не переключает backend или семейство
модели молча.

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

`design` создаёт новую VoiceDesign rendition, а `synth` переиспользует
зарегистрированный Base-профиль. Native preparation и native synthesis — разные
возможности: наличие подготовленных `.spk/.rvq` не заставляет `qwen-tts synth`
выбрать native backend, а native-профиль не взаимозаменяем с Python prompt.

Для резервной копии переносите весь каталог `voices`, когда команды изменения
не выполняются. Managed WAV можно использовать как Python reference на другой
установке. Native `.spk/.rvq` действительны только для записанных в manifest
runtime/ABI и точных хешей моделей; они не являются Python prompt и не
переносятся между Q8_0, Q4 и другими моделями автоматически.

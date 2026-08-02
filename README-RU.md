# QwenTTSBridge

[English README](README.md)

QwenTTSBridge - Windows-first библиотека-клиент на C++17 для локального
потокового инференса Qwen3-TTS. Python, PyTorch, CUDA и модель работают в одном
постоянном worker-процессе, а C++-приложение получает PCM через API,
ориентированный на асинхронные запросы.

Это bridge, а не реализация Qwen3-TTS на C++. Worker загружает модель один раз,
принимает несколько запросов, передаёт фреймированный PCM по локальным
stdin/stdout и поддерживает отмену по ID запроса.

## Основные возможности

- Постоянный локальный worker, асинхронная отправка C++-запросов и PCM-callback.
- Фреймированный бинарный протокол, ограниченные очереди, детерминированная
  остановка worker и тесты с mock-worker без CUDA.
- Поля запроса хранят отдельно текст, язык, необязательный speaker и
  естественную инструкцию стиля; поддержка зависит от семейства модели и
  документируется для каждой модели отдельно.
- Примеры для WAV и воспроизведения через устройство по умолчанию.
- Узкий измеренный internal opt-in профиль `torch.compile` для одного
  закреплённого RTX 4090 с 48 GiB; default остаётся eager и не меняется.

Клонирование голоса Base-моделью доступно через пример playback; обычный
runtime `0.6B-CustomVoice` по-прежнему работает с предустановленными голосами.
Инструкцию по референсному аудио смотрите в
[Local Voice Clone](docs/voice-clone-ru.md).

## Быстрый старт

Сконфигурируйте и соберите проект через CMake:

```powershell
cmake -S . -B build -DQWEN_TTS_BRIDGE_BUILD_TESTS=ON
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
```

При одноконфигурационной сборке MinGW исполняемые файлы находятся прямо в
`build`; многоконфигурационные генераторы вроде Visual Studio используют
`build\Release`.

Для mock-примера WAV не нужны CUDA и модель:

```powershell
.\build\qwen_tts_save_wav.exe --mock --output sample.wav --text "Hello from QwenTTSBridge"
```

Для реального worker укажите packaged worker либо выбранный Python launcher и
профиль модели. Runtime-конфигурация намеренно не зашита в C++.

Portable Python worker собирается из локальных wheel-файлов и помечает свой
output файлом `.qtb-portable-worker-root`. При его запуске через
`StdIoTransport` задавайте `environment_overrides` как полную замену окружения
с `PYTHONHOME`, `PYTHONPATH` и нужными Windows runtime-переменными; не
наследуйте произвольное development Python окружение в packaged worker.

## Интерактивный Playback CLI

`qwen_tts_play` - пример и smoke-инструмент для Windows. Он отправляет
потоковый 16-битный PCM на устройство вывода по умолчанию через Windows
multimedia API.

Для закреплённого internal RTX 4090 profile один раз создайте игнорируемый
локальный runtime-файл из `config/playback-runtime.local.example.json`, после
чего worker-аргументы не нужно повторять при каждом запуске:

```powershell
Copy-Item config\playback-runtime.local.example.json config\playback-runtime.local.json
# Укажите три локальных пути в playback-runtime.local.json.
scripts\start-qwen-tts-play.ps1
```

Launcher по умолчанию использует sealed R10 profile и запускает его preflight.
`-Text "Hello"` выполняет одноразовый playback smoke, а `-DryRun` показывает
итоговую команду без запуска worker. Параметры `-Speaker`, `-Language`,
`-Instruction`, `-Temperature`, `-TopK`, `-TopP`, `-RepetitionPenalty`, `-Seed`
и `-NoSample` переопределяют сохранённые настройки на один запуск **только с
`-StyleExperiment`**. Sealed R10 profile по умолчанию отклоняет request-level
sampling, чтобы не менять измеренный контракт. Пятиминутный
timeout запуска worker учитывает измеренное время compile/prime для R10; его
можно изменить через `-StartupTimeoutMs`.

```powershell
scripts\start-qwen-tts-play.ps1 -Text "Hello" -Speaker serena -Language English
```

Введите текст для озвучивания. Пока запрос выполняется, новая строка отменяет
предыдущую генерацию и поставленный звук, затем запускает новый запрос. Для
отмены используйте `/cancel`; для выбора голоса - `/voice <name>`; также
доступны `/language <name>`, `/style <text>`, `/temperature <value>`,
`/seed <value>`, `/sample <on|off>`, `/sampling`, `/help` и `/quit`.

`--text "..."` запускает одноразовый playback smoke, а `--mock` проверяет CLI
на встроенном mock-worker. Пример воспроизведения намеренно остаётся небольшой
утилитой для Windows, а не будущим кроссплатформенным аудиослоем библиотеки.

Практическое использование CustomVoice, приёмы для русского произношения,
команды CLI и ограничения текущей модели описаны в
[руководстве](docs/using-qwen-customvoice-and-cli-ru.md)
([English version](docs/using-qwen-customvoice-and-cli.md)).

## Публичный C++ API

Подключайте только нужную доменную поверхность:

```cpp
#include <qwen_tts_bridge/client.hpp>
#include <qwen_tts_bridge/audio.hpp>
#include <qwen_tts_bridge/transport.hpp>
```

Единого `qwen_tts_bridge.hpp` намеренно нет: `client.hpp`, `audio.hpp`,
`transport.hpp`, `session.hpp`, `data.hpp` и protocol umbrella-заголовки держат
зависимости явными и следуют доменной структуре репозитория.

```cpp
qwen_tts_bridge::QwenTtsClient client;
client.start(worker_options);

qwen_tts_bridge::TtsRequest request;
request.text = "Hello";
request.speaker = "serena";

const auto id = client.synthesize_async(request, callbacks);
client.cancel(id);
```

`synthesize_async()` возвращает управление после локального принятия запроса и
не ждёт инференс модели. Аудио, completion, cancellation и ошибки приходят через
callback на dispatcher-потоке клиента.

## Измеренный Internal Profile

Project default не компилируется. Отдельный internal profile был валидирован на
**закреплённой NVIDIA GeForce RTX 4090, сообщающей о 48 GiB VRAM**, с
закреплённым bundle модели, runtime и исходников:

| Метрика | Результат |
| --- | ---: |
| Проверенные compiled prefill lengths | `18, 19, 20, 26, 27, 29` |
| Compiled schedule | `8, 8, 12` |
| Среднее / p95 first audio на frozen holdout из 500 строк | 368.7 ms / 428.3 ms |
| RTF frozen holdout | около 0.372 |
| Exact compiled coverage на этом holdout | 99 / 500 (19.8%) |
| Python operational soak | 504 операции; 396 completed, 108 cancelled |
| C++ API soak | 250 операций; 225 completed, 25 cancelled |

Большинство форм holdout намеренно остаются eager. В operational smoke eager
tail достигал примерно 1.17--1.18 s p95 first audio, поэтому таблица не является
SLA для произвольного текста. Другие подходящие CUDA GPU могут использовать
generic eager path, но для этого compiled profile им нужны отдельные измерения.

О методе, области применимости, ссылках на evidence и не-A/B внешнем сравнении
читайте [отчёт RTX 4090](docs/reports/frequency-r10-rtx4090.md). Полный контракт
профиля находится в [frequency-r10-internal-opt-in-candidate.md](docs/frequency-r10-internal-opt-in-candidate.md).

## Исследования и Evidence

- [Индекс исследовательских отчётов](docs/reports/README.md)
- [Representative corpus v4](docs/reports/benchmark-corpus-v4.md)
- [Решения по оптимизации](docs/reports/optimization-decisions.md)
- [R10 operational evidence](docs/benchmark-artifacts/rtx4090-2026-08-01/frequency-exact-allowlist-operational-r10/README.md)

Benchmark corpus содержит 2,000 уникальных русских, английских и смешанных
реплик из игровых и live-stream сценариев. Он создавался с LLM-помощью на основе
языковых/сценарных паттернов реальных стримов, затем проходил валидацию и human
adjudication; это не корпус дословных транскриптов. Frozen holdout сохранён для
оценки и не используется для настройки exact allowlist.

## Текущие границы

- Пока нет удалённого network API и WebSocket transport.
- Model weights не входят в репозиторий.
- Клонирование голоса поддержано для Base-моделей через локальный WAV и его
  транскрипт; оно не относится к `0.6B-CustomVoice`.
- Packaged worker ориентирован на Windows x64 и Python 3.11.
- Compiled profile RTX 4090 - opt-in и fail-closed; он не включает компиляцию
  для неизвестных форм входа.

## Разработка

Для установки и проверки Python worker используйте проектные скрипты:

```powershell
scripts\setup-python-dev.ps1 -UseVenv
scripts\check-python.ps1 -UseVenv
```

Смотрите [AGENTS.md](AGENTS.md): там описаны архитектура репозитория, политика
зависимостей, языковая политика документации и требования к тестам.

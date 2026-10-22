# QwenTTSBridge

QwenTTSBridge — Windows-ориентированный C++17-мост к локальному Qwen3-TTS.
Публичный API асинхронный: приложение отправляет запрос, а PCM приходит
порциями через callbacks. Worker запускается один раз и сохраняет загруженную
модель между запросами.

## Текущий статус

Основной принятый production- и packaging-маршрут — persistent Python/PyTorch
worker. Native worker на `qwentts.cpp`/GGML доступен как opt-in backend и
проходит отдельные проверки качества, отмены, ABI и целевого железа. Это не
означает, что native и Python backend имеют одинаковую производительность или
одинаковую степень acceptance.

In-process адаптер `qwen.dll` остаётся экспериментальным. Модели и runtime не
хранятся в репозитории.

Краткая доказательная сводка текущей архитектуры и уже достигнутых этапов
находится в [docs/project-status.md](docs/project-status.md). В частности, в
репозитории уже зафиксированы успешная opt-in сборка native
`qwen.dll`/qwentts.cpp и аппаратно проверенный экспериментальный русский
профиль с ударениями; ни один из них не стал production default.

## Что уже работает и проверено

- Persistent Python worker остаётся принятым production- и packaging-маршрутом.
- Opt-in native path собирает общий `qwen.dll`, загружает split talker/codec
  runtime и выдаёт потоковый PCM на проверенной конфигурации CMP 50HX.
- Экспериментальный `ru-stress` профиль проверен с голосом
  `kraftwerk_robot_ru_warm`. Расширенный корпус из 12 русских фраз прошёл
  прослушивание: текст понятен, явные ударения слышны в заданных местах,
  естественное завершение и непустой PCM получены во всех случаях.
- `tts-front-cpp` v0.2.2 передаёт model-neutral `PreparedText` с данными о
  произношении и семантических ударениях.
- Опциональный speech-animation adapter проверен на реальном Qwen receipt:
  PCM и animation timeline непрерывны, terminal fade привязан к концу PCM,
  playback вызывается первым, а сбой анимации не меняет lifecycle TTS. Это
  закрывает audio-reactive v0 data path, но не готовую интеграцию аватара.

Русский профиль и native path остаются экспериментальными и opt-in. Полные
provenance и receipts перечислены в [docs/project-status.md](docs/project-status.md).

## Возможности и семейства моделей

| Семейство | Поля запроса | Статус |
| --- | --- | --- |
| CustomVoice 0.6B/1.7B | текст, язык, speaker, optional instruction | Реализовано через worker; проверяйте конкретную модель и runtime |
| VoiceDesign 1.7B | текст, язык, непустое описание голоса в `instruction` | API и worker path реализованы; real-model acceptance выполняется отдельно |
| Base 0.6B/1.7B | текст, язык, reference audio или зарегистрированный voice profile | Реализовано клонирование голоса и работа с референсами |

Streaming зависит от выбранного backend и wrapper модели. Если runtime умеет
только полную генерацию, такой результат нельзя называть realtime streaming.

VoiceDesign не использует preset speaker, `voice_id` или Base reference fields.
Python worker отклоняет эти поля, чтобы они не терялись молча.

## Быстрый старт

Для native bundle скопируйте конфигурацию и укажите внешние runtime/GGUF:

```powershell
Copy-Item config/native-worker.example.json config/native-worker.local.json
.\scripts\start-native-play.ps1 -Text "Привет"
```

Native launcher проверяет существующие модели и скачивает отсутствующие только
при явно заданных URL и SHA-256. Для закрытого окружения используйте
`-Offline` или `-NoDownload`.

Для Python worker установите пакет worker и передайте путь к модели через
`--model-path`. Подробности упаковки находятся в основном
[README.md](README.md) и в `scripts/`.

## VoiceDesign → WAV

Существующий `qwen_tts_save_wav` сохраняет PCM и не дублирует синтез. Для
воспроизводимого smoke-теста используйте:

```powershell
.\scripts\start-voice-design-save-wav.ps1 `
  -SaveWavExecutable .\build\default\Release\qwen_tts_save_wav.exe `
  -Worker .\dist\QwenTTSBridge\worker\qwen_tts_worker.exe `
  -WorkerArgument @("--engine", "qwen", "--model-path", "D:\Models\Qwen3-TTS-12Hz-1.7B-VoiceDesign") `
  -Text "Привет! Я рада тебя видеть." `
  -Instruction "Мягкий, спокойный женский голос с естественной артикуляцией." `
  -Language Russian `
  -Output .\artifacts\voice-design.wav `
  -RequireNaturalEos
```

Wrapper проверяет terminal result JSON и PCM16 WAV: sample rate, число каналов,
разрядность и ненулевой объём данных. Веса VoiceDesign и native GGUF не входят
в репозиторий, поэтому реальный GPU acceptance отмечается `PASS` только вместе
с receipt, а при отсутствии артефактов — `NOT RUN`.

Полное описание параметров и native-примера: [docs/voice-design-acceptance.md](docs/voice-design-acceptance.md).

## C++ API

Публичный API уже реализован как асинхронный клиент. Объявления находятся в
[`src/qwen_tts_bridge/client/QwenTtsClient.hpp`](src/qwen_tts_bridge/client/QwenTtsClient.hpp),
а полный минимальный исполняемый пример — в
[`examples/basic_synthesis.cpp`](examples/basic_synthesis.cpp).

```cpp
QwenTtsClient tts;
tts.start("qwen_tts_worker.exe");

TtsRequest request;
request.text = "Первая фраза";
request.language = "Russian";
request.instruction = "Спокойный тёплый голос.";

const auto id = tts.synthesize_async(std::move(request), callbacks);
if (id == 0) {
    tts.stop();
    return 1;
}
// Условное ожидание: реальный пример использует condition_variable.
wait_until_terminal();
tts.stop();
```

Worker и transport скрыты за `QwenTtsClient`. Внутри используются framed
stdin/stdout, request IDs, очередь запросов, dispatcher и отдельные terminal
events (`completed`, `cancelled`, `error`).

## Архитектура и границы

```text
Application
    |
    +--> optional tts-front-cpp v0.2.2
    |        |
    |        v
    |     PreparedText / pronunciation evidence
    |        |
    `------> QwenTtsClient
                 |
                 v
              QTB stdin/stdout
                 |
                 v
            selected worker
              |-- persistent Python/PyTorch/Qwen worker --+
              `-- optional native -> qwen.dll + qwentts.cpp/GGML/CUDA --+
                                                                  v
                                                        PCM + canonical sample clock
                                                                  |             |
                                                                  v             v
                                                        application-owned sink  optional speech-animation adapter
                                                                               sample-addressed timeline;
                                                                               physical playback cursor pending
```

Core bridge не владеет физическим audio sink. WaveOut, Unity, OBS и игровые
движки должны управлять собственной очередью и interruption policy. Материалы
по playback и avatar integration находятся в
[docs/audio-and-unity-integration.md](docs/audio-and-unity-integration.md).

Опциональный `tts-front-cpp` готовит текст и произношение, но не переносит
Qwen-специфическую логику в bridge. `speech-animation` получает PCM/timing
sideband отдельно от playback.

Подробная схема границ и evidence собрана в
[docs/project-status.md](docs/project-status.md). Python worker остаётся
production-маршрутом; native DLL, русский stress-профиль и speech-animation
являются отдельными opt-in/experimental слоями и не меняют PCM-контракт.
`tts-front-cpp` является опциональным: приложение может передавать уже
подготовленный запрос или использовать другой pronunciation provider. Receipt
speech-animation подтверждает sample-addressed timeline, но не физическую
синхронизацию с playback cursor.

## Сборка и тесты

Проект собирается CMake под C++17 и Windows x64. Модели, CUDA runtime и
сгенерированные `build/`/`dist/` не коммитятся.

```powershell
cmake -S . -B build -DQWEN_TTS_BRIDGE_BUILD_TESTS=ON
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
```

Python-проверки используют worker из `worker/src` и locked development tools:

```powershell
.\scripts\setup-python-dev.ps1
.\scripts\check-python.ps1
```

Для portable/Nuitka packaging используйте инструкции из основного README и
скрипты `setup-python-packaging.ps1`, `package-worker.ps1` и
`package-python-worker.ps1`.

## Документация

- [Основной README на английском](README.md)
- [VoiceDesign acceptance](docs/voice-design-acceptance.md)
- [Native qwentts backend](docs/native-qwentts-backend.md)
- [Текущий статус и подтверждённая архитектура](docs/project-status.md)
- [tts-front-cpp integration](docs/tts-front-integration.md)
- [Russian stress model compatibility](docs/russian-stress-model-compatibility.md)
- [Speech-animation integration](docs/speech-animation-integration.md)
- [Протокол QTB v1](docs/protocol-v1.md)
- [Audio и Unity integration](docs/audio-and-unity-integration.md)
- [Примеры](examples/README.md)

Исследовательские benchmark-отчёты и аппаратные receipts находятся в `docs/`;
они не являются обещанием одинакового поведения для всех моделей и GPU.

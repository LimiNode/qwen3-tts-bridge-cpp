# Локальное клонирование голоса

Base-модели Qwen3-TTS могут синтезировать речь по локальному референсному WAV.
Это отдельный режим, не связанный с предустановленными голосами CustomVoice.
Production-путь регистрирует референс один раз, подготавливает prompt при
запуске worker и затем выбирает его по стабильному `voice_id`.

## Реестр

Скопируйте `config/voice-profiles.example.json` в игнорируемый локальный файл и
сохраните ту же схему:

```json
{
  "schema_version": 1,
  "voices": [
    {
      "voice_id": "my_voice",
      "reference_audio_path": "C:/voices/reference.wav",
      "reference_text": "Точная расшифровка референсной записи.",
      "x_vector_only": false
    }
  ]
}
```

Путь может быть абсолютным или относительным к файлу реестра. Используйте
монофонический WAV и точную расшифровку. Worker проверяет профиль до события
ready и повторно использует подготовленный prompt во всех запросах постоянной
сессии.

## Проверка воспроизведения

Соберите `qwen_tts_play`, затем выполните:

```powershell
scripts/start-qwen-tts-clone-play.ps1 `
  -BuildDirectory build/Release `
  -Python C:/runtime/python.exe `
  -ModelPath C:/models/Qwen3-TTS-12Hz-1.7B-Base `
  -VoiceRegistryPath config/voice-profiles.local.json `
  -VoiceId my_voice `
  -Text "Проверка клонированного голоса"
```

Нельзя одновременно передавать preset `speaker` и Base `voice_id`. Передача
референсного аудио в каждом запросе остаётся диагностическим режимом;
приложениям следует использовать зарегистрированные профили, чтобы подготовка
не попадала в задержку запроса.

## Профили CMP 50HX

Launcher предоставляет четыре явных профиля через `-RuntimeProfile`:

| Профиль | Ёмкость Talker | Эмиссия / decoder | Первый PCM | Назначение |
| --- | ---: | --- | ---: | --- |
| `cmp50hx-fastest` | 448 | сначала E3, затем E4 / W29 | около 0,53 с | Короткие звуки с приоритетом минимальной задержки; prefix-KV может немного изменить произношение |
| `cmp50hx-ultra-low-latency` | 448 | сначала E3, затем E4 / W29 | около 0,61 с | Самые короткие ограниченные реплики без prefix-KV |
| `cmp50hx-low-latency` | 768 | E4 / W33 | около 0,68 с | Короткие и средние ограниченные реплики ассистента или аватара |
| `cmp50hx-safe` | 2048 | E8 / W33 | около 0,97 с | Длинный текст или заранее неизвестная длительность |

Профиль выбирается при запуске worker. Нельзя изменять статический CUDA Graph
во время запроса. Для переключения без перезагрузки автоматический роутер держит
одновременно прогретыми `cmp50hx-fastest` и `cmp50hx-safe`, а затем выбирает
worker до отправки очередной реплики:

```powershell
scripts/start-qwen-tts-clone-play.ps1 `
  -BuildDirectory build/Release `
  -Python C:/runtime/python.exe `
  -RuntimeProfile cmp50hx-fastest `
  -AutoProfile `
  -VoiceRegistryPath config/voice-profiles.local.json `
  -VoiceId my_voice `
  -Interactive
```

По умолчанию быстрый worker используется до 240 непробельных UTF-8 байт,
дальше выбирается safe. Порог можно изменить параметром
`-AutoFastMaxChars`. Два прогретых worker требуют около 11,9 ГиБ VRAM;
для этого режима нужно оставлять примерно 13 ГиБ свободной видеопамяти.

Подробные измерения находятся в
[CMP E4 throughput research](cmp50hx-e4-throughput-research.md),
[CMP latency batch research](cmp50hx-latency-batch-research.md) и
[CMP Base Startup](cmp50hx-base-profile-startup.md). Реализация роутера,
ограничения памяти и команда эксплуатационного soak-теста описаны в
[CMP automatic profile routing](cmp50hx-profile-routing.md).

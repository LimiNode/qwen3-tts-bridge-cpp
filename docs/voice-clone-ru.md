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
  -PlayerPath build/Release/qwen_tts_play.exe `
  -PythonPath py `
  -ModelPath C:/models/Qwen3-TTS-12Hz-1.7B-Base `
  -VoiceRegistryPath config/voice-profiles.local.json `
  -VoiceId my_voice `
  -Text "Проверка клонированного голоса"
```

Нельзя одновременно передавать preset `speaker` и Base `voice_id`. Передача
референсного аудио в каждом запросе остаётся диагностическим режимом;
приложениям следует использовать зарегистрированные профили, чтобы подготовка
не попадала в задержку запроса.

## Профиль CMP 50HX

Принятый idle-профиль быстрого старта использует opt-in bootstrap контекста
Base, right-padded W48 codec decode, фиксированный E8 и один playback prebuffer
chunk. Измеренная область применимости, parity, listening и точная команда
описаны в [CMP Base Startup](cmp50hx-base-profile-startup.md).

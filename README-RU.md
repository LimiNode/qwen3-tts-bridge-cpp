# QwenTTSBridge

Русское краткое описание релизной ветки находится в [README.md](README.md).
QwenTTSBridge — C++17-мост с асинхронным API к постоянному локальному
Qwen3-TTS worker-процессу. Python/PyTorch/CUDA и веса модели остаются внутри
worker, а приложение получает поток PCM через framed stdin/stdout transport.

## Быстрый старт

```powershell
qwen_tts_play.exe --worker qwen_tts_native_worker.exe --text "Привет"
```

Для bundle-local конфигурации скопируйте
`config/native-worker.example.json` в `config/native-worker.local.json`,
укажите пути к runtime и моделям и запустите
`.\scripts\start-native-play.ps1 -Text "Привет"`.

Worker требует внешний runtime, GGUF-модели и registry голосов. Эти файлы не
хранятся в репозитории; для проверки путей используйте
`scripts/ensure-native-models.ps1`. Прямой in-process `qwen.dll` включается
только явно через `QWEN_TTS_BRIDGE_BUILD_NATIVE_BACKEND=ON` и считается
экспериментальным. Примеры API перечислены в [examples/README.md](examples/README.md).

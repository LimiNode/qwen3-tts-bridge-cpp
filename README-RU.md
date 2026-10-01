# QwenTTSBridge

Русское краткое описание релизной ветки находится в [README.md](README.md).
QwenTTSBridge — C++17-мост с асинхронным API к постоянному локальному
worker-процессу Qwen3-TTS. Канонический релизный маршрут использует
`qwen_tts_native_worker.exe` и закреплённый runtime `qwentts.cpp`/GGML;
Python/PyTorch worker сохраняется как альтернативный маршрут для разработки и
упаковки. Приложение получает поток PCM через framed stdin/stdout transport.

## Быстрый старт

Для bundle-local конфигурации скопируйте
`config/native-worker.example.json` в `config/native-worker.local.json`,
укажите пути к runtime и моделям и запустите launcher:

```powershell
.\scripts\start-native-play.ps1 -Text "Привет"
```

Worker требует внешний runtime и GGUF-модели. Эти файлы не хранятся в
репозитории. Launcher проверяет модели, а загрузку отсутствующих файлов
выполняет только при заданных в конфигурации URL и SHA-256; файл загружается во
временный путь и заменяется атомарно. Для offline-пуска используйте `-Offline`
или `-NoDownload`. Репозиторий не объявляет публичный canonical URL для
split-Q8 артефактов: их источник и хэши задаёт владелец release bundle.

Прямой in-process `qwen.dll` включается только явно через
`QWEN_TTS_BRIDGE_BUILD_NATIVE_BACKEND=ON` и считается экспериментальным.
Примеры API перечислены в [examples/README.md](examples/README.md).

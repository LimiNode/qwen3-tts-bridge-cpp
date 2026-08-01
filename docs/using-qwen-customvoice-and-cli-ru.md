# Использование CustomVoice и Playback CLI

Это практическое руководство для проверенного локального сценария:
`Qwen3-TTS-12Hz-0.6B-CustomVoice` и Windows-примера `qwen_tts_play`. Оно не
означает, что все модели Qwen3-TTS имеют те же возможности.

English version: [using-qwen-customvoice-and-cli.md](using-qwen-customvoice-and-cli.md).

## Запуск интерактивного CLI

Один раз соберите `qwen_tts_play`, затем создайте игнорируемую локальную
конфигурацию из примера:

```powershell
Copy-Item config\playback-runtime.local.example.json config\playback-runtime.local.json
# Укажите python, faster_qwen_source_path и model_path в локальном файле.
.\scripts\start-qwen-tts-play.ps1
```

Локальный файл содержит пути конкретной машины и не попадает в Git. Launcher
использует закреплённый internal RTX 4090 R10 profile и его runtime preflight.
Начальная загрузка модели, warmup compiled allowlist и generation prime на
проверенной машине занимают примерно минуту. После появления приглашения `>`
вводите произносимый текст строкой.

Для одноразового smoke вместо интерактивной сессии:

```powershell
.\scripts\start-qwen-tts-play.ps1 -Text "Hello" -Speaker serena -Language English
```

`-Speaker`, `-Language` и `-Instruction` переопределяют сохранённые значения
для одного запуска launcher. Пятиминутный startup timeout намеренный: до
готовности R10 предварительно прогревает шесть точных compiled-форм.

## Интерактивные команды

| Ввод | Действие |
| --- | --- |
| Обычный текст | Отменяет текущую генерацию и поставленный звук, затем озвучивает новый текст. |
| `/cancel` | Отменяет текущую генерацию и останавливает поставленный звук. |
| `/voice <name>` | Выбирает preset-голос для будущих запросов. |
| `/language <name>` | Выбирает язык будущих запросов. |
| `/style <text>` | Сохраняет инструкцию стиля для будущих запросов; см. ограничение модели ниже. |
| `/help` | Показывает справку по командам. |
| `/quit` | Останавливает worker и завершает программу. |

`/voice` не меняет уже сгенерированное аудио. Чтобы сменить голос сразу,
задайте голос и введите новую строку: новый запрос отменит прежнюю генерацию.
`serena` и `ryan` - проверенные preset-голоса локальной модели. Неподдерживаемый
speaker worker отклонит.

## Русское произношение

CLI передаёт консольный ввод в UTF-8, поэтому поддерживает русский текст, `ё`
и обычную пунктуацию. Произношение модели всё равно вероятностное: отдельного
API для фонем или ударений нет.

Сначала добавляйте контекст. Например, `дверной замок` даёт модели больше
сигналов, чем отдельное двусмысленное слово.

Не полагайтесь на combining acute accent после гласной: `за́мок` или `замо́к`.
В локальном тесте модель 0.6B CustomVoice иногда произносила сам combining
symbol как часть слова и давала артефакты вместо подсказки ударения.

Для отдельных проблемных слов полезна ручная подсказка через изменение
написания гласной:

```text
всее
замоок
```

Это нужно прослушивать в конкретной фразе, а не применять ко всему языку:
гласная может стать слишком длинной. `е` и `ё` также можно выбирать намеренно,
когда этого требует нужное слово. В будущем прикладной словарь произношения
сможет подменять только известные проблемные слова на проверенные варианты.

## Ограничения текущего 0.6B CustomVoice

- Это модель preset-голосов. Клонирование голоса ещё не доступно в публичном
  сценарии bridge.
- Sealed R10 runtime объявляет style-инструкции неподдерживаемыми для 0.6B
  CustomVoice. Запрос с `/style` завершится понятной ошибкой, а не будет молча
  принят и проигнорирован. Не следует рассчитывать на style control в этом
  runtime profile.
- `-StyleExperiment` намеренно использует eager profile и отдельное локальное
  дерево исходников FasterQwen. Он не меняет и не переиспользует sealed R10
  allowlist. Укажите `style_experiment_faster_qwen_source_path` и запустите:

  ```powershell
  .\scripts\start-qwen-tts-play.ps1 -StyleExperiment
  ```

  Это только эксперимент для оценки instruction control. Сравните одинаковые
  текст, голос, язык и seed сначала без `/style`, затем с ним. Передача prompt
  ещё не доказывает полезного эмоционального изменения: результат нужно
  прослушать.

  Воспроизводимый A/B probe без воспроизведения фиксирует эти технические
  факты:

  ```powershell
  $env:PYTHONPATH = "C:\path\to\faster-qwen3-tts-style-experiment;worker\src"
  .\.venv-faster-qwen\Scripts\python.exe scripts\qwen_customvoice_style_ab.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "This is a controlled style test." `
    --instruction "Speak with controlled urgency." `
    --output tmp\customvoice-style-ab.json
  ```
- Нет поддерживаемого word-level контроля фонем, IPA, SSML или ударений.
- Sealed RTX 4090 R10 profile - internal opt-in профиль производительности,
  а не универсальный default для других GPU и семейств моделей. Тексты за
  пределами его точного compiled allowlist корректно используют eager fallback.
- Предупреждения `flash-attn` и SoX в этом CustomVoice path пока неблокирующие.
  Проверенный profile использует PyTorch SDPA; playback получает потоковый PCM
  24 kHz напрямую и не требует отдельный бинарник SoX.

## Диагностика

Текущий playback example передаёт stderr worker в консоль, поэтому строки с
`qtb_metric` - это диагностика, а не текст или аудиоданные. В них есть время
очереди, first audio, выбранный compiled/eager маршрут и память. Запрос с
`eager_unknown` просто имел длину вне шести prewarm-форм R10: это безопасный
fallback, а не ошибка запроса.

После успешного запроса worker пишет `completed request <id>`. Реальные ошибки
содержат отдельную категорию и сообщение.

# Использование CustomVoice и Playback CLI

Это практическое руководство для локального пути
`Qwen3-TTS-12Hz-0.6B-CustomVoice` и Windows-примера `qwen_tts_play`.
Оно не означает, что все модели Qwen3-TTS имеют такие же возможности.

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
по умолчанию использует закреплённый internal RTX 4090 R10 profile; его старт
может занять около минуты из-за загрузки модели и warmup. Для однократной
проверки используйте:

```powershell
.\scripts\start-qwen-tts-play.ps1 -Text "Hello" -Speaker serena -Language English
```

Параметры `-Speaker`, `-Language`, `-Instruction`, `-Temperature`, `-TopK`,
`-TopP`, `-RepetitionPenalty`, `-Seed` и `-NoSample` переопределяют сохранённые
значения на один запуск.

## Интерактивные команды

| Ввод | Действие |
| --- | --- |
| Обычный текст | Отменяет текущую генерацию и поставленный звук, затем озвучивает новый текст. |
| `/cancel` | Отменяет текущую генерацию и останавливает звук. |
| `/voice <name>` | Выбирает preset-голос для следующих запросов. |
| `/language <name>` | Выбирает язык следующих запросов. |
| `/style <text>` | Сохраняет style-инструкцию для следующих запросов. |
| `/temperature <value\|default>` | Устанавливает температуру или возвращает значение профиля. |
| `/top-k <value\|default>` | Устанавливает top-k или возвращает значение профиля. |
| `/top-p <value\|default>` | Устанавливает top-p или возвращает значение профиля. |
| `/repetition-penalty <value\|default>` | Устанавливает penalty или возвращает значение профиля. |
| `/sample <on\|off\|default>` | Включает sampling, greedy decoding или значение профиля. |
| `/seed <value\|default>` | Устанавливает seed либо возвращает политику worker. `off` сохранён как alias для `default`. |
| `/sampling` | Показывает текущие overrides и capabilities worker; `<worker default>` означает значение профиля. Worker логирует итоговые настройки как `request_effective_generation_settings`. |
| `/help` | Показывает справку. |
| `/quit` | Останавливает worker и завершает программу. |

Чтобы сменить голос или настройки сразу, задайте команду и отправьте новую
строку текста: новый запрос отменит прежнюю генерацию. `serena` и `ryan` —
известные preset-голоса локальной модели.

## Sampling и стабильность произношения

Экспериментальный CustomVoice profile запускается с `temperature = 0.4`,
`top_k = 50`, `top_p = 1.0`, `repetition_penalty = 1.05` и включённым sampling.
Температура `0.4` заметно консервативнее upstream default `0.9`: обычно она
уменьшает разницу между одинаковыми фразами, сохраняя часть интонации. Она не
добавляет фонемный API или управление ударениями.
Команды request-level sampling включены только с `-StyleExperiment`; sealed
R10 profile отклоняет их, чтобы его измеренный operating contract не менялся.
CLI сообщает об этом до отправки запроса. То же ограничение действует для
one-shot sampling-флагов.

Перед сравнением style, орфографической подсказки или произношения зафиксируйте
seed:

```text
/seed 4242
/temperature 0.4
/sample on
```

`/sample off` включает greedy decoding. Это самый строгий режим повторяемости,
но речь может стать менее живой, а влияние style — слабее. `top_k` ограничивает
список кандидатов; меньшие значения обычно консервативнее. `top_p` оставляет
наиболее вероятную суммарную массу кандидатов; его уменьшение также снижает
вариативность. Большой repetition penalty подавляет повторения, но может
ухудшить естественность. Меняйте по одному параметру и слушайте целую фразу.

## Русское произношение

CLI передаёт UTF-8, но модель остаётся вероятностной и не имеет API для фонем,
IPA, SSML или ударений. Сначала добавляйте контекст. Не полагайтесь на combining
acute accent после гласной: на 0.6B CustomVoice он иногда превращается в
артефакт. Для отдельных слов можно после прослушивания вручную удлинить гласную
или выбрать `е`/`ё`, например `всее` или `замоок`. Это подсказка для конкретной
фразы, а не автоматическое правило языка.

## Ограничения 0.6B CustomVoice

- Модель использует preset-голоса; voice cloning ещё не доступен в публичном
  bridge workflow.
- Sealed R10 profile корректно отклоняет style instructions для 0.6B
  CustomVoice. Для эксперимента со стилем используйте отдельный eager runtime:

  ```powershell
  .\scripts\start-qwen-tts-play.ps1 -StyleExperiment
  ```

  Для него нужен `style_experiment_faster_qwen_source_path` в локальной
  конфигурации. Он не меняет R10 allowlist. Сравнивайте одинаковые text,
  speaker, language, seed и sampling settings с `/style` и без него. Перед
  `worker_ready` эксперимент намеренно завершает одну короткую синтезацию с
  instruction: запуск занимает дольше, зато первая введённая фраза больше не
  отвечает за захват CUDA graph и первый проход пути instruction.
- Предупреждения `flash-attn` и SoX сейчас неблокирующие: проверенный путь
  использует PyTorch SDPA и проигрывает 24 kHz PCM напрямую.

## Диагностика

Строки `qtb_metric` — telemetry worker из stderr, а не озвучиваемый текст.
`completed request <id>` означает успешное завершение. `eager_unknown` для
закреплённого R10 — безопасный fallback формы, а не ошибка запроса.

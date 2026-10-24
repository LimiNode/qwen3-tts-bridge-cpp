# tts-front-cpp v0.2.2 → v0.2.3 effective-text comparison

This report records the B2-1 comparison of the exact UTF-8 text that the
bridge sends to Qwen through `PreparedText::effective_text`.

## Revisions and method

| Version | Git revision |
| --- | --- |
| v0.2.2 | `f828893b46728544041ab577215640338756a9d4` |
| v0.2.3 | `52383911290aabe6e2963ec434d195fdeaac0aad` |

The same bridge commit, compiler, Release configuration, corpus source, and
options were used for both runs. The corpus executable is
`tts_front_effective_text_corpus`; it emits the input, normalized text,
pronunciation text, effective text, and warning count as UTF-8 JSON. The
comparison was run with:

```powershell
cmake --build .tmp/b2-1-build-v022 --config Release --target tts_front_effective_text_corpus
.\.tmp\b2-1-build-v022\Release\tts_front_effective_text_corpus.exe --stdout > .tmp\b2-1-v022.json

cmake --build .tmp/b2-1-build-v023 --config Release --target tts_front_effective_text_corpus
.\.tmp\b2-1-build-v023\Release\tts_front_effective_text_corpus.exe --stdout > .tmp\b2-1-v023.json
```

All temporary output stays under the repository worktree's `.tmp/` directory.

## Corpus result

The corpus covers Russian stress marks, numbers, currency prefixes and
postfixes, agreement/genitive contexts, dates and time, abbreviations,
protected technical spans, mixed-language candidate segmentation, English
controls, and an unchanged plain-text control.

| Case | v0.2.2 effective text | v0.2.3 effective text | Warnings | Classification |
| --- | --- | --- | --- | --- |
| `ru_stress_homographs` | `за́мок мука́ го́ре` | `за́мок мука́ го́ре` | 0 → 0 | unchanged control |
| `ru_numbers` | `В две тысячи двадцать шесть году два книги и пять домов.` | `В две тысячи двадцать шесть году два книги и пять домов.` | 0 → 0 | unchanged control |
| `ru_currency` | `Цена: 1 234,50 ₽ и пятьдесят евро.` | `Цена: 1 234,50 ₽ и пятьдесят евро.` | 1 → 1 | unchanged control |
| `ru_agreement` | `У 21-го клиента три новых договора.` | `У 21-го клиента три новых договора.` | 1 → 1 | unchanged control |
| `ru_abbreviations` | `API, RTX 4090 и CUDA 13.3 готовы.` | `API, RTX 4090 и CUDA 13.3 готовы.` | 0 → 0 | unchanged control |
| `ru_date_time` | `В две тысячи двадцать шестом году встреча в четырнадцать часов тридцать минут.` | `В две тысячи двадцать шестом году встреча в четырнадцать часов тридцать минут.` | 0 → 0 | unchanged control |
| `mixed_technical` | `Сегодня API v2.3 работает через HTTP/2.` | `Сегодня API v2.3 работает через HTTP/2.` | 1 → 1 | unchanged control |
| `en_controls` | `Build forty two uses CUDA 13.3 on 2026-10-24.` | `Build forty two uses CUDA 13.3 on 2026-10-24.` | 1 → 1 | unchanged control |
| `unchanged_plain` | `Простая фраза без чисел.` | `Простая фраза без чисел.` | 0 → 0 | unchanged control |
| `currency_prefixes` | `$ 1,234.50; €-2.00; £ 3.5; ¥+4,50.` | `$ 1,234.50; €-2.00; £ 3.5; ¥+4,50.` | 4 → 4 | unchanged control |
| `currency_continuations` | `$1,23% 456 and €1,234/five hundred sixty seven.` | `$1,23% 456 and €1,234/five hundred sixty seven.` | 2 → 2 | unchanged control |
| `technical_protected` | `https://example.com/$1,234%25 RTX-4090/123 C++17,234%25` | `https://example.com/$1,234%25 RTX-4090/123 C++17,234%25` | 3 → 3 | unchanged control |
| `mixed_segment_candidates` | `Цена twelve dollars fifty cents и три килограмма; API v2.3.` | `Цена twelve dollars fifty cents и три килограмма; API v2.3.` | 1 → 1 | unchanged control |
| `ru_genitive_decimal` | `После одна целая пять десятых попыток и две целых двадцать пять сотых часа.` | `После 1,5 попыток и две целых двадцать пять сотых часа.` | 0 → 1 | intended behavior change |

The only effective-text change is `ru_genitive_decimal`. v0.2.3 keeps the
unsupported genitive decimal surface `1,5` intact and emits one
`UnresolvedNumber` warning, instead of partially normalizing it as v0.2.2 did.
This is consistent with the v0.2.3 fail-closed currency/continuation boundary
policy and requires targeted listening acceptance before beta inclusion.

## Classification

- Intended: 1 (`ru_genitive_decimal`), pending targeted listening acceptance.
- Regression: none observed in this corpus.
- Unresolved: none observed in this corpus.
- Unchanged controls: 13, including stress, ordinary numbers, currency,
  agreement, abbreviations, dates/time, technical identifiers, mixed-language
  segmentation, and English controls.

The corpus is a focused bridge integration check, not a replacement for the
upstream tts-front quality oracle or a claim that every language surface is
unchanged. Only the changed case needs hardware/listening follow-up.

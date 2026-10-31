# tts-front-cpp v0.2.2 → v0.2.3 effective-text comparison

This report records the B2-1 comparison of the exact UTF-8 text that the
bridge sends to Qwen through `PreparedText::effective_text`.

## Revisions and method

The historical comparison was executed with bridge revision
`c1936f78ac6cdb7938b9a70d4aee50c6f5936c4f`. The current rebased PR #231 HEAD
is `94f9d193cb6f00ffbe77d54ecdb1d2c554ec1520`; it contains the same comparison
result and is the revision under review. Each version is configured in its
own independent checkout so the frontend submodule pin cannot leak between
runs.

| Version | Git revision |
| --- | --- |
| v0.2.2 | `f828893b46728544041ab577215640338756a9d4` |
| v0.2.3 | `52383911290aabe6e2963ec434d195fdeaac0aad` |

The reproducible setup below is for Windows x64, Visual Studio 17 2022, and
Release configuration. It creates independent source checkouts under
`.worktrees/`, CMake build trees under `.build/`, and generated receipts under
`.tmp/`; replace `$repoUrl` with the bridge remote when reproducing outside the
repository checkout:

```powershell
$bridgeRevision = "c1936f78ac6cdb7938b9a70d4aee50c6f5936c4f"
$repoUrl = "https://github.com/LimiNode/qwen3-tts-bridge-cpp.git"
$repoRoot = git rev-parse --show-toplevel
$sourceRoot = Join-Path $repoRoot ".worktrees\b2-1-repro"
$buildRoot = Join-Path $repoRoot ".build\b2-1-repro"
$resultRoot = Join-Path $repoRoot ".tmp\b2-1-repro"
New-Item -ItemType Directory -Force $resultRoot | Out-Null

git clone --no-checkout $repoUrl "$sourceRoot\v022"
git clone --no-checkout $repoUrl "$sourceRoot\v023"
foreach ($version in @("v022", "v023")) {
    git -C "$sourceRoot\$version" checkout $bridgeRevision
    git -C "$sourceRoot\$version" submodule update --init --recursive
}
git -C "$sourceRoot\v022\external\cpp\tts-front-cpp" checkout f828893b46728544041ab577215640338756a9d4
git -C "$sourceRoot\v023\external\cpp\tts-front-cpp" checkout 52383911290aabe6e2963ec434d195fdeaac0aad

cmake -S "$sourceRoot\v022" -B "$buildRoot\v022" -G "Visual Studio 17 2022" -A x64 `
    -DQWEN_TTS_BRIDGE_BUILD_TESTS=ON -DQWEN_TTS_BRIDGE_BUILD_TTS_FRONT=ON
cmake -S "$sourceRoot\v023" -B "$buildRoot\v023" -G "Visual Studio 17 2022" -A x64 `
    -DQWEN_TTS_BRIDGE_BUILD_TESTS=ON -DQWEN_TTS_BRIDGE_BUILD_TTS_FRONT=ON
```

The corpus executable is `tts_front_effective_text_corpus`; it emits the input,
normalized text, pronunciation text, effective text, warning count, uncertainty
state, and warning diagnostics as UTF-8 JSON. Build and run both independent
trees with:

```powershell
cmake --build "$buildRoot\v022" --config Release --target tts_front_effective_text_corpus
& "$buildRoot\v022\Release\tts_front_effective_text_corpus.exe" --stdout --emit-only > "$resultRoot\v022.json"

cmake --build "$buildRoot\v023" --config Release --target tts_front_effective_text_corpus
& "$buildRoot\v023\Release\tts_front_effective_text_corpus.exe" --stdout > "$resultRoot\v023.json"
```

The v0.2.2 invocation uses `--emit-only` because the executable's default
oracle asserts the v0.2.3 contract; both invocations still emit the same JSON
schema for differential comparison. Source checkouts stay under `.worktrees/`,
build trees under `.build/`, and generated JSON receipts under `.tmp/`. The
expected bridge flags are
`QWEN_TTS_BRIDGE_BUILD_TESTS=ON` and `QWEN_TTS_BRIDGE_BUILD_TTS_FRONT=ON` in
both configurations.

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
| `ru_supported_decimal` | `В отчёте одна целая пять десятых метра.` | `В отчёте одна целая пять десятых метра.` | 0 → 0 | supported decimal control |
| `ru_genitive_decimal` | `После одна целая пять десятых попыток и две целых двадцать пять сотых часа.` | `После 1,5 попыток и две целых двадцать пять сотых часа.` | 0 → 1 | intended behavior change |

The only effective-text change is `ru_genitive_decimal`. v0.2.3 keeps the
unsupported genitive decimal surface `1,5` intact and emits one
`UnresolvedNumber` warning, instead of partially normalizing it as v0.2.2 did.
This is consistent with the v0.2.3 fail-closed currency/continuation boundary
policy and requires targeted listening acceptance before beta inclusion.

The v0.2.3 diagnostic evidence for the changed and neighboring decimal cases
is fixed by the corpus oracle:

```json
[
  {
    "id": "ru_supported_decimal",
    "effective_text": "В отчёте одна целая пять десятых метра.",
    "warning_count": 0,
    "uncertain": false,
    "warnings": []
  },
  {
    "id": "ru_genitive_decimal",
    "effective_text": "После 1,5 попыток и две целых двадцать пять сотых часа.",
    "warning_count": 1,
    "uncertain": true,
    "warnings": [
      {"code": "unresolved_number", "offset": 11, "length": 3}
    ]
  }
]
```

The serialized adapter code `unresolved_number` corresponds to the frontend
enum `WarningCode::UnresolvedNumber`. The warning span is measured in UTF-8
bytes in the original source text.

The comparison was rerun on 2026-10-24 from the common bridge revision above.
The v0.2.2 and v0.2.3 source trees were pinned only at the frontend submodule,
then built independently with the documented Visual Studio configuration. Raw
UTF-8 stdout was captured with `cmd.exe` redirection:

```powershell
cmd /c "<v022>\Release\tts_front_effective_text_corpus.exe --stdout --emit-only > <v022>.json"
cmd /c "<v023>\Release\tts_front_effective_text_corpus.exe --stdout > <v023>.json"
```

Both receipts contain 15 corpus cases. Comparing by stable case ID, with warning
arrays canonicalized by `(code, offset, length)`, produced:

```text
unchanged: 14
intended effective-text change: 1 (ru_genitive_decimal)
regressions: 0
unresolved: 0
```

The `technical_protected` case has the same effective text, warning count,
uncertainty, and warning spans in both versions; only the order of three
equivalent `unresolved_number` entries differs. It is therefore not classified
as a frontend behavior change.

## Targeted audio acceptance gate

The required listening comparison for `ru_genitive_decimal` was not run in
this repository checkout. `models/` contains only `.gitkeep`; no external Base
1.7B model snapshot, registered voice registry/reference asset, worker runtime,
or CUDA profile is available here. Consequently there is no honest PCM/EOS or
human-listening receipt to attach to this dependency comparison.

The pending gate is deliberately narrow: run the v0.2.3 effective text above
and a directly comparable unchanged control on the accepted CMP 50HX Python/Base
1.7B profile, recording model revision, voice ID and registry/reference hash,
runtime/device, seed when supported, PCM non-empty/EOS evidence, and a human
listening verdict. The fail-closed text-preservation result is accepted
independently of pronunciation quality. PR #231 remains Draft until this gate
is completed or an external receipt is supplied.

## Classification

- Dependency pin v0.2.3: PASS.
- C++ adapter compatibility: PASS.
- 15-case effective-text regression: PASS.
- Intended `ru_genitive_decimal` text/diagnostic change: PASS.
- Targeted audio listening: NOT RUN.
- Base model availability: `MODEL_ARTIFACT_UNAVAILABLE`.

- Intended: 1 (`ru_genitive_decimal`), pending targeted listening acceptance.
- Regression: none observed in this corpus.
- Unresolved: none observed in this corpus.
- Unchanged controls: 14, including stress, ordinary numbers, currency,
  agreement, abbreviations, dates/time, technical identifiers, mixed-language
  segmentation, and English controls.

The corpus is a focused bridge integration check, not a replacement for the
upstream tts-front quality oracle or a claim that every language surface is
unchanged. Only the changed case needs hardware/listening follow-up.

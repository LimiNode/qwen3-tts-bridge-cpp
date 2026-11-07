# tts-front-cpp v0.2.2 → v0.2.5 effective-text comparison

This report records the dependency update and the bridge-level comparison of
the exact UTF-8 text and diagnostics produced by `PreparedText`.

## Revisions and method

| Item | Revision or value |
| --- | --- |
| Bridge revision | `cf66be08` (`docs(frontend): record v0.2.5 comparison`) |
| Corrective oracle commit | `b31228d5712c6a6e39e445de84b6fd3e014dd241` |
| Baseline frontend | `f828893b46728544041ab577215640338756a9d4` (v0.2.2) |
| Candidate frontend | `d1b6a6e18e7f51f8c51fff548bb84f10e749004a` (v0.2.5) |
| Compiler | MinGW GCC 15.2.0, C++17 |
| Build | Ninja, Release-equivalent default configuration |
| Corpus | 17 fixed bridge cases |

The two runs used independent worktrees with the same bridge revision and
different `tts-front-cpp` submodule pins. The corpus executable is
`tts_front_effective_text_corpus`; it emits the input, normalized text,
pronunciation text, effective text, uncertainty state, and warning tuples
`(code, offset, length)` as UTF-8 JSON. Raw output was captured with `cmd.exe`
redirection so PowerShell encoding cannot alter the bytes.

The raw receipts remain local under
`.tmp/tts-front-v025/{v022-17,v025-17}.raw.json` and are not committed. Their
SHA-256 values are:

| Receipt | SHA-256 |
| --- | --- |
| v0.2.2 | `C3EF58E9C72E2CA6D24B1CE60CD6E3BA037E46460AD8091B5E0426EC42957946` |
| v0.2.5 | `C91DFF108AE4F92FDE268AB0A31D75DD896D7C4A91967F7A3015E82676027518` |

## Corpus scope and result

The cases cover Russian leading-zero years, numeric and agreement boundaries,
stress marks, dates and time, currency, abbreviations, unsupported genitive
decimals, mixed-language segmentation, English controls, technical protected
spans, and unchanged plain text.

Comparing by stable case ID and canonicalizing warning arrays by
`(code, offset, length)` produced: the committed oracle in
`tts-front-v022-v025-effective-text-fixture.json` records the exact old/new
values for every changed case; the executable corpus asserts the full
normalized text, pronunciation text, effective text, uncertainty flag, and
complete warning tuple set for all cases.

```text
cases: 17
unchanged: 13
intended effective-text changes: 3
intended diagnostic-only changes: 1
regressions: 0
unresolved: 0
```

| Case | Difference | Classification |
| --- | --- | --- |
| `ru_leading_zero_year` | v0.2.2 rewrote `0026` to `двадцать шесть`; v0.2.5 preserves `0026` and emits one `unresolved_number` over the four-byte candidate | Intended fail-closed v0.2.5 behavior; targeted listening required if this surface is advertised |
| `ru_numbers` | `двадцать шесть году` becomes `двадцать шестом году` | Intended Russian contextual year agreement; targeted listening required |
| `ru_genitive_decimal` | v0.2.2 partially rewrote `1,5`; v0.2.5 preserves `1,5` and emits one `unresolved_number` at UTF-8 byte offset 11, length 3 | Intended fail-closed behavior; targeted listening required |
| `ru_currency` | Effective text is unchanged; warning span expands from the numeric core (8 bytes) to the complete `1 234,50 ₽` candidate (12 bytes) | Intended diagnostic-boundary correction; no new audio case by itself |

The `technical_protected` warning order differs between versions, but the
canonical warning tuples and effective text are identical; it is therefore an
unchanged control, not a behavior change.

## Verification boundary

The bridge adapter and strict corpus oracle pass on the candidate. A controlled
negative run with one expected warning span altered failed the executable, and
the oracle was restored before commit. No model weights,
worker runtime, Base voice registry, or CUDA device are present in this
worktree, so PCM/EOS or human-listening acceptance for the three changed
surfaces was not run. Those cases remain the only listening follow-up before a
release claim depends on the new frontend behavior.

This dependency comparison does not change worker, native backend, protocol,
or lifecycle code. It supersedes the old v0.2.3-only comparison as the current
bridge evidence; historical PR #231 remains preserved separately.

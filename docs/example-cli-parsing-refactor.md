# Example CLI parsing refactor

This change extracts the private scalar and option-value parsing shared by the
three executable examples:

- `qwen_tts_save_wav`
- `qwen_tts_latency_benchmark`
- `qwen_tts_play`

## Before and after

Before the change, each example contained its own implementation of
`require_value`, `parse_u32`, `parse_int`, and `parse_double`; the benchmark and
play examples also contained `parse_u64`. That was three copies of the option
value helper and three copies of each scalar parser (fourteen local definitions in
total, counting the benchmark-only and play-only `parse_u64` copies).

After the change, `examples/common/cli_parsing.hpp` contains one implementation
of each helper. The examples retain their option-specific parsing, validation,
help text, diagnostics, and worker argument forwarding.

The shared unsigned parsers now explicitly reject negative syntax, including a
negative value after leading ASCII whitespace. This prevents `std::stoul` and
`std::stoull` from accepting `-1` as a wrapped unsigned maximum. Empty values,
`+1`, leading whitespace, range checks, trailing-garbage rejection, and finite
floating-point checks remain covered by direct unit tests.

`qwen_tts_play` still owns Windows `wmain()` and wide-to-UTF-8 conversion. The
shared helper receives an already converted current argument and a callback for
the next argument, so Unicode handling and the existing Windows entry point
remain in the example.

## Verification

- direct parser unit test covers `--option=value`, `--option value`, Unicode,
  missing values, signed and unsigned boundaries, `-1`, `+1`, zero, overflow,
  long decimal input, trailing garbage, whitespace, floating syntax, and
  `NaN`/`Inf` rejection;
- existing save-WAV, latency-benchmark, and playback mock CLI smoke tests pass;
- no PCM capture, receipt/diagnostics, playback orchestration, post-processing,
  worker, protocol, or public SDK code was extracted;
- remaining candidates such as full option structs, receipt formatting, and
  playback orchestration are intentionally domain-specific and remain outside
  this narrow refactor.

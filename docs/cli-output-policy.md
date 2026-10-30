# User CLI output policy

The release-facing `qwen-tts design` and `qwen-tts synth` commands are user
interfaces, not diagnostic launchers. They keep the worker and native bridge
diagnostics available without printing routine metrics during every successful
request.

## Current policy

- The default mode prints a concise completion line with the generated WAV
  path. Worker metrics and routine model/runtime messages are captured but not
  printed.
- Actionable failures retain the subprocess exit code and print a bounded
  diagnostic tail. `qtb_metric` records are omitted from that tail so a failed
  command remains readable.
- `--verbose` replays the complete captured diagnostic stream on stderr.
- `--log-file <path>` atomically writes the complete diagnostic stream,
  including unchanged `qtb_metric` lines. The file is written separately from
  the WAV and receipt outputs.
- Output capture uses a temporary file rather than an in-memory pipe, avoiding
  unbounded accumulation and pipe deadlocks while the worker streams audio.

The worker itself still emits diagnostics to stderr. The CLI owns the
presentation policy; the QTB protocol and synthesis engine are unchanged.

## Verification

The Python user-CLI tests cover quiet success, complete diagnostic logs,
verbose replay, non-zero exit propagation, bounded failure diagnostics, UTF-8
output, and output publication safety. The relocated portable CLI acceptance
script captures native stdout and stderr into owned temporary files, so a
successful native command writing diagnostic stderr is not converted into a
PowerShell `NativeCommandError`.

## Deliberately separate follow-up work

This change does not implement streaming playback, native backend selection in
the user CLI, or persistence of a generated VoiceDesign rendition as a Base
voice. Those remain independent acceptance tracks:

1. Compose `qwen-tts play` from the existing `qwen_tts_play` WinMM player and
   measure time-to-first-audio, queue starvation, and real-time factor.
2. Add explicit opt-in native synthesis only after profile, packaging,
   lifecycle, quality, and RTX 4090 gates are recorded; never fall back
   implicitly between Python and native engines.
3. Define a persistent VoiceDesign workflow only where the model provides a
   validated reusable conditioning contract; a generated WAV alone is not
   treated as a portable Base profile.

The CMP 50HX portable Base acceptance is complete, including human listening.
RTX 4090 remains a separate, not-yet-run hardware gate.

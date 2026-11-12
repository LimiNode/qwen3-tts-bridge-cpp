# `qwen-tts play`

The portable package exposes a release-facing one-shot playback command for a
registered Python Base voice (the default family is Base 1.7B):

```powershell
qwen-tts play `
  --voice-id kraftwerk-ru `
  --text "Проверка потокового воспроизведения." `
  --language Russian
```

The command validates the managed voice profile, resolves the Base 1.7B model,
starts the existing `qwen_tts_play.exe` streaming client, and routes its PCM to
the default WinMM device. It does not create a second playback pipeline.
Without `--out` it does not write a WAV file; `--out <path>` captures the PCM
through the existing C++ `WavCapture` and publishes a validated PCM16 mono
24 kHz WAV only after successful completion. `--out` and `--log-file` must not
refer to the same file. The FasterQwen backend is selected by default;
`--runtime-backend upstream` is available for an explicit comparison.

Explicit `--model-family` also selects Base 0.6B, CustomVoice 0.6B/1.7B, or
VoiceDesign. Base uses `--voice-id`; CustomVoice uses an advertised preset
`--speaker`; VoiceDesign uses `--instruction`, not a registered Base profile:

```powershell
qwen-tts play --model-family custom-0.6b --speaker ryan `
  --text "Hello." --language English --out .\speech.wav
qwen-tts play --model-family voice-design --instruction "A calm warm voice" `
  --text "Hello." --language English
```

These routes are implemented and mock-tested. Only independently accepted
model/runtime/hardware combinations may enter the advertised
[release scope](beta-release-scope.md).

Output is quiet on success. Use `--verbose` to replay bounded diagnostics or
`--log-file <path>` to retain the complete captured process output. Startup and
request timeouts can be set independently with `--startup-timeout-ms` and
`--request-timeout-ms`. A request timeout cancels the active request and still
waits for deterministic player cleanup before returning a failure.

Playback requires completion metadata confirming a generation trace with
`termination_reason=eos`, `hit_eos=true`, and no max-sequence or max-token
limit. `--allow-non-natural-eos` is an explicit diagnostic opt-out and is not
part of the accepted release path. CI's mock playback uses a relocated
packaged worker and remains synthetic evidence rather than model acceptance.

The portable release contains `bin/qwen_tts_play.exe` alongside
`qwen_tts_save_wav.exe`; the release manifest records both executable hashes.
The mock-only acceptance switches used by CI are intentionally hidden from the
public help output.

Hardware acceptance still requires a real CMP 50HX run and human listening.
RTX 4090 remains a separate validation gate.

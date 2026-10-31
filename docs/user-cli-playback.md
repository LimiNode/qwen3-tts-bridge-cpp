# `qwen-tts play`

The portable package exposes a release-facing one-shot playback command for a
registered Python Base voice:

```powershell
qwen-tts play `
  --voice-id kraftwerk-ru `
  --text "Проверка потокового воспроизведения." `
  --language Russian
```

The command validates the managed voice profile, resolves the Base 1.7B model,
starts the existing `qwen_tts_play.exe` streaming client, and routes its PCM to
the default WinMM device. It does not create a second playback pipeline and it
does not write a WAV file. The FasterQwen backend is selected by default;
`--runtime-backend upstream` is available for an explicit comparison.

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

# CMP 50HX automatic profile routing

`qwen_tts_play --auto-profile` keeps two static FasterQwen workers alive: the
configured fast worker and a derived `cmp50hx-safe` worker. Each request is sent
to one worker before synthesis starts; CUDA graphs are never changed while a
request is running.

The default policy counts non-space UTF-8 bytes as a conservative text-length
proxy. Texts up to 240 bytes use the fast worker; longer texts use the safe
worker. The threshold can be changed with `--auto-fast-max-chars` or the
launcher's `-AutoFastMaxChars`. The name is kept for CLI compatibility, but the
value is a byte budget rather than a word or language-specific token count.

Automatic mode requires the worker arguments to contain a `--runtime-profile`
option. The second worker is derived by replacing its profile and static
capacity settings with `cmp50hx-safe`, `max_seq_len=2048`, E8, and W33. Both
workers must advertise compatible voice capabilities. Since two model workers
are resident, applications should verify available VRAM before enabling this
mode. The accepted idle CMP run used about 11.9 GiB for the two warmed workers.
A later load-sensitivity run started with 8.8 GiB already occupied by another
application and reached 19.2 GiB after both workers were loaded; WDDM paging
then increased safe-profile chunk cadence above two seconds. Treat roughly
13 GiB of free VRAM as a launch-time operational floor for this exact profile
pair, and rerun the target-hardware soak after changing the model, graph
implementation, or driver.

The policy is intentionally conservative and deterministic. It does not split
one utterance into multiple requests: splitting can alter prosody and voice
continuity. A future tokenizer-aware policy may replace the byte proxy after a
multilingual boundary matrix is available.

Example:

```text
qwen_tts_play.exe --worker python.exe --auto-profile \
  --worker-arg -m --worker-arg qwen_tts_bridge_worker \
  --worker-arg qwen --worker-arg --runtime-profile \
  --worker-arg cmp50hx-fastest ...
```

The PowerShell launcher exposes the same mode:

```powershell
.\scripts\start-qwen-tts-clone-play.ps1 `
  -BuildDirectory build\Release `
  -Python C:\runtime\python.exe `
  -ModelPath C:\models\Qwen3-TTS-12Hz-1.7B-Base `
  -FasterSourcePath C:\src\faster-qwen3-tts `
  -QwenSourcePath external\python\Qwen3-TTS-streaming `
  -VoiceRegistryPath config\voice-profiles.local.json `
  -RuntimeProfile cmp50hx-fastest `
  -AutoProfile `
  -VoiceId my_voice `
  -Interactive
```

The launcher defaults to the pinned `external/python/faster-qwen3-tts` and
`external/python/Qwen3-TTS-streaming` submodules. `-FasterSourcePath` and
`-QwenSourcePath` are diagnostic overrides. The Qwen source remains explicit in
acceptance commands so the FasterQwen model always imports the patched 12 Hz
decoder instead of an unrelated user-site `qwen_tts` installation.

## Operational soak

The automatic-router soak keeps both workers alive and exercises mixed
Russian/English fast and safe routes, repeated route transitions, registered
voice A -> B -> A isolation, cancellation after first PCM, and a recovery
request. It fails on a route mismatch, non-natural completion, capacity hit, or
a steady later-chunk cadence gap longer than the preceding PCM chunk. The first
E3 -> E4 transition is excluded because the accepted playback path measures
that transition with actual WaveOut startup slack:

```powershell
py -3.11 scripts\run-cmp50hx-auto-profile-soak.py `
  --launcher scripts\start-qwen-tts-clone-play.ps1 `
  --build-directory build\Release `
  --worker-python C:\runtime\python.exe `
  --model-path C:\models\Qwen3-TTS-12Hz-1.7B-Base `
  --faster-source-path C:\src\faster-qwen3-tts `
  --qwen-source-path external\python\Qwen3-TTS-streaming `
  --voice-registry-path config\voice-profiles.local.json `
  --voice-id my_voice `
  --alternate-voice-id my_second_voice `
  --output-directory tmp\cmp50hx-auto-profile-soak
```

The JSON report and raw interleaved stdout/stderr log are intentionally written
under ignored `tmp/`. The cadence assertion is a conservative starvation proxy,
not a hardware WaveOut underrun counter; retain the existing ETW playback soak
as the sink-level release gate. Before starting either worker, the runner also
requires 13 GiB of free memory on CUDA device 0. Override
`--cuda-device-index` or `--minimum-free-vram-mib` only when validating a
different deliberate deployment contract.

`cmp50hx-fastest-experimental` remains accepted as a compatibility alias for
the fastest opt-in profile.

The option is intended for the persistent interactive CLI as well as one-shot
requests. `/cancel` cancels whichever worker owns the active request.

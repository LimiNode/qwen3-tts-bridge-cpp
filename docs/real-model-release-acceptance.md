# Real-Model Release Acceptance

Run this matrix before a Windows release that claims real Qwen3-TTS support.
It deliberately separates three model concepts:

- `ryan` and `serena` are preset speakers of the 0.6B CustomVoice model.
- A `voice_id` is a locally registered Base voice-clone profile.
- `qwen_tts_play` is the public C++ playback CLI; worker-only completion is not
  a substitute for its one-shot playback test.

The matrix uses the recommended CMP 50HX Faster configuration: right-padded
codec decode, fixed 48-frame window, manual codec CUDA Graph, 16-frame PCM
emission, and a two-chunk WaveOut prebuffer. It is an idle-machine acceptance
test. It does not promise real-time playback while another application uses the
GPU.

## Automated CustomVoice and CLI Matrix

From a checkout containing the built client, sealed Python runtime, local model,
and the versioned Faster submodule:

```powershell
.\scripts\run-real-model-release-acceptance.ps1 `
  -PlayerPath 'E:\_repoz\qwen3-tts-bridge-cpp\build\cmp50hx-diagnostic-mingw\qwen_tts_play.exe' `
  -PythonPath 'E:\_repoz\qwen3-tts-bridge-cpp\tmp\QwenTTSBridge-technical-beta-r3\QwenTTSBridge-technical-beta-r3\worker\python\python.exe' `
  -CustomVoiceModelPath 'E:\_repoz\qwen3-tts-bridge-cpp\tmp\cmp50hx-r3-external-models\Qwen3-TTS-12Hz-0.6B-CustomVoice' `
  -RuntimeCachePath 'E:\_repoz\qwen3-tts-bridge-cpp\tmp\cmp50hx-r3-runtime-cache'
```

It requires all of the following:

- `qwen_tts_play --help` documents the release-relevant options and commands;
- a single persistent worker completes sequential English/Russian CustomVoice
  requests for `ryan` and `serena` with non-empty PCM;
- CustomVoice rejects a Base `voice_id` instead of silently treating it as a
  preset speaker;
- two C++ one-shot playback runs complete without a WaveOut starvation-proxy
  outlier. The proxy is not a hardware-underrun counter.

The output directory contains the machine-readable report, worker timing
reports, and the two physical-playback summaries. It contains no model weights.
Pass `-SkipPhysicalPlayback` only for a worker/CLI-control retest; it cannot
replace the release playback check.

## Base Voice-Profile Matrix

Base voice-cloning needs its own compatible Base model, reference WAV, and local
registry. It is not part of the CustomVoice model contract. When the product
advertises profiles, require all three additional arguments:

```powershell
  -BaseModelPath 'D:\models\Qwen3-TTS-12Hz-1.7B-Base' `
  -VoiceRegistryPath 'config\voice-profiles.local.json' `
  -VoiceId 'approved_voice'
```

The runner then verifies two sequential requests on one worker and repeats the
same check after a worker restart. It fails if a request has no PCM, lacks a
first-audio/completion timing record, or the worker cannot load the selected
profile. For a registered Base profile it warms the bounded cache using that
same `voice_id`; a generic
CustomVoice-style warmup does not prepare the Base profile's first generation.

Use the separate [CMP 50HX Base-profile startup A/B](cmp50hx-base-profile-startup.md)
before making any claim about first-audio latency. Continuous delivery after
the two-chunk prebuffer and low startup latency are separate gates.

If these arguments are absent, `summary.json` marks Base profiles `not_run`.
Do not advertise clone profiles as release-validated from that run.

## Human Listening Gate

The automation verifies transport and completion, not pronunciation or voice
quality. Listen to both physical samples and mark each item pass/fail:

| Case | Listen for |
| --- | --- |
| Ryan / English | intelligible words, stable identity, no clicks or stutter |
| Serena / Russian | intelligible Russian, stable identity, no clicks or truncation |
| Long text | no late stall, repeated phrase, or early end |
| End of stream | complete final word and natural tail; no clipped tail |
| Sequential requests | the second request does not inherit audible content from the first |
| Base profile, if advertised | identity is plausible before and after worker restart |

Record the report path, GPU/driver, model revisions, and the human verdict in
the release notes. A passing idle run is evidence for that machine and runtime
fingerprint only.

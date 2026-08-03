# Local Voice Clone

Base Qwen3-TTS models can synthesize speech from a local reference WAV. This
is separate from the `0.6B-CustomVoice` preset-speaker model used by the normal
playback CLI. A reusable Base voice profile stores its reference metadata on
disk and creates the model-ready prompt once per persistent worker process.

The local `kraftwerk_robot_3_ru.wav` reference is 4.344 seconds long and has
been smoke-tested through the C++ CLI with the cached `1.7B-Base` model. A few
seconds of clear reference speech can be enough, but quality remains sensitive
to recording quality, transcript accuracy, and the target text.

For this repository's processed robotic reference, zero-shot Base ICL has not
met the product-quality gate for voice identity retention. Treat the example
profiles as diagnostics, not as production voice clones. See the detailed
[ICL diagnosis](voice-clone-diagnosis.md) before using them beyond local tests.

## Candidate Text Prefix

When making a longer synthetic reference from an ICL result, do not begin the
candidate text with the reference transcript or a close continuation of it. In
one repeated-source experiment, that overlap made the first generated utterance
repeat part of the reference before speaking the requested text.

Prefix the target with one short, neutral phrase that is absent from the
reference, for example `Привет! `. Keep that prefix in the candidate's exact
transcript if the generated WAV is later registered as a profile. First run a
small listening gate, then start a larger candidate search only if the gate is
clean. This is a tested workaround for this overlap pattern, not a general
guarantee against every Base ICL artefact.

## Bootstrap Candidate Evidence

`scripts/run-voice-clone-bootstrap-candidates.py` writes each accepted
candidate as a WAV plus a neighbouring `.wav.json` sidecar. The sidecar pins
the source text, voice-profile reference hashes, sampling settings, generation
limits, PCM/WAV hashes, full terminal-stream evidence, generation trace, and
graph-reset result. It also records the SHA-256 of a shared experiment contract
that pins the model content manifest, exact installed Python-distribution
content, Faster and bridge source trees, runner source, and Python/CUDA runtime
provenance. Absolute paths are saved only as diagnostic locations and do not
affect the identity hash.

`--resume` accepts only a matching completed sidecar. It will refuse an
untracked WAV, a changed model/runtime/code contract, a changed
seed/profile/text/sampling contract, a changed WAV, or a candidate whose saved
terminal evidence no longer proves an EOS completion and cache reset. The audio
cap is also fail-closed: a truncated stream is not written as a selectable
candidate. Sidecars written by older schemas remain historical evidence and
cannot be resumed under schema 4.

Before a bootstrap run, build a model content manifest once for the exact local
snapshot and keep it with the experiment evidence:

```powershell
.venv-faster-qwen\Scripts\python.exe scripts\model_runtime_manifest.py build `
  --model-path C:\models\Qwen3-TTS-12Hz-1.7B-Base `
  --repository Qwen/Qwen3-TTS-12Hz-1.7B-Base `
  --revision <pinned-Hugging-Face-revision> `
  --output tmp\voice-clone-bootstrap\model-runtime-manifest.json
```

Pass that file to every bootstrap invocation with
`--model-runtime-manifest`. The runner verifies the complete local model file
set before generating or resuming candidates.

Build and verify a matching Python runtime manifest in the same interpreter:

```powershell
.venv-faster-qwen\Scripts\python.exe scripts\python_runtime_manifest.py build `
  --output tmp\voice-clone-bootstrap\python-runtime-manifest.json
```

Pass it as `--python-runtime-manifest`. The runner verifies all distributions
installed in the active environment, including their recorded package files,
before generating or resuming candidates.

These guarantees make a listening selection reproducible; they do not turn a
synthetic bootstrap candidate into a verified identity clone.

## Create, Test, and Save a Profile

Use the dedicated creation command to preflight a reference WAV, run a short
test synthesis, and then explicitly save or discard the profile. Creating a
profile is separate from normal playback; it does not turn every future request
into a fresh clone operation.

```powershell
.\scripts\new-qwen-tts-voice-profile.ps1 `
  -VoiceId kraftwerk_robot_ru `
  -ReferenceAudioPath .\examples\assets\kraftwerk_robot_3_ru.wav `
  -ReferenceText 'Я твой слуга, я твой работник' `
  -TestText 'Я твой робот. Я твой работник.'
```

Pass `-Save` to skip the final confirmation. The default output is the ignored
`config/voice-profiles.local.json`. You can also begin from the checked-in
example:

```powershell
Copy-Item config\voice-profiles.example.json config\voice-profiles.local.json
```

The launcher defaults to the locally configured FasterQwen source for this Base
model. The tested cold request prepares the profile and CUDA graphs; once it
starts emitting, the measured chunks arrive faster than playback. Pass
`-RuntimeBackend upstream` for a diagnostic comparison, not for real-time
playback. Pass `-ModelPath` to select another local snapshot or Hugging Face
model ID.

## Use a Saved Profile

Select a registered voice when starting the Base-model playback example:

```powershell
.\scripts\start-qwen-tts-clone-play.ps1 `
  -VoiceRegistryPath .\config\voice-profiles.local.json `
  -VoiceId kraftwerk_robot_ru `
  -Interactive
```

In the interactive CLI, use `/voices` to list the profile IDs advertised by the
worker and `/voice kraftwerk_robot_ru` to select one for future requests. A
new line of spoken text cancels the prior generation as usual.

The normal clone launcher keeps request-level sampling controls sealed for a
repeatable default. Start it with `-StyleExperiment` when comparing sampling
or style interactively; only that explicit mode enables `/temperature`,
`/seed`, `/top-k`, `/top-p`, `/repetition-penalty`, and `/sample` for future
requests. Do not use those ad hoc settings as performance evidence.

Registry JSON is durable metadata, not a serialized GPU prompt. In a running
worker, the selected profile is converted into a Base-model voice prompt once
and retained in a bounded LRU cache. Restarting the worker re-creates that
in-memory prompt on the first use, but it does not require reauthoring or
re-entering the profile.

The preflight accepts local uncompressed PCM WAV files only: mono or stereo,
8--96 kHz, 8/16/24/32-bit, 2--20 seconds, non-silent, and at most 16 MiB. ICL
profiles require an accurate transcript; `-XVectorOnly` is an explicit fallback
that omits it.

The repository's example asset is user-provided, restored, and processed; the
owner confirmed permission to publish it. Its provenance and SHA-256 are in
[`examples/assets/README.md`](../examples/assets/README.md). Generated audio
is still synthesized. Use only references you are permitted to process, label
generated output as synthesized, and do not use any profile to impersonate a
real person.

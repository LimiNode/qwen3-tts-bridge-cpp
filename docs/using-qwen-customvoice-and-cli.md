# Using CustomVoice and the Playback CLI

This guide covers the currently validated local path:
`Qwen3-TTS-12Hz-0.6B-CustomVoice` with the Windows `qwen_tts_play` example.
It is a practical usage guide, not a claim that every Qwen3-TTS model has the
same capabilities.

For a Russian translation, see
[using-qwen-customvoice-and-cli-ru.md](using-qwen-customvoice-and-cli-ru.md).

## Start the Interactive CLI

Build `qwen_tts_play` once, then create the ignored local configuration from
the checked-in example:

```powershell
Copy-Item config\playback-runtime.local.example.json config\playback-runtime.local.json
# Set python, faster_qwen_source_path, and model_path in the local file.
.\scripts\start-qwen-tts-play.ps1
```

The local file contains machine-specific paths and is ignored by Git. The
launcher uses the pinned internal RTX 4090 R10 profile and its runtime
preflight. Initial model load, compiled allowlist warmup, and generation prime
take roughly a minute on the validated machine. Once the prompt `>` appears,
enter spoken text on a line.

For a one-shot smoke test instead of an interactive session:

```powershell
.\scripts\start-qwen-tts-play.ps1 -Text "Hello" -Speaker serena -Language English
```

`-Speaker`, `-Language`, `-Instruction`, `-Temperature`, `-TopK`, `-TopP`,
`-RepetitionPenalty`, `-Seed`, and `-NoSample` override the saved values for
one launcher invocation. The five-minute startup timeout is intentional: the R10
profile prewarms six exact compiled shapes before declaring the worker ready.

## Interactive Commands

| Input | Effect |
| --- | --- |
| Plain text | Cancels an active synthesis and queued playback, then speaks the new text. |
| `/cancel` | Cancels the active synthesis and stops queued playback. |
| `/voice <name>` | Selects a preset speaker for future requests. |
| `/language <name>` | Selects the request language for future requests. |
| `/style <text>` | Stores a style instruction for future requests; see the model limitation below. |
| `/temperature <value\|default>` | Sets sampling temperature for future requests, or restores the worker profile default. |
| `/top-k <value\|default>` | Limits each sampling step to the most likely candidates, or restores the worker default. |
| `/top-p <value\|default>` | Sets nucleus sampling probability, or restores the worker default. |
| `/repetition-penalty <value\|default>` | Discourages repeating generated acoustic tokens, or restores the worker default. |
| `/sample <on\|off\|default>` | Enables sampling, requests greedy decoding, or restores the worker default. |
| `/seed <value\|off>` | Uses a deterministic request seed, or returns to the worker seed policy. |
| `/sampling` | Prints the effective CLI overrides; `<worker default>` means the profile controls that value. |
| `/help` | Shows the command reference. |
| `/quit` | Stops the worker and exits. |

Changing `/voice` does not recolor audio that is already generated. To switch
immediately, set the voice and submit a new line of text; that new request
cancels the old generation. `serena` and `ryan` are known preset speakers for
the local model. An unsupported speaker is rejected by the worker.

## Sampling and Stable Pronunciation

The experimental CustomVoice profile starts with `temperature = 0.4`,
`top_k = 50`, `top_p = 1.0`, `repetition_penalty = 1.05`, and sampling enabled.
This is deliberately more conservative than FasterQwen's upstream temperature
of `0.9`: it normally reduces phrase-to-phrase variation while retaining some
prosody. It does not add phoneme or stress control.
Request-level sampling commands are enabled only by `-StyleExperiment`; the
sealed R10 profile rejects them so its measured operating contract cannot drift.

Use a fixed seed before comparing a style, spelling hint, or pronunciation:

```text
/seed 4242
/temperature 0.4
/sample on
```

`/sample off` uses greedy decoding. It is the strongest repeatability check,
but may sound flatter and can weaken a style instruction. `top_k` narrows the
candidate set; lower values are more conservative. `top_p` retains only the
most probable cumulative mass; lowering it also reduces variation. Increasing
the repetition penalty discourages repeated acoustic tokens, but an excessive
value can make articulation less natural. Change one control at a time and
listen to the complete phrase rather than judging a single word.

## Russian Pronunciation

The CLI sends console input as UTF-8, so Russian text, `ё`, and normal
punctuation are supported. The model's pronunciation is still probabilistic;
it does not expose a phoneme or stress-mark API.

Use context first. A phrase such as `дверной замок` gives the model a better
signal than an isolated ambiguous word.

Do not rely on a combining acute accent after a vowel, such as `за́мок` or
`замо́к`. In local testing the 0.6B CustomVoice model sometimes pronounced the
combining mark as part of the word and produced artifacts instead of a stress
cue.

For individual troublesome words, deliberately respelling a vowel can be a
useful manual workaround:

```text
всее
замоок
```

Treat this as an auditioned per-phrase hint, not a language-wide replacement:
it can make a vowel too long and should never be applied automatically to every
word. `е` and `ё` can likewise be selected intentionally when the desired word
requires it. A future application-level pronunciation dictionary may map only
known problematic words to approved replacements.

## Current 0.6B CustomVoice Limitations

- It is a preset-speaker model. It does not yet provide voice cloning through
  this bridge's public workflow.
- The sealed R10 runtime advertises style instructions as unsupported for 0.6B
  CustomVoice. A request with `/style` fails clearly instead of being accepted
  and silently ignored. Do not depend on style control in that runtime profile.
- `-StyleExperiment` deliberately uses an eager profile and a separate local
  FasterQwen source tree. It never changes or reuses the sealed R10 allowlist.
  Configure `style_experiment_faster_qwen_source_path` and start it with:

  ```powershell
  .\scripts\start-qwen-tts-play.ps1 -StyleExperiment
  ```

  This experiment is only for assessing instruction control. Compare the same
  text, speaker, language, seed, and sampling controls first without `/style`,
  then with it. It completes one short instructed synthesis before
  `worker_ready`, so startup is longer but the first phrase you enter is not
  responsible for CUDA graph capture or the first instruction-path execution.
  The resulting audio still requires listening review; passing a prompt through
  is not proof of a useful emotional change.

  The reproducible non-playback A/B probe records those transport-level facts:

  ```powershell
  $env:PYTHONPATH = "C:\path\to\faster-qwen3-tts-style-experiment;worker\src"
  .\.venv-faster-qwen\Scripts\python.exe scripts\qwen_customvoice_style_ab.py `
    --model models\Qwen3-TTS-12Hz-0.6B-CustomVoice `
    --text "This is a controlled style test." `
    --instruction "Speak with controlled urgency." `
    --output tmp\customvoice-style-ab.json
  ```
- There is no supported word-level phoneme, IPA, SSML, or stress-mark control.
- The sealed RTX 4090 R10 profile is an internal opt-in performance profile,
  not a universal default for other GPUs or model families. Text lengths outside
  its exact compiled allowlist correctly run through eager fallback.
- `flash-attn` and SoX warnings seen during this CustomVoice path are currently
  non-blocking. The validated profile uses PyTorch SDPA; playback consumes
  streamed 24 kHz PCM directly and does not require a standalone SoX binary.

## Diagnostics

The current playback example forwards worker stderr, so lines beginning with
`qtb_metric` are diagnostic telemetry, not text or audio data. They include
queue time, first-audio timing, selected compiled/eager route, and memory
information. A request marked `eager_unknown` simply used a length outside the
six prewarmed R10 shapes; it is a safe fallback, not a request failure.

The worker reports `completed request <id>` after a successful request. Real
errors use an error category and message instead.

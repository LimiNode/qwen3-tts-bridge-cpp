# Explicit-stress model priorities and additional experiments

- Date:2026-11-24. Active research plan; no model/default promotion.
- User amendment: explicit Russian stress, full ICL cloning, complete speech
  and continuous streaming are required together. RU-stress remains primary;
  Base is a control, not an escape from the stress requirement.
- R1 remains **NO-GO**. Warm usable-speech onset200–250ms on CMP and RTF<1
  are engineering targets, not measured release guarantees.

## Confirmed listening and the reference-cost mechanism

The user listened to the exact13-file reference-conditioning selection.
RU-stress04-07 correctly say `Ладно.` with acceptable voice preservation;
06/07 sound more alike and04/05 vary more in timbre. Base08-12 has good full
speech and acceptable voice;11/12 sound slightly higher than09/10.03 has no
voice and remains the failed original-A control. Separate canonical run002
receipts now record scoped `partial_pass`; remaining cases/stress/tails and
release gates are not inferred. No audio or sealed inventory was rewritten.

Yes: the measured latency difference is primarily consistent with shortening
the **reference speech/transcript**, not the requested output phrase or removal
of cloning. Reference codec frames226->56 reduce initial prompt rows236->66;
warm prefill153->60ms accounts for about93ms of the observed95ms first-PCM
change178->83ms. Short B retains the original17.6s speaker vector and full
ICL/decoder context from the crop. No kernel/prefix cache changed and the
rounded KV window remains256. Medium116 frames/126 rows gives about110ms
first PCM. Those initial A values were historical, not interleaved. The later
[native comparison](native-stress-model-comparison-20261124.md) repeats both
arms in balanced ABBA fresh-process blocks and reproduces approximately179→83ms
first PCM and153→60ms prefill. It is not same-session reference switching:
the retained probe fixes conditioning per process. First callback is not
first audible or intelligible speech.

Subsequent listening to that comparison selection is mixed: RU-stress short
05-07 initially sounded normal but 08 changes voice after the middle; CF short
13-16 and Base 17-24 initially sounded normal. Original-reference RU-stress
01-03 and CF 09-10 fail speech, and CF 12 has an abrupt ending. These new
observations are attached to their exact separate receipts; short full ICL
is not a general voice-stability fix. The subsequent stress clarification
confirms requested О stress in CF 11/15. The user revised RU-stress 07 after
re-listening on 2026-11-25: the stress is uncertain and may be on О, so the
earlier stress-failure classification is withdrawn to not_assessed.
Base 19/23 distort the target word as
«доикументы»; stress on И is tentative, not confirmed. Base's current scoped
listening is therefore fail for that pronunciation artifact, refining the
earlier partial_pass. CF's positive stress result is limited to one word and
seed 64 under the two references, not whole-corpus or voice/release acceptance.
The deliberately nonstandard target is до́кументы; remaining stress cases
stay unassessed.

The 2026-11-25 follow-up makes a paired listening selection from existing
short-full-ICL RU-stress/CF outputs: за́мок/замо́к at seeds 64/2027 and
му́ка/мука́, докуме́нты/до́кументы, проце́ссор/процессо́р at seed 64.
All20 generated files are retained without outcome filtering and now have
user feedback. Zamok/muka/processor contrasts are heard as requested in both
models. Only paired CF16 clearly has О in до́кументы; paired RU14 remains not
clearly confirmed, not a definitive wrong-vowel failure. Paired RU06 truncates
final К and RU17 has a reported «инжинЁр» vowel distortion, independently of
correct processor stress. The RU selection receipt is fail; CF is scoped
partial_pass, aggregate not_assessed. This adds nine distinct heard outputs
per model to the eight first-pass outputs (17 heard /27 unassessed primary
outputs each), without new GPU work or full model/voice acceptance. The user's
training-annotation hypothesis is unverified; no training frequency or
annotation statistics were checked. Earlier source comparison failures remain.

## RU-Stress-CF: preparation actually performed

Pinned primary source:
[siriusfreak/qwen3-tts-12hz-1.7b-ru-stress-cf](https://huggingface.co/siriusfreak/qwen3-tts-12hz-1.7b-ru-stress-cf/tree/c16b3af3db3095120efc1ebb73f6522442bcb3b1),
revision `c16b3af3db3095120efc1ebb73f6522442bcb3b1`.
The card declares U+0301, reference-audio-plus-transcript ICL and Apache2.0.
Its claimed96% counter-dictionary stress versus77%/17% is an author meter2
evaluation on130 sentences, not our independent human result or EOS evidence.
The card explicitly warns about missing license declarations for some
training/reference texts and noncommercial provenance of meter2 renders.
Keep those as release/provenance questions; the card's Apache tag alone is
not a complete commercial-use review. No meter2 code/model was executed.

Downloaded only the34908456-byte adapter and small pinned metadata/cards:
adapter SHA256
`88a94c0fbe85800d309f94bb9c28d698bf9c86d9494617b6cf4dd996cc13648b`.
The existing exact Base checkpoint SHA256 is
`38fc7fc51c5e776e840414b6fd443962e9411b9654888fd7913e4da643cb857c`,
matching the adapter's Base revision
`fd4b254389122332181a7c3db7f27e918eec64e3`. All196 LoRA A/B pairs (392 tensors),
rank16/alpha32, map to existing `talker.model` weights with correct dimensions.
This collection pass established **provenance/shape compatibility only**;
it performed no merge, model inference, GGUF conversion or audio generation.
The separate subsequently executed CPU source control is recorded below.

The existing trusted merge script already accepts an explicitly pinned new
adapter hash and verifies target/provenance. Reuse it, then the unchanged
converter and quantizer; do not patch production weights or weaken guards.
Do not execute downloaded training scripts or `trust_remote_code`.
The native converter emits F32: preparation needs approximately3.86GB for
the merged checkpoint,7.72GB F32 GGUF and2.08GB Q8 plus reserve/results.
The initial2.29GB storage refusal is preserved as history. After separately
authorized cleanup of verified duplicates and compiler intermediates, the
[native comparison](native-stress-model-comparison-20261124.md) completed
CPU-only merge/conversion/quantization and independent tensor checks. The
new CF Q8 hash is `de5ab0b516de7f6f6d04e9375e3a59a7b4e4ff714c5a898f89269588d2223596`.
Unique historical WAVs, logs, models and provenance were retained. These
preparation checks alone do not establish speech or prescribed-stress quality.

Local CPU/network preparation payload:
`.tmp/base-acceptance/model-candidates-20261124/run-001/`.
`results.json`:56445 bytes, SHA256
`1d25ad2926d60579a1d6d898e3e47f2f00005574746181f0533f77110ffba055`.
Inventory:3971 bytes, SHA256
`ca67fd93085961382c5c461691df8c27b71021bde06c8f4649d0721270cd844c`.
It preserves pinned metadata, model cards, adapter and exact tensor-shape
checks. This is not a hardware acceptance receipt. No GPU was used.

## Executed Base/CF CPU source control

A separate bounded source-only control completed in306.5s, exit0, with no
deadline/storage stop or GPU use. It reuses the four fixed texts, seeds,
original226-frame full ICL codes and speaker input from
[native/source run002](native-source-causal-20261124.md). It is not the frozen
132-attempt native model/stress comparison below.

The existing installed Torch2.8.0+cpu/Transformers4.57.3/safetensors0.8.0
environment ran CPU FP32 with8 threads and eager attention verified on actual
nested attention configurations. Base ran first; the exact downloaded CF
adapter was then applied in memory to196 targets using the trusted merger's
`(Base_BF16.float() + 2 * (B.float() @ A.float())).to(BF16).float()` arithmetic.
All target tensors equal those merged values and have recorded hashes.
No merged checkpoint or GGUF file was written. Published merged-checkpoint
byte parity is not established; this is the pinned **CF-adapter source arm**.
The processor, ICL, default stochastic Talker/Predictor sampler, seeds and
128-frame maximum stayed the same, with no retry, penalty or speaker fallback.

| Fixed original-full-ICL case | Prior RU-stress source frames / first EOS | Base source frames / first EOS | CF-adapter source frames / first EOS |
| --- | ---: | ---: | ---: |
| `Ладно.` /2027 |2 /2 |9 /9 |2 /2 |
| `All right.` /2029 |11 /11 |10 /10 |2 /2 |
| Long Russian /2027 |86 /86 |92 /92 |82 /82 |
| Long English /2027 |85 /85 |84 /84 |92 /92 |

The previous RU source column is retained evidence, not a fresh concurrent
arm. No displayed free trajectory was decoded/listened to. Frame counts are
not a word-coverage, prescribed-stress or voice-quality score. CF does **not**
remove the early two-frame EOS in these two source controls. At decision2,
CF's allowed-vocabulary temperature1/no-penalty EOS probabilities are94.14%
and81.13%, both raw rank1, versus Base1.14e-8 and6.71e-8. These diagnostic
probabilities are not the final sampler-chain probabilities or proof of why
the fine-tuning/reference combination produces that preference.

Payload: `.tmp/base-acceptance/model-candidates-20261124/source-run-001/`.
Runner `run_cf_source.py` SHA256
`b4f3d8bc83c97fb26b2bfb820a8d8d197e4d4375882b94976cb013a7e62fc48b`.
`results.json`:687737 bytes, SHA256
`b8d22e6595bf6d884cb55535b58a7b9c5beb599490f9c52aff0b8dee15348061`.
Inventory:16942 bytes, SHA256
`8723b4991ba3fd5dd260e5a2415239e4cac023c6e50e64e224801a071ce07a86`;
77 entries/1991906 payload bytes, including all saved codes/traces, first8
raw distributions per case (only3 when EOS occurs at2), merge target hashes,
attention settings and execution log. The runner enforces a600s absolute
CPU watchdog,512MiB reserve and50MiB output cap, retaining failures.

The runner's own before/after identities cover Base weights/configuration,
adapter, helper/runner and previous plan/results, not every installed-source
or tokenizer file. Independent postflight confirms the three installed Qwen
source files and package versions match the previous frozen plan, and Base/
merged3 tokenizer metadata are identical. Do not describe that postflight as
a complete independent before/after freeze by this new runner. No dedicated
new model-free runner test suite was run; the reused source helper has its
previous10 passing contract tests and the new script/merge/inventory received
independent read-only review. Native CF, audio, stress, latency and broader
reliability are not qualified by this control. Subsequent native execution is
recorded separately in the [native comparison](native-stress-model-comparison-20261124.md);
it does not retroactively decode or qualify these CPU-source trajectories.

## Other candidates: primary-source checks, not inference results

All model cards below were retrieved at the exact revisions recorded in the
local metadata receipt. That card-collection pass loaded no additional model
weights/packages/backends; the separate Base/CF source run above is distinct.

| Candidate / pinned revision | Confirmed card declaration | Boundary / next disposition |
| --- | --- | --- |
| MOSS-TTS Local Transformer1.5 / `be7766a6735b98bd793f7c79fb720b4d0f5d13b8` | Apache2.0, Russian, zero-shot cloning, Pinyin/IPA; SGLang-Omni streaming interface |4.5504B BF16 parameters (~9.1GB weights alone), custom architecture/audio path, not a drop-in qwentts model; Russian IPA/stream continuity not tested |
| ESpeech-TTS-1 RL-V2 / `f582b6e5897fe8a5835059405a8439d13bdf7684` | Apache2.0; `+` stress and F5-style reference audio/text inference | Useful independent pronunciation control; not evidence of Qwen-like incremental within-sentence streaming |
| F5-TTS Russian / `ea166adeae4c80ec5ee423a671e2bdb83906cf84` | `+` stress; CC-BY-NC4.0 | Research-only licensing boundary; different inference/streaming architecture |
| Pocket-TTS RU / `ded503687f13fb3761c14e856a3295a032bbbe04` |109.5M parameters, CPU cloning, `+` stress; CC-BY-NC4.0 | Card warns of50-token chunk truncation and10–20s reference needs; no timing/quality claim on our machine |
| Dialogs RU VITS2 / `af7eabc15d087fce701de7261190ccb747c3bc7a` | `+` stress,3 preset voices, OpenRAIL | Does not satisfy arbitrary-reference ICL cloning; pronunciation control only, license restrictions need review |
| Silero V5 CIS Base / source `e382298387332f2bf461fe6eadfde99104611b0c` | `+` stress and preset voices; CIS Base section specifically MIT | Distinguish `LICENSE_CIS` from repository-wide CC-BY-NC; no arbitrary-reference ICL acceptance |

Primary repositories:
[MOSS](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5),
[ESpeech](https://huggingface.co/ESpeech/ESpeech-TTS-1_RL-V2),
[F5 Russian](https://huggingface.co/Misha24-10/F5-TTS_RUSSIAN),
[Pocket RU](https://huggingface.co/amekhrishvili/pocket-tts-ru),
[Dialogs](https://huggingface.co/frappuccino/dialogs-ru-vits2),
[Silero pinned source](https://github.com/snakers4/silero-models/blob/e382298387332f2bf461fe6eadfde99104611b0c/README.md).
MOSS deployment examples pin Torch/Torchaudio2.9.1+cu128 and use a different
audio decoder/runtime. No new dependencies or network service are introduced
into Bridge. It remains a separate future-backend feasibility study, including
SM75/memory support and Russian IPA listening. Mapping a future pronunciation
representation to U+0301/`+`/IPA is a design possibility, not a new frontend API.

## Frozen comparison and subsequent EOS work

The [exact UTF-8 corpus](native-stress-model-comparison-corpus-20261124.json)
has16 texts/22 text-seed cases: known RU/EN short failures, original seeds72/75/78,
homographs, counter-dictionary marks, technical vocabulary and long voice
controls. Compare current RU-stress, CF and Base at the same Q8 quantization,
engine, codec, sampler, chunk schedule and original/short full ICL with the
same original speaker vector:132 synthesis attempts before separate timing
repetitions. The corpus was frozen before conversion/storage gates passed;
execution now has its separate [report](native-stress-model-comparison-20261124.md).
No after-the-fact seed selection. Freeze corpus/model/runtime manifests before GPU use;
one bounded CMP-only window, preserved failures and exact listening identities.

Measure code/terminal outcomes, missing/extra speech, prescribed stress and
voice stability separately. Observer-OFF warm first callback/prefill/RTF and
first-use costs must be separate from diagnostic logits. First **usable**
speech needs listening/independent alignment; energy/VAD alone is not proof.
Add balanced original/short timing order rather than relying solely on A's
historical medians. Never compare model changes and new EOS policy as one arm.

After that unchanged-sampler baseline, the next separate research candidate
is controlled EOS logit subtraction/alternative continuation without prefill.
Preserve a zero-penalty control; record the exact pre-temperature application
stage and all raw/suppressed/post-chain probabilities. Calibrate any adaptive
text/frame/code-conditioned schedule separately from held-out assessment.
Keep fixed seed/RNG consumption and distinguish resampling from changing the
generated prefix. A reduced EOS probability is not successful speech: retain
repeats, nonsense, coughs, omissions and resource-limit failures. No universal
minimum-duration guard, always-on penalty or selector is enabled by this plan.

Existing rollback/branching remains frozen as a retained option, not discarded
or integrated. Cheap continuation must be measured against full retry and
unchanged immediate streaming, including snapshot cost, false intervention on
legitimate short words, irreversible PCM commit, shared deadline and bounded
holdback. Larger-buffer recovery, new fine-tuning and MOSS integration are not
implemented by this evidence-only change.

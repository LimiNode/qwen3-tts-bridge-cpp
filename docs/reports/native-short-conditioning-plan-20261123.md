# Short-input checkpoint and conditioning controls

Prespecified 2026-11-23 after the user rejected both exact short files in
the [matched-decoder reset study](native-eos-short-reset-20261123.md).
Research only. R1 remains NO-GO; no production source, defaults, pin, model,
or release-package change. No seed search, EOS suppression or text change.

## Fixed comparison

Use seed64, exact `Нет.` / russian and `Hi!` / english, the same Kraftwerk
speaker vector, and the same buffered decoder as the completed reset study.
Cross RU-stress/Base Q8_0 with full226-frame Kraftwerk ICL versus speaker-only.
The completed RU-stress/full-ICL cell is reused by its frozen code/PCM hashes
and failed user listening; do not regenerate it or transfer its verdict.

Three new cells, each with five logical groups:

| Checkpoint | Conditioning | New short groups | Long control |
| --- | --- | ---: | ---: |
| RU-stress | speaker-only | Two texts, two repeats each | Original MGU phrase64 once |
| Base | full ICL | Two texts, two repeats each | Original MGU phrase64 once |
| Base | speaker-only | Two texts, two repeats each | Original MGU phrase64 once |

Intended total:15 groups /15 independent AR attempts. Each uses the existing
buffered full-retry probe path with threshold1 and continuation64 purely to
capture complete codes without changing the engine. Require NOT-triggered,
one attempt/prefill and zero snapshot/restore; unexpected fallback invalidates
that cell and is retained/countable, not a rescue. A failed gate stops later
cells. All attempts share one1800-second wall bound established before identity
preflight; each logical operation has one60-second deadline, cap256frames.
Only CMP50HX UUID `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb` is in scope.

Reuse clean engine `4e47ed266f08cab9e13e277aa460a33bb607e769` and static probe
SHA256 `8bd699d6f12d31198e004ed82ef67a4d6aa515c6a361a52353e203d682abef5f`.
RU-stress model SHA256
`f4672741608d145fae169075cb0ec775a5382cbe9183eccb59c7ab9cc4797427`;
Base SHA256 `4b9a33a236908dd9435a42f7a396e38038329d053b704342a6413c08544c4fda`;
codec SHA256 `1883beeed99348fc35e23dd225e9082f93f6f8c109330a33d935baa8acdbfd94`.
Full ICL receives unchanged reference codes/transcript; speaker-only omits
those parameters but retains the same speaker vector. This intentionally
changes both conditioning and decoder-reference availability, not a pure
single-transformer ablation. Record the effective mode explicitly. Do not
claim any difference is localized to a specific model layer or kernel.

## Checks and decision

Record exact manifest paths/input hashes, actual loaded-model selection,
hardware/software, seeds,16-code histories, naturalEOS, all PCM/WAVs and
failures. Before/after hashes cover all selected models, codec, conditioning,
probe and runtime. Require byte-exact short repeats within each cell, no
unexpected fallback, finite correctly sized PCM and unchanged identities.
The three long same-mode controls check whether failure is restricted to short
input; their linguistic quality still needs listening. A low-signal long
control or any failed mechanical/repeat gate blocks causal interpretation.

Label near-silent results before handoff. Preserve every failure; no trimming,
normalization, duration-selected successes or automatic hearing claims.
Select only unique short outcomes plus the long controls, with at most9 new
WAVs for initial listening; retain repeats and rejected outputs separately.
Keep Base and RU-stress listening/receipts separate. New listening is not_run.

Improvement only in a particular cell is evidence of a dependency under this
fixed seed/text/checkpoint/conditioning setup, not proof of the root cause or
a universal remedy. If all cells fail, stop this matrix instead of extending
seeds or suppressing EOS; matched upstream/native forward and prompt/codec
checks are then possible separate investigations. No CustomVoice top1 claim,
native-arithmetic parity, streaming speedup or release qualification follows.

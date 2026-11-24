# Matched-history native/source comparison: run002 freeze

- Status: frozen before execution; new user-authorized bounded batch.
- Date: 2026-11-24.
- Previous prepared run001 is preserved without execution or modification.
- Scientific question, four fixed texts/seeds, unchanged full ICL and model
  identities: [original plan](native-source-causal-plan-20261124.md).

## Run002 corrections and boundaries

Use a new exclusive payload directory:
`.tmp/base-acceptance/native-source-causal-cmp50hx-20261124/run-002/`.
The versioned local runner/test are `run_source_causal_v2.py` and
`test_source_causal_v2.py`, under
`.tmp/pr-metadata/native-source-causal-20261124/`. Original v1 tools remain
unchanged, preserving their recorded run001 hashes.

The coordinator owns GPU execution and the single new <=1800s batch clock,
started immediately before the first GPU call across reference/source work.
Every execution invocation requires that same absolute
`--deadline-monotonic`; the native/source supervisor refuses before spawn if
expired and kills/reaps only its own child at expiry. Its native300s and
CPU-source600s watchdogs can shorten, never extend, the shared deadline.
The agent does not launch GPU itself. Do not run heavy CPU source inference
during reference timing measurements; the coordinator signals when to start.

The frozen identity set now includes all four corpus text files and the exact
test file, along with source/model/helper/probe/runtime/conditioning inputs.
Numerical equality is labelled `elementwise_equal`, not byte equality of
values that were converted to another dtype.

Before any source forward, explicitly align the nested top-level Talker and
CodePredictor configurations **and each actual attention module config** to
the planned eager path. Record the inherited values, actual aligned values
and final values after execution; reject any non-eager value. The installed
source selects its attention function dynamically from those module configs.
The old top-level `from_pretrained(attn_implementation='eager')` argument alone
was not adequate evidence of the nested path. This is research-only alignment,
not a production or installed-package change.

The fixed execution remains four native cap8frame dumps, matched source
histories with all16 codes, exact-native-embedding source forwards and four
bounded free source trajectories. Keep raw logits distinct from filtered
sampler quantities. Retain failures and no semantic success claim from code
counts/durations. No new seed selection, recovery or full-text geometry work.
Native Q8/source FP32 remains a quantization/checkpoint comparison, not
equal-weight arithmetic parity or proof of a native/conversion defect.

Ten model-free tests cover case identities, numerical labels, frozen text/test
paths, missing/invalid deadline rejection, refusal before spawn, kill/reap
under an expiring absolute deadline, nested/module attention alignment and
the lack of a speech/release verdict. No model/GPU run is implied by them.
Reserve512MiB disk; native/source payload caps400/200MiB. Root owns shared
status/index integration. Production pin/defaults, ABI, QTB and frozen package
remain unchanged; R1 stays NO-GO.

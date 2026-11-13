# ADR: R1 dual-backend acceptance and native-first evaluation

Status: accepted direction; backend promotion is pending the R1 acceptance
gates.

## Context

QwenTTSBridge has two local inference routes behind the same C++ bridge
contract: the persistent Python/Faster worker and the native qwentts.cpp/GGUF
worker. The native route has promising warm latency and reduced Python
dependencies, while Python already covers model families and runtime profiles
that native does not. A Python-only release baseline would make the native
measurements secondary before the required hardware and package checks exist.

## Decision

R1 uses two equally rigorous acceptance tracks:

1. native qwentts.cpp/GGUF, prioritised for local Base 1.7B Q8_0 evaluation;
2. Python/Faster/PyTorch, retained as a maintained alternative and reference.

Native is not automatically supported or made the default. Promotion requires
the frozen bridge/runtime/model manifests, dual-GPU mechanical and listening
receipts, clean-package checks, lifecycle/cancellation/restart evidence, and a
backend-selection record. Native process-worker and in-process `qwen.dll`
adapter acceptance are separate gates. Native gaps for CustomVoice or
VoiceDesign do not invalidate Python acceptance for those families.

The Python user CLI remains the current installed command contract. The
future C++17 user CLI, speech.cpp optimisation research, and expressive-speech
composition remain R2 work and are not introduced by this decision.

## Required decision record

After the CMP 50HX and RTX 4090 campaign, record correctness and natural EOS,
RU/EN listening quality and voice identity, first PCM/playback latency, RTF and
chunk continuity, resource usage, cancellation/restart stability, packaging
complexity, supported model families, and maintenance risk. A failed optional
native family stays an explicit failure or unsupported result; it is never
silently replaced by Python in the same receipt.

## Consequences

Acceptance receipts must name the backend and surface under test. Historical
native CMP measurements remain useful evidence but do not transfer to RTX or
to the in-process adapter. Release documentation can select native for Base,
Python for unsupported families, or both, but must state the exact scope and
never imply universal backend equivalence.

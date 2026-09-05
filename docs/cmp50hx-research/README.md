# CMP 50HX research archive

This directory is the durable index for the CMP 50HX investigations that were
developed in stacked pull requests #44 through #60. Pull-request descriptions
are supporting history, not the canonical record. The detailed reports linked
from this index contain the full commands, run identifiers, measurements, and
quality limits.

## Environment and evidence rules

The measurements targeted a CMP 50HX with 20 GiB VRAM on Windows/WDDM. Unless
a row explicitly says otherwise, the experiments used the persistent Python
worker, the 1.7B Qwen model family, and the FasterQwen streaming path available
on the experiment branch. Exact source revisions changed as candidates were
promoted; each thematic report records the applicable commit.

Timing evidence was accepted only from successful, finite, natural-EOS runs.
ETW evidence additionally required a non-empty ETL, zero reported event loss,
the expected WPR markers, scheduler data, and unambiguous player/worker
attribution. PCM capture and generation tracing were correctness tools and were
never treated as performance measurements.

`queue-starvation proxy` means the WaveOut queue was empty immediately before a
later PCM chunk was submitted. It is not a hardware-underrun counter.

## Experiment registry

| Experiment | PR | Hypothesis | Key result | Decision |
| --- | ---: | --- | --- | --- |
| ETW playback markers | #44 | Put playback observations and WDDM events on one clock | Marker writes and PerfInfo records can be validated fail-closed | **ADOPTED** diagnostic infrastructure |
| Marker-aware ETW analysis | #45, #47 | Attribute bounded marker windows to the TTS worker and competitors | Attribution works; individual 1.1 s windows made the 754 MB ETL tractable | **ADOPTED** diagnostic infrastructure |
| Selected-profile warmup and chunk size | #46 | Move graph capture out of the request and improve reserve | Warmup improved first audio; E8/E16/E32 still showed 6/3/1 proxy events and E32 RTF 1.301 | **PARTIALLY ADOPTED** warmup; chunk sizing not sufficient |
| TF32 policy | #48 | Speed the remaining FP32 GEMM | One matched pair improved synthesis 4.64%, but RTF remained 1.426 with three proxy events | **REJECTED** as runtime policy |
| Client CPU priority | #49 | Scheduler priority causes stalls | Normal/AboveNormal RTF 1.386605/1.386561; worker priority was not proven | **INCONCLUSIVE** |
| GPU lifecycle ETW | #50 | Derive worker GPU execution durations | Existing ETL had activity but zero pairable worker DmaPacket Start/Stop events | **INCONCLUSIVE** method on this WDDM capture |
| Full-EOS codec warmup | #51 | Warm every dynamic terminal codec path | Initial 0/3 proxy result did not repeat; extended and prompt-matched runs reproduced terminal residual near 874-879 ms | **REJECTED** as sufficient fix |
| Playback prebuffer | #52 | Reserve can absorb terminal codec bursts | Two-chunk runs started near 2.72 s and produced 0/3 proxy events | **ADOPTED** infrastructure, not default fast-start policy |
| Left-padded streaming codec | #53 | Fixed input shape reduces codec cost | Same codec tokens, changed every PCM chunk and added 444 first-chunk samples | **REJECTED** correctness |
| Right-padded codec and PCM gate | #54 | Causal zero right-padding preserves the valid prefix | 63 codec frames matched; RMS 2.845, SNR 55.458 dB, max s16 delta 52; about 16.5% synthesis gain in first pair | **ADOPTED** after later consolidation |
| Compiled codec decoder | #55 | `torch.compile` removes launch overhead | Candidate failed the PCM quality gate | **REJECTED** |
| Manual codec CUDA Graph | #56 | Capture the fixed codec graph without Inductor | Exact PCM in the tested pair; repeated 4.09-5.04% synthesis gain; 10/10 bounded soak | **ADOPTED** after later consolidation |
| Smaller W48 codec graph | #57 | Remove unused fixed-window work | 10.78-12.33% synthesis reduction vs W80; quality gate passed; 10/10 soak | **SUPERSEDED** by smaller production windows/profiles |
| Versioned FasterQwen source | #58 | Replace local shadows with a reproducible dependency | Pinned Faster commit and fail-closed input contract worked | **ADOPTED**, revision later superseded |
| Python-to-GGML adapter | #59 | Prove qwentts.cpp can satisfy Bridge requests | Explicit-language CustomVoice smoke produced native output | **ADOPTED AS PROOF**, not production architecture |
| Cross-backend timing harness | #60 | Compare engines only under an identical contract | Matching contract passed; mismatched text and incomplete playback failed closed | **ADOPT CONTRACT**; implementation to be restacked |

Production consolidation occurred in #63. Selectable profiles, routing, and
the final operational soak were merged through #64, #65, and #66. Those PRs,
not the historical experiment branches, define current runtime policy.

## Thematic reports

- [Playback and ETW](playback-and-etw.md)
- [Codec decoder experiments](codec-decoder.md)
- [Startup and prefill](startup-and-prefill.md)
- [Faster runtime optimization](faster-runtime.md)
- [Native GGML proof and comparison contract](native-ggml.md)
- [Native engine boundary ADR](../architecture/adr-native-engine-boundaries.md)

The final production measurements are in
[CMP 50HX profile acceptance](../cmp50hx-profile-acceptance.md). The complete
historical narrative remains in
[CMP 50HX playback investigation](../cmp50hx-playback-investigation.md).

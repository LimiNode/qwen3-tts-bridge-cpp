# CMP 50HX Kraftwerk warm long-horizon matrix (2026-09-28)

This rerun supersedes `cmp50hx-long-horizon-eos-matrix-2026-09-27`. The old
run used mismatched ICL conditioning: a Latin-transliterated reference text for
a Russian reference WAV. This run uses the registered
`kraftwerk_robot_ru_warm` profile with its matching Cyrillic reference text.

## Provenance

- Bridge worker source: `202e64c82725198a36a165aac0772109d458ca7c`
- qwentts.cpp: `130cb99af9ae12d554962fd0920e08fb4268af01`
- GGML: `c044c6f03892f9d5e98213b05f8afea1f8b0d3c9`
- runtime: CUDA graphs ON, `sm_75`, Q8 talker and tokenizer
- GPU: NVIDIA CMP 50HX, driver 581.94
- voice: `kraftwerk_robot_ru_warm`
- reference WAV SHA-256:
  `B8285C5925D89D90435AFA2F084A197A9E428DEC41FFF09C74969E6624A4B147`
- local registry SHA-256:
  `1655686047130DF630643F1863DFD0275B62FC7364EEC9C5CD5EBCF12769D53A`
- seed: `1002`; stream chunk size: one codec frame
- both persistent workers reported `ready.warmed_up=true` and exited with code
  zero

## Mechanical results

| case | guard OFF | frames | guard ON | frames | OFF/ON PCM |
| --- | --- | ---: | --- | ---: | --- |
| RU medium | `natural_eos` | 147 | `natural_eos` | 147 | byte-identical |
| RU long | `natural_eos` | 218 | `natural_eos` | 218 | byte-identical |
| EN medium | `natural_eos` | 156 | `eos_assisted` | 151 | different |
| EN long | `natural_eos` | 202 | `eos_assisted` | 198 | different |

All eight requests stayed bounded. First PCM was 183-201 ms. Maximum
inter-chunk gaps were 27.6-35.9 ms with the guard disabled and 28.1-42.1 ms
with it enabled. The previous `max_tokens` and 415 ms gap were not reproduced
with correct conditioning.

## Listening result

Human listening on 2026-09-28 confirmed:

- all RU and EN phrases are intelligible and complete in both modes;
- the intended warm Kraftwerk voice is preserved;
- no words are lost in the two guard-assisted English endings;
- some endings are very tight: the final sound can lack a smooth decay.

The guard does not improve these four correctly conditioned trajectories:
guard OFF already reaches natural EOS for all cases. Guard ON changes only the
English endings and introduces the small tail-quality concern above. Therefore
this evidence supports keeping the guard opt-in rather than enabling it by
default. Tail padding/fade policy, if desired, is an audio-output concern and
must not be represented as model/EOS correctness.


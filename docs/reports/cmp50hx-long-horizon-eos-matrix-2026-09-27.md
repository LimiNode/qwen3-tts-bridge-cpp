# CMP 50HX long-horizon RU/EN EOS matrix (2026-09-27)

This follow-up uses the canonical pair from the CUDA-graphs reports:
Bridge `202e64c8`, qwentts `130cb99`, Q8 models, registered
`kraftwerk_robot_ru_bootstrap_fidelity`, CUDA graphs ON, one persistent worker,
and `--stream-max-chunk-frames 1`. Four longer RU/EN texts were run with seed
`1002`, first with the EOS guard disabled and then with `--eos-guard`.

## Guard disabled

| case | terminal | frames/chunks | first PCM | wall | median gap | max gap |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| RU medium | `natural_eos` | 228 | 180.6 ms | 6.20 s | 26.2 ms | 38.9 ms |
| RU long | `natural_eos` | 617 | 196.3 ms | 17.30 s | 27.7 ms | 53.5 ms |
| EN medium | `max_tokens` | 2049 | 186.8 ms | 55.66 s | 27.0 ms | 46.4 ms |
| EN long | `natural_eos` | 1182 | 182.2 ms | 47.99 s | 27.6 ms | 415.2 ms |

The English medium case hit the hard token limit, and the English long case had
a pathological 415 ms inter-chunk gap. These are acceptance failures, not
graphs failures to hide: short-horizon graph correctness remains unchanged,
but long-horizon/EOS behavior is not yet release-ready for this matrix.

## Guard enabled

| case | terminal | frames/chunks | first PCM | wall | median gap | max gap |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| RU medium | `eos_assisted` | 243 | 190.5 ms | 6.30 s | 25.1 ms | 37.3 ms |
| RU long | `eos_assisted` | 395 | 179.8 ms | 10.13 s | 25.1 ms | 35.8 ms |
| EN medium | `eos_assisted` | 172 | 179.2 ms | 4.47 s | 24.8 ms | 27.3 ms |
| EN long | `eos_assisted` | 233 | 180.5 ms | 5.97 s | 24.9 ms | 26.3 ms |

The guard prevents the runaway English trajectory and restores bounded chunk
gaps, but every case is `eos_assisted`, including the Russian cases. This is
mechanical evidence only; no default-on decision is made without listening for
truncated endings and semantic completeness.

## Decision

CUDA graphs remain the performance/runtime choice: the earlier paired and
100-request reports show byte-identical short-horizon output and stable
streaming. The long-horizon matrix keeps EOS guard policy open. The next gate
is listening/semantic review of the four guard OFF/ON pairs, followed by a
larger text/seed matrix before changing production defaults.


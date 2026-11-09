# CMP 50HX upstream FP16 code-predictor mitigation

> Historical diagnostic summary (August 2026). It records a bounded experiment and is not a current release gate. Raw machine artifacts are intentionally local-only and are not part of this curated documentation set.

Date: 2026-08-07
Scope: source-only diagnostic and fix validation. The published R3 package was
used read-only for its private Python runtime and was not rebuilt or modified.

## Finding

The first non-finite value in the failing CustomVoice request is produced by
the code-predictor decoder layer 2 gated MLP. `gate_proj` and `up_proj` are
finite FP16 tensors, but `SiLU(gate_proj(x)) * up_proj(x)` overflows binary16.
`down_proj` propagates the infinity and the following layer eventually produces
NaN logits/probabilities for `torch.multinomial`.

This is a numerical range failure, not evidence of an SDPA kernel failure. The
earlier source trace is retained in
`cmp50hx-source-upstream-fp16-tensor-trace-v3-worker.stderr.log`.

## Source change

`--code-predictor-compute-dtype float32` is an explicit upstream-only opt-in.
It keeps the main talker and code-predictor codec embeddings at the model dtype,
but executes the code-predictor projection, decoder, and logits in FP32. The
predictor input is converted to FP32 immediately before its projection. The
default `model` leaves the existing behavior unchanged; FasterQwen rejects this
option.

No compile, bridge CUDA graph, frequency profile, compiled allowlist, canary,
or schedule option was enabled.

## Validation on CMP 50HX

The source worker ran with the R3 private interpreter, `CUDA_VISIBLE_DEVICES`
set to `GPU-40361931-6cb5-ac58-a059-5ba3e70986fb`, and `--device cuda:0`.
The worker PID 83244 was observed by `nvidia-smi` on that CMP UUID.

Configuration: upstream, eager prefill, SDPA, main dtype FP16,
code-predictor compute dtype FP32, `--no-compile`, `--no-cuda-graphs`, fixed
seed 20260806. CustomVoice medium Russian request (`ryan`) completed naturally:

| field | value |
| --- | --- |
| terminal state | `completed` |
| termination | `eos` |
| PCM chunks / bytes | 40 / 1,217,102 |
| codec frames | 317 |
| max-seq / max-new-token termination | false / false |
| first PCM | 10,017.572 ms |
| synthesis time | 203,912.599 ms |
| audio duration | 25,356.292 ms |
| RTF | 8.041893 |

This validates correctness only; it is not a realtime profile.

Unit tests: 38 passed (`test_engine_factory`, `test_qwen_model_loader`,
`test_cuda_graph_controls`).

## Sealed R3 verification

After the source run, both R3 manifest verifiers passed. The package-tree
manifest keeps the expected verified digest
`c2a5133e843d5660b2fd0ca3c2b633f54154195c6fc1c76e7d0994542211ecfc`.
The source fix and temporary diagnostic hooks reside outside the sealed tree.

## Evidence

Raw result, provenance, and worker-log artifacts are retained locally and intentionally omitted from this curated documentation set.

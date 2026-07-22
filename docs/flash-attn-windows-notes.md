# Flash-Attn Windows Notes

This project can run the Qwen3-TTS streaming fork on Windows without
`flash-attn`, but the fork warns that it falls back to a slower manual PyTorch
attention path.

Current working runtime:

- Python: 3.11.9.
- PyTorch: `2.11.0+cu126`.
- Torchaudio: `2.11.0+cu126`.
- Triton package: `triton-windows==3.7.1.post27`.

Findings:

- Upstream `flash-attn` documents Linux as the primary supported platform and
  says Windows compilation still requires more testing.
- The vendored Qwen streaming fork recommends a Windows matrix based on Python
  3.12, CUDA 13.0, a `flash_attn` wheel built for torch 2.10, and
  `triton-windows<3.7`.
- The current bridge packaging baseline intentionally uses Python 3.11. A
  compatible `flash_attn` wheel for the exact current matrix
  (`cp311`, `torch2.11`, `cu126`, `win_amd64`) was not found during this pass.
- Installing `triton-windows` into `.venv-packaging` removes PyTorch's
  `triton not found` warning, but does not satisfy Qwen's `flash_attn` import.
- The optimized/warmup path reaches near real-time on RTX 4090 without
  `flash-attn`, so changing the main packaging matrix is not required for the
  current bridge validation.

Recommended next experiment:

Create a separate throwaway environment for the Qwen fork's recommended Windows
matrix instead of changing `.venv-packaging` in place:

```powershell
py -3.12 -m venv .venv-qwen-flash
.\.venv-qwen-flash\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu130
.\.venv-qwen-flash\Scripts\python.exe -m pip install "triton-windows<3.7"
```

Then install the exact community `flash_attn` wheel recommended by the Qwen
fork README for the selected torch/Python version and run the same benchmark
commands against that environment. Keep this separate until it shows a clear
latency or RTF win over the Python 3.11 warmup baseline.

Sources checked:

- `external/python/Qwen3-TTS-streaming/README.md`
- https://pypi.org/project/flash-attn/
- https://github.com/mjun0812/flash-attention-prebuild-wheels

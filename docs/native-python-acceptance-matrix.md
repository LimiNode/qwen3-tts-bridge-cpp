# Native versus Python acceptance matrix

The native process worker and the accepted Python/FasterQwen worker use the
same C++ benchmark executable and QTB transport. This keeps request timing and
callback dispatch comparable while allowing the engines to produce different
PCM trajectories. Byte-for-byte PCM parity is not a gate between these engine
families; successful text, natural EOS, identity, absence of starvation, and
audible quality are measured separately.

Required workload rows:

| Dimension | Rows |
| --- | --- |
| Language | Russian, English |
| Length | 1–2 words, short sentence, medium paragraph, long paragraph near the configured limit |
| Lifecycle | warmed worker, cold start, 30–100 sequential requests, cancellation after first PCM, reset/restart |
| Voice | Kraftwerk profile/reference, A→B→A voice switch |
| Metrics | startup, first PCM, inter-chunk cadence, total synthesis, RTF, starvation, EOS, errors, peak VRAM |

Run every row with the same model family, seed policy, and runtime settings.
The native manifest commit, ABI, DLL hashes, and backend must be retained with
the raw result. The Python package and source revisions must be retained too.

The benchmark fails a row if the request does not complete, PCM arrives after
cancellation, EOS is missing, or a protocol/stdout violation occurs. Keep raw
JSON and stderr telemetry. Add a short subjective listening check for clicks,
pauses, clipping, word endings, and voice identity after objective gates pass.

The repository currently has no local GGUF pair, so a real hardware comparison
is intentionally not claimed by CI. Supply model paths from outside the source
tree when running the matrix.

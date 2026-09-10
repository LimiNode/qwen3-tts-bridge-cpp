# Protocol domain

The protocol domain owns QTB framing, incremental parsing, control validation,
and error/completion mapping. It is byte/protocol code only: no process,
thread, CUDA, Python, or playback policy belongs here.

Keep frame-size, version, flag, and request-ID checks at the framing boundary.
Keep JSON decoding split by responsibility instead of growing a monolithic
codec. Preserve the documented terminal-state and late-audio rules. Add a
deterministic test for every new field or validation branch.

# CMP 50HX automatic profile routing

`qwen_tts_play --auto-profile` keeps two static FasterQwen workers alive: the
configured fast worker and a derived `cmp50hx-safe` worker. Each request is sent
to one worker before synthesis starts; CUDA graphs are never changed while a
request is running.

The default policy counts non-space UTF-8 bytes as a conservative text-length
proxy. Texts up to 240 bytes use the fast worker; longer texts use the safe
worker. The threshold can be changed with `--auto-fast-max-chars`. The name is
kept for CLI compatibility, but the value is a byte budget rather than a word
or language-specific token count.

Automatic mode requires the worker arguments to contain a `--runtime-profile`
option. The second worker is derived by replacing its profile and static
capacity settings with `cmp50hx-safe`, `max_seq_len=2048`, E8, and W33. Both
workers must advertise compatible voice capabilities. Since two model workers
are resident, applications should verify available VRAM before enabling this
mode.

The policy is intentionally conservative and deterministic. It does not split
one utterance into multiple requests: splitting can alter prosody and voice
continuity. A future tokenizer-aware policy may replace the byte proxy after a
multilingual boundary matrix is available.

Example:

```text
qwen_tts_play.exe --worker python.exe --auto-profile \
  --worker-arg -m --worker-arg qwen_tts_bridge_worker \
  --worker-arg qwen --worker-arg --runtime-profile \
  --worker-arg cmp50hx-fastest ...
```

`cmp50hx-fastest-experimental` remains accepted as a compatibility alias for
the fastest opt-in profile.

The option is intended for the persistent interactive CLI as well as one-shot
requests. `/cancel` cancels whichever worker owns the active request.

# Python worker protocol package

Keep framing, data types, and control/error JSON mapping in their respective
subdomains. The protocol package must not import Qwen model classes or perform
inference. Enforce payload limits in the framing layer before calling JSON
decoders, as required by the deferred-agent notes in the root contract.

Prefer one validation owner per field and table-driven tests for equivalent
message variants. Do not duplicate the C++ protocol schema in ad-hoc helpers;
update `docs/protocol-v1.md` and both implementations together.

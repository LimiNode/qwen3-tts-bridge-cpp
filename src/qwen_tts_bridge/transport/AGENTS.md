# Transport domain

Transports move bytes and report transport lifecycle; they do not interpret
QTB messages or invoke application callbacks. Read boundaries are arbitrary,
`stop()` is idempotent, and non-accepted sends are handled as session failures
until an outbound retry/writable-notification contract exists.

Keep worker supervision and protocol parsing in their owning layers. Any change
to thread shutdown, stderr handling, or environment overrides needs a lifecycle
regression test and must not hold a mutex while calling user code.

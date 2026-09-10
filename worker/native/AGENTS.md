# Native qwentts.cpp worker

This is an opt-in process worker around the pinned `external/cpp/qwentts.cpp`
C ABI. Verify the runtime manifest, DLL hashes, ABI, and engine commit before
the worker sends `ready`. Keep qwentts logs on stderr and QTB frames on binary
stdout.

The native worker must fail closed on invalid requests, empty successful EOS,
capacity overflow, cancellation, and unknown finish reasons. Any new native
profile control needs an ABI/runtime test and a documented hardware result.
Do not claim parity with FasterQwen without identical workload, seed, lifecycle,
quality, and timing evidence. Keep native fallback/routing signals explicit;
do not silently retry a partially played request.

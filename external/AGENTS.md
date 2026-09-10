# `external/` — pinned dependencies

All external source dependencies are git submodules pinned to reachable
commits. Do not edit vendored code as part of a bridge change. For qwentts.cpp,
keep the selected `LimiNode` fork and its ABI/runtime manifest contract; do not
substitute an upstream repository or an unrelated prebuilt DLL.

A dependency update is its own logical change: record the purpose, pin reason,
and compatibility evidence. Push the dependency commit before pushing the
parent gitlink so CI can clone it.

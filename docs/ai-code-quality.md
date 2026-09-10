# AI-assisted code quality

This project accepts AI-assisted changes, but generated code is not a quality
criterion. The goal is the smallest implementation that makes the required
invariant explicit, testable, and maintainable.

The policy is informed by Andrey Karpov's review [“Опухший C++ код”](https://habr.com/ru/companies/pvs-studio/articles/1072264/),
especially its observations about copy-paste growth, redundant conditions,
unnecessary abstractions, and code that is harder for both people and static
analysis to inspect.

## Rules for agents and reviewers

1. Search for an existing implementation before adding a helper, option, DTO,
   parser, or test. Extend the existing owner when the behavior belongs there.
2. Prefer deletion or reuse over adding a parallel implementation. Similar
   blocks must either share one implementation or document why their semantics
   are intentionally different.
3. Keep a function focused. Split a function when it owns independent policy,
   lifecycle, parsing, or I/O decisions—not merely to hit an arbitrary line
   count.
4. Do not add speculative layers, generic wrappers, compatibility aliases, or
   configuration knobs without a current caller and a test.
5. Remove impossible branches and redundant checks. If a condition documents a
   safety invariant, enforce that invariant at the boundary and comment the
   reason once.
6. Use `noexcept` only when no exception can escape the function. A
   potentially-throwing operation is allowed only when that path is proven
   non-throwing or its exception is caught before leaving the function. Never
   add `noexcept` merely as an optimization annotation.
7. Do not claim a performance improvement without a reproducible before/after
   measurement, the workload, and the hardware/runtime identity.
8. Tests must exercise behavior and failure modes. Source-text assertions are
   acceptable only for scripts/configuration contracts where no executable
   seam exists.
9. Keep generated or machine-local output out of the repository. Do not add
   bulk formatting, renames, or unrelated cleanup to a feature change.
10. When a change increases code size, the PR description must name the new
    invariant or capability and why reuse/deletion was insufficient. Reviewers
    should ask what can be removed before approving more code.

## Required review pass

Before opening a PR, an agent must perform a short anti-slop pass:

- inspect changed files for duplicated blocks and repeated literals;
- inspect changed functions for redundant branches, dead parameters, and
  exception specifications that do not match the body;
- run the narrowest relevant tests plus the normal build/lint checks;
- record any intentionally deferred refactor instead of copying a second
  implementation;
- include a brief “quality review” note in the PR body when the change touches
  a large file or adds more than one similar branch.

The existing large benchmark, launcher, and model-adapter files are historical
boundaries, not permission to grow them indefinitely. New work in those files
should extract a cohesive domain module when doing so reduces duplication and
keeps the public contract unchanged.

## Review outcome vocabulary

- **blocker**: duplicated or dead logic can change behavior, an exception/
  `noexcept` contract is invalid, or the change has no testable owner;
- **warning**: a maintainability or size concern that is safe to defer with a
  named follow-up;
- **accepted**: code is intentionally explicit because the protocol, hardware
  profile, or failure contract requires the distinction.

This policy complements, and does not replace, the architecture and safety
rules in the root [`AGENTS.md`](../AGENTS.md).

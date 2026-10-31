# Acceptance evidence migration — 2026-10-31

This record documents the local migration of historical Base acceptance
evidence. It does not change the experiment-time provenance recorded by the
older reports.

## Locations

| Role | Path |
| --- | --- |
| Original experiment-time root | `E:\stage-a-base-evidence` |
| Current local archive | `E:\_repoz\qwen3-tts-bridge-cpp\.tmp\historical\stage-a-base-evidence` |
| Repository-relative archive | `.tmp/historical/stage-a-base-evidence/` |

The original paths remain in the historical Markdown and JSON reports because
they identify where the files were produced. The repository-relative path is
the current location of the verified copy.

The archive is ignored by Git. Its files are not committed, transferred, or
backed up by Git. Keep an independent backup before deleting the original
rollback copy or the local archive.

## Verification

The source and destination inventories were compared on 2026-10-31.

- Relative file count: `13` source / `13` destination.
- Total bytes: `1,081,824` source / `1,081,824` destination.
- Every relative path exists at the destination.
- Every file size and SHA-256 matches.
- JSON receipts parse successfully.
- `voice-registry/voice-profiles.local.json` and
  `voice-registry/kraftwerk_robot_ru_fidelity.wav` remain present.
- No model weights were copied by this migration.

The verification used PowerShell `Get-FileHash -Algorithm SHA256` over both
trees and `python -m json.tool` for the three JSON report files that reference
the migrated evidence.

## Inventory

| Relative path | Bytes | SHA-256 |
| --- | ---: | --- |
| `b1-active-cancel.json` | 46,733 | `5c27d7d455d329d3323676f0f14731ecf89a231cb9f7d266850af21ea3cc2f1f` |
| `b1-cancel-recovery.json` | 442 | `2a66578b82b8a037cde625dd226cbb3625ea7e2d3d080bb4cbecf35636a6a866` |
| `b1-persistent-benchmark.json` | 16,288 | `53d17d076cecfe2533df9c61cc1a234d521951f63f531091b76154e2dc47b8b1` |
| `b1-persistent-eos-oracle.json` | 3,363 | `940d5e23d25d4670f1f97b8cb740ea029e4f1475df95b3b538537e6cb06a5d68` |
| `b1-playback-capture` | 152,460 | `4e30a2690eb81f9b751997f0dfab424bbb434c96338694db6a0d7c7a44363712` |
| `b1-playback-capture.json` | 222 | `142bfc61e0549f2cbb4350e77a2e11c3b7c700be5d3668a0d6649d85df410078` |
| `b1-playback-metrics.json` | 1,341 | `82180aadbdb4ca71d19ced3c19a34ae318c26a4aadf47b8ff7a99bc644b0f852` |
| `b1-real-base-smoke.json` | 11,467 | `e059cb37fdd679740fce4402d552e8c238de7a900fdd9a5b8862974168d1e6f5` |
| `b1-real-base-smoke-utf8.json` | 786 | `bd23242a2cee1f8f0ee276224937d51ed1cbfcd9b54adf02f94f8b8371c1dacd` |
| `b1-restart.json` | 858 | `582f3e8dea4d7f2eb08a9695e48a63b2b52cd5f3612f89df80ae7f0aa1454a81` |
| `qwen3-tts-12hz-1.7b-base-manifest.json` | 2,424 | `b6b32e0067c0878f3c7bf231f2961bef3e4b0eb0cb87e1b871a42dd302a21a12` |
| `voice-registry/kraftwerk_robot_ru_fidelity.wav` | 844,844 | `90e5f7576991ea5b9f0a85e9109f7bd31ff667c4a12d58783a06c650796c3ca1` |
| `voice-registry/voice-profiles.local.json` | 596 | `02155a13fdeaac3e5ffd67edf39d620a497f0c1d49ac5624c1d8a79c4c5c7b24` |

The original external directory is intentionally not deleted by this PR.

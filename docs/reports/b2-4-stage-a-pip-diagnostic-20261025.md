# B2-4 Stage A: locked pip provisioning diagnostic

Status: diagnostic only. Stage A portable acceptance remains blocked.

## Scope and provenance

This report follows the merged Stage A receipt on `main`:

```text
main: e115deb8e0dcb5f0a766a9c4e7bb6a726ae322d3
Python: 3.11.9
venv pip: 24.0
requirements: worker/requirements-packaging.lock.txt (unchanged)
worker source: editable checkout (unchanged)
```

The experiment was run in the dedicated worktree
`chore/b2-4-pip-diagnostic`. No packaging script, lock file, dependency
version, model, or production source was changed.

## Question

The earlier 180-second diagnostic stopped while pip was processing the locked
environment. The purpose of this run was to distinguish resolver work and wheel
staging from a process with no observable progress, and to test whether moving
pip's temporary paths from the system drive to E: changed the behavior.

## Controlled experiment

The exact locked install was run in a fresh Python 3.11 virtual environment:

```powershell
$venvPython = '.\.tmp\pip-diagnostic\venv-e\Scripts\python.exe'
$diagnosticTemp = (Resolve-Path '.\.tmp\pip-diagnostic\temp').Path
$env:TEMP = $diagnosticTemp
$env:TMP = $diagnosticTemp
$env:TMPDIR = $diagnosticTemp

& $venvPython -m pip --disable-pip-version-check install -vvv `
  --log '.\.tmp\pip-diagnostic\pip-e.verbose.log' `
  --no-warn-script-location `
  -r 'worker\requirements-packaging.lock.txt' `
  -e '.\worker'
```

The pip cache was intentionally not relocated. The intended controlled change
was to redirect temporary staging to E:, while the run itself used a fresh venv
instead of the earlier partially prepared environment. There was no matched
same-venv C:-staging A/B run, so this experiment does not isolate the
performance effect of staging relocation from all other factors. The run had a
360-second watchdog budget and was terminated by that watchdog; pip did not
emit a final exit code.

At the start of the run, free space was approximately 103.9 GB on C: and
79.3 GB on E:. The effective pip cache remained
`C:\Users\User\AppData\Local\pip\cache`; no global, user, or venv pip config
file was present. During the controlled run `tempfile.gettempdir()` resolved to
the E: diagnostic directory, while the cache stayed on C:.

The full verbose logs and temporary tree remain local under
`.tmp/pip-diagnostic/` and are intentionally not committed because they contain
large generated data and machine-local paths.

## Observations

| UTC | Observation |
| --- | --- |
| 09:41:13 | Fresh venv pip process started. |
| 09:41:18 | Build-isolation setuptools bootstrap completed. |
| 09:41:22–09:43:19 | Resolver scanned PyPI/PyTorch candidates and produced metadata directories. |
| 09:43:19.267 | Cached `torch==2.10.0+cu128` wheel selected; reported size 2867.4 MB. |
| 09:43:47.269 | `Installing collected packages` began. |
| 09:43:19 | Process sample: approximately 100% CPU and 238 MB/s read/write activity. |
| 09:46:16 | Temporary staging tree measured 3,081,174,261 bytes; process still running. |
| ~09:47:13 | 360-second watchdog expired; no pip completion/error line was emitted. |

During resolver work the verbose log grew continuously. During wheel staging,
the E: temporary tree contained `pip-unpack-*` entries for Torch, Torchaudio
and the other locked wheels. CPU time continued increasing; the process was not
idle. After the watchdog terminated the process, the temporary tree was no
longer present; the partial venv remained for inspection.

The resulting partial venv occupied approximately 5.19 GB. `pip check` reported
no broken requirements, but that is not a lock completeness check. Comparing
the installed distributions with the lock showed these pinned packages were
still absent:

```text
accelerate, fastapi, gradio, gradio_client, hf-gradio, httpx,
huggingface_hub, librosa, pandas, pooch, pydantic, rich, safehttpx,
scikit-learn, soundfile, starlette, tokenizers, torchaudio, transformers,
typer
```

`torch==2.10.0+cu128` was present and importable. `torchaudio` was not present.
The environment therefore cannot be used for packaging acceptance.

## Conclusion

This experiment rules out the interpretation that pip is simply deadlocked with
no work after selecting the cached Torch wheel. The resolver and subsequent
wheel staging show sustained CPU, file-system writes, and temporary storage
growth on E:. Moving `TMP/TEMP` did not make the full locked install complete
within six minutes, but it did expose the active operation and its storage
cost.

The concrete blocker is therefore **uncompleted local installation within the
available diagnostic budget**, with the expensive phase beginning at the
2.87-GB Torch wheel and continuing through unpack/install of the locked set. The
evidence does not distinguish CPU decompression, file-system throughput, or
security scanning as the individual limiting factor. No dependency substitution
or packaging-code change is justified by this run.

For comparison, the successful Windows CI log completes the corresponding base
setup in roughly 264 seconds, including about 222 seconds after the Torch wheel
line. That makes a 180-second watchdog insufficient, while the local six-minute
run still warrants a separate machine-level performance investigation if the
portable package must be produced on CMP 50HX.

## Decision

- Stage A remains `BLOCKED`; no portable package acceptance is claimed.
- The canonical lock and packaging scripts remain unchanged.
- The next safe experiment is a longer bounded run with per-process CPU, I/O,
  disk-space and staging measurements, or an equivalent clean-machine run.
- Antivirus/security settings must not be disabled as a workaround.
- If a packaging-code correction is proposed later, it must be based on a
  reproducible failure and submitted separately from this evidence report.

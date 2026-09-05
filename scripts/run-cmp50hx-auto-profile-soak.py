#!/usr/bin/env python3
"""Exercise the CMP 50HX automatic router through the interactive CLI."""

from __future__ import annotations

import argparse
import json
import queue
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any


@dataclass(frozen=True, slots=True)
class Case:
    label: str
    text: str
    voice_id: str | None = None
    cancel_after_first_pcm: bool = False


@dataclass(slots=True)
class CaseResult:
    label: str
    estimated_bytes: int
    expected_profile: str
    selected_profile: str = ""
    request_id: int = 0
    terminal_state: str = ""
    first_audio_ms: float | None = None
    audio_duration_ms: float | None = None
    synthesis_ms: float | None = None
    real_time_factor: float | None = None
    chunk_count: int = 0
    starvation_proxy_count: int = 0
    natural_eos: bool = False
    hit_max_seq_len: bool = False
    prefix_reuse_hit: bool | None = None
    voice_id: str | None = None
    errors: list[str] = field(default_factory=list)


def estimated_text_bytes(text: str) -> int:
    return sum(value > 0x20 for value in text.encode("utf-8"))


def default_cases(primary_voice: str, alternate_voice: str) -> list[Case]:
    short_ru = [
        "Привет.",
        "Система готова.",
        "Проверка связи завершена.",
        "Проофиль Kraftwerk Robot работает на CMP 50HX.",
        "Температура стабильна, продолжаю работу.",
        "Я слышу тебя и готов ответить.",
    ]
    short_en = [
        "Hello, operator.",
        "The system is ready.",
        "Audio routing is stable.",
        "I am processing your request now.",
        "The connection is clear and reliable.",
        "The next response should start quickly.",
    ]
    safe_ru = (
        "Сейчас система проверяет автоматический выбор профиля для достаточно "
        "длинной реплики. Она должна заранее оценить размер всего текста, выбрать "
        "безопасный режим с увеличенным окном последовательности и произнести ответ "
        "полностью, без пропавшего окончания, длительных пауз и разрывов между чанками."
    )
    safe_en = (
        "The automatic router is checking a deliberately long assistant response. "
        "It should estimate the complete input before synthesis begins, select the "
        "safe worker with the larger sequence window, and finish the sentence "
        "naturally "
        "without missing words, long pauses, or interruptions between audio chunks."
    )

    cases: list[Case] = []
    for index in range(24):
        text = (
            short_ru[index % len(short_ru)]
            if index % 2 == 0
            else short_en[index % len(short_en)]
        )
        cases.append(Case(f"fast-{index + 1:02d}", text, primary_voice))
        if index in {4, 10, 16, 22}:
            long_text = safe_ru if index % 4 == 0 else safe_en
            cases.append(Case(f"safe-{index // 6 + 1:02d}", long_text, primary_voice))

    # A -> B -> A validates per-voice prefix cache isolation and reuse.
    cases.extend(
        [
            Case("voice-a-before", "Проверка первого голоса.", primary_voice),
            Case("voice-b", "Проверка тёплого варианта голоса.", alternate_voice),
            Case("voice-a-after", "Повторная проверка первого голоса.", primary_voice),
        ]
    )
    # The cancellation request is followed by a normal recovery request.
    cases.extend(
        [
            Case(
                "cancel-after-first-pcm",
                safe_ru
                + " После отмены этот фрагмент не должен быть произнесён полностью.",
                primary_voice,
                cancel_after_first_pcm=True,
            ),
            Case(
                "post-cancel-recovery",
                "После отмены новый запрос работает нормально.",
                primary_voice,
            ),
        ]
    )
    return cases


def parse_metric(line: str) -> dict[str, Any] | None:
    marker = "qtb_metric "
    offset = line.find(marker)
    if offset < 0:
        return None
    try:
        value = json.loads(line[offset + len(marker) :])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


class InteractiveSession:
    def __init__(self, command: list[str], raw_log: Path) -> None:
        self._raw_log = raw_log.open("w", encoding="utf-8", newline="\n")
        self._log_lock = threading.Lock()
        self._lines: queue.Queue[tuple[str, str]] = queue.Queue()
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert self.process.stdout is not None
        assert self.process.stderr is not None
        self._threads = [
            threading.Thread(
                target=self._reader, args=("stdout", self.process.stdout), daemon=True
            ),
            threading.Thread(
                target=self._reader, args=("stderr", self.process.stderr), daemon=True
            ),
        ]
        for thread in self._threads:
            thread.start()

    def _reader(self, source: str, stream: IO[str]) -> None:
        for line in stream:
            clean = line.rstrip("\r\n")
            with self._log_lock:
                self._raw_log.write(f"[{source}] {clean}\n")
                self._raw_log.flush()
            self._lines.put((source, clean))

    def send(self, line: str) -> None:
        if self.process.stdin is None:
            raise RuntimeError("interactive stdin is closed")
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def next_line(self, deadline: float) -> tuple[str, str]:
        while True:
            if self.process.poll() is not None and self._lines.empty():
                raise RuntimeError(
                    f"interactive CLI exited with {self.process.returncode}"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for interactive CLI output")
            try:
                return self._lines.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue

    def wait_ready(self, timeout_seconds: float) -> None:
        deadline = time.monotonic() + timeout_seconds
        while True:
            _, line = self.next_line(deadline)
            if "profile=auto" in line:
                return

    def run_case(
        self, case: Case, threshold: int, timeout_seconds: float
    ) -> CaseResult:
        expected = (
            "cmp50hx-fastest"
            if estimated_text_bytes(case.text) <= threshold
            else "cmp50hx-safe"
        )
        result = CaseResult(
            label=case.label,
            estimated_bytes=estimated_text_bytes(case.text),
            expected_profile=expected,
            voice_id=case.voice_id,
        )
        if case.voice_id is not None:
            self.send(f"/voice {case.voice_id}")
            time.sleep(0.1)
        self.send(case.text)
        deadline = time.monotonic() + timeout_seconds
        chunks: list[tuple[float, float]] = []
        cancel_sent = False
        finished: dict[str, Any] | None = None
        while finished is None:
            _, line = self.next_line(deadline)
            route_marker = "auto profile: "
            route_offset = line.find(route_marker)
            if route_offset >= 0:
                result.selected_profile = line[
                    route_offset + len(route_marker) :
                ].split(" ", 1)[0]
            metric = parse_metric(line)
            if metric is None:
                if " failed:" in line:
                    result.errors.append(line)
                continue
            event = metric.get("event")
            metric_request_id = int(metric.get("request_id", 0) or 0)
            if event == "request_received" and result.request_id == 0:
                result.request_id = metric_request_id
            if result.request_id != 0 and metric_request_id not in {
                0,
                result.request_id,
            }:
                continue
            if event == "request_first_audio":
                result.first_audio_ms = float(metric["first_audio_ms"])
                if case.cancel_after_first_pcm and not cancel_sent:
                    self.send("/cancel")
                    cancel_sent = True
            elif event == "request_pcm_chunk":
                chunks.append(
                    (float(metric["pcm_ready_ms"]), float(metric["pcm_duration_ms"]))
                )
                if (
                    result.prefix_reuse_hit is None
                    and "voice_prefix_kv_reuse_hit" in metric
                ):
                    result.prefix_reuse_hit = bool(metric["voice_prefix_kv_reuse_hit"])
            elif event == "request_first_chunk_engine_phases":
                if "voice_prefix_kv_reuse_hit" in metric:
                    result.prefix_reuse_hit = bool(metric["voice_prefix_kv_reuse_hit"])
            elif event == "request_generation_trace":
                result.natural_eos = bool(metric.get("hit_eos", False))
                result.hit_max_seq_len = bool(metric.get("hit_max_seq_len", False))
            elif event == "request_finished":
                finished = metric

        result.terminal_state = str(finished.get("terminal_state", ""))
        if finished.get("audio_duration_ms") is not None:
            result.audio_duration_ms = float(finished["audio_duration_ms"])
        if finished.get("synthesis_ms") is not None:
            result.synthesis_ms = float(finished["synthesis_ms"])
        if finished.get("real_time_factor") is not None:
            result.real_time_factor = float(finished["real_time_factor"])
        result.chunk_count = len(chunks)
        # The first transition includes WaveOut/device startup and the accepted
        # E3 -> E4 schedule intentionally relies on that startup slack. Treat
        # only subsequent gaps as the steady playback starvation proxy.
        result.starvation_proxy_count = sum(
            1
            for (ready, duration), (next_ready, _) in zip(
                chunks[1:], chunks[2:], strict=False
            )
            if next_ready - ready > duration
        )

        if case.cancel_after_first_pcm:
            if result.terminal_state != "cancelled":
                result.errors.append(
                    f"expected cancellation, got {result.terminal_state}"
                )
        else:
            if result.terminal_state != "completed":
                result.errors.append(
                    f"expected completion, got {result.terminal_state}"
                )
            if not result.natural_eos:
                result.errors.append("request did not report natural EOS")
            if result.hit_max_seq_len:
                result.errors.append("request hit max_seq_len")
        if result.selected_profile != result.expected_profile:
            selected = result.selected_profile or "<missing>"
            result.errors.append(
                f"expected route {result.expected_profile}, got {selected}"
            )
        if result.starvation_proxy_count:
            result.errors.append(
                f"observed {result.starvation_proxy_count} starvation proxy gaps"
            )

        if (
            not case.cancel_after_first_pcm
            and result.audio_duration_ms
            and result.synthesis_ms
        ):
            tail_seconds = max(
                0.0, (result.audio_duration_ms - result.synthesis_ms) / 1000.0
            )
            time.sleep(min(tail_seconds + 0.25, 2.0))
        return result

    def close(self) -> int:
        if self.process.poll() is None:
            try:
                self.send("/quit")
            except (BrokenPipeError, RuntimeError):
                pass
        try:
            return self.process.wait(timeout=120)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            return self.process.wait(timeout=30)
        finally:
            self._raw_log.close()


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction + 0.999999)))
    return ordered[index]


def query_gpu_memory(device_index: int) -> dict[str, int]:
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,memory.used,memory.free,memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    for line in completed.stdout.splitlines():
        values = [value.strip() for value in line.split(",")]
        if len(values) != 4 or int(values[0]) != device_index:
            continue
        return {
            "device_index": int(values[0]),
            "used_mib": int(values[1]),
            "free_mib": int(values[2]),
            "total_mib": int(values[3]),
        }
    raise RuntimeError(f"nvidia-smi did not report CUDA device {device_index}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--build-directory", required=True)
    parser.add_argument("--worker-python", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--faster-source-path", type=Path, required=True)
    parser.add_argument("--qwen-source-path", type=Path, required=True)
    parser.add_argument("--voice-registry-path", type=Path, required=True)
    parser.add_argument("--voice-id", required=True)
    parser.add_argument("--alternate-voice-id", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--threshold", type=int, default=240)
    parser.add_argument("--cuda-device-index", type=int, default=0)
    parser.add_argument("--minimum-free-vram-mib", type=int, default=13 * 1024)
    parser.add_argument("--startup-timeout-seconds", type=float, default=300.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=180.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for path in (
        args.launcher,
        args.worker_python,
        args.model_path,
        args.faster_source_path,
        args.qwen_source_path,
        args.voice_registry_path,
    ):
        if not path.exists():
            raise FileNotFoundError(path)
    args.output_directory.mkdir(parents=True, exist_ok=True)
    memory_before = query_gpu_memory(args.cuda_device_index)
    preflight_path = args.output_directory / "preflight.json"
    preflight = {
        "observed_gpu_memory": memory_before,
        "minimum_free_vram_mib": args.minimum_free_vram_mib,
        "passed": memory_before["free_mib"] >= args.minimum_free_vram_mib,
    }
    preflight_path.write_text(
        json.dumps(preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not preflight["passed"]:
        observed_free = memory_before["free_mib"]
        print(
            "VRAM preflight failed: "
            f"device {args.cuda_device_index} has {observed_free} MiB free; "
            f"at least {args.minimum_free_vram_mib} MiB is required",
            file=sys.stderr,
        )
        return 2
    raw_log = args.output_directory / "interactive.log"
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(args.launcher.resolve()),
        "-BuildDirectory",
        args.build_directory,
        "-Python",
        str(args.worker_python.resolve()),
        "-ModelPath",
        str(args.model_path.resolve()),
        "-FasterSourcePath",
        str(args.faster_source_path.resolve()),
        "-QwenSourcePath",
        str(args.qwen_source_path.resolve()),
        "-VoiceRegistryPath",
        str(args.voice_registry_path.resolve()),
        "-RuntimeProfile",
        "cmp50hx-fastest",
        "-AutoProfile",
        "-AutoFastMaxChars",
        str(args.threshold),
        "-VoiceId",
        args.voice_id,
        "-Interactive",
    ]
    cases = default_cases(args.voice_id, args.alternate_voice_id)
    started_at = datetime.now(UTC)
    session = InteractiveSession(command, raw_log)
    results: list[CaseResult] = []
    process_exit_code = -1
    try:
        print("waiting for both automatic-profile workers", flush=True)
        session.wait_ready(args.startup_timeout_seconds)
        print("workers ready", flush=True)
        for index, case in enumerate(cases, 1):
            result = session.run_case(
                case, args.threshold, args.request_timeout_seconds
            )
            results.append(result)
            print(
                f"[{index:02d}/{len(cases):02d}] {case.label}: "
                f"{result.selected_profile}, {result.terminal_state}, "
                f"first={result.first_audio_ms}, "
                f"starvation={result.starvation_proxy_count}",
                flush=True,
            )
    finally:
        process_exit_code = session.close()

    fastest_first = [
        value.first_audio_ms
        for value in results
        if value.expected_profile == "cmp50hx-fastest"
        and value.terminal_state == "completed"
        and value.first_audio_ms is not None
    ]
    safe_first = [
        value.first_audio_ms
        for value in results
        if value.expected_profile == "cmp50hx-safe"
        and value.terminal_state == "completed"
        and value.first_audio_ms is not None
    ]
    by_label = {value.label: value for value in results}
    expected_prefix_hits = {
        "voice-a-before": True,
        "voice-b": False,
        "voice-a-after": True,
    }
    for label, expected_hit in expected_prefix_hits.items():
        value = by_label.get(label)
        if value is not None and value.prefix_reuse_hit is not expected_hit:
            value.errors.append(
                f"expected prefix reuse hit={expected_hit}, "
                f"got {value.prefix_reuse_hit}"
            )
    failures = [value.label for value in results if value.errors]
    report = {
        "schema_version": 1,
        "scope": "cmp50hx_auto_profile_operational_soak",
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "threshold_non_space_utf8_bytes": args.threshold,
        "vram_preflight": preflight,
        "process_exit_code": process_exit_code,
        "summary": {
            "cases": len(results),
            "completed": sum(value.terminal_state == "completed" for value in results),
            "cancelled": sum(value.terminal_state == "cancelled" for value in results),
            "route_mismatches": sum(
                value.selected_profile != value.expected_profile for value in results
            ),
            "starvation_proxy_count": sum(
                value.starvation_proxy_count for value in results
            ),
            "natural_eos_completed": sum(
                value.terminal_state == "completed" and value.natural_eos
                for value in results
            ),
            "failures": failures,
            "fastest_first_pcm_ms": {
                "samples": len(fastest_first),
                "median": statistics.median(fastest_first) if fastest_first else None,
                "p95": percentile(fastest_first, 0.95),
                "maximum": max(fastest_first) if fastest_first else None,
            },
            "safe_first_pcm_ms": {
                "samples": len(safe_first),
                "median": statistics.median(safe_first) if safe_first else None,
                "p95": percentile(safe_first, 0.95),
                "maximum": max(safe_first) if safe_first else None,
            },
        },
        "cases": [asdict(value) for value in results],
    }
    report_path = args.output_directory / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"report={report_path}")
    if process_exit_code != 0 or failures or len(results) != len(cases):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

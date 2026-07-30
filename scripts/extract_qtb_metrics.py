"""Extract valid QTB metrics from a Windows PowerShell-wrapped stderr capture."""

import argparse
import hashlib
import json
from pathlib import Path

PREFIX = "qtb_metric "


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = _decode_source(args.input.read_bytes())
    metrics = list(_extract_metrics(source))
    if not metrics:
        raise RuntimeError("stderr capture contains no valid qtb_metric JSON objects")
    output = "".join(f"{PREFIX}{metric}\n" for metric in metrics)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    print(
        json.dumps(
            {
                "metric_count": len(metrics),
                "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


def _extract_metrics(source: str) -> list[str]:
    position = 0
    metrics: list[str] = []
    while (prefix_at := source.find(PREFIX, position)) >= 0:
        object_at = prefix_at + len(PREFIX)
        if object_at >= len(source) or source[object_at] != "{":
            position = object_at
            continue
        metric, position = _extract_object(source, object_at)
        if metric is None:
            continue
        json.loads(metric)
        metrics.append(metric)
    return metrics


def _decode_source(source: bytes) -> str:
    if source.startswith((b"\xff\xfe", b"\xfe\xff")):
        return source.decode("utf-16")
    return source.decode("utf-8", errors="replace")


def _extract_object(source: str, start: int) -> tuple[str | None, int]:
    depth = 0
    in_string = False
    escaped = False
    characters: list[str] = []
    position = start
    while position < len(source):
        character = source[position]
        if character in "\r\n":
            position += 1
            continue
        characters.append(character)
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return "".join(characters), position + 1
        position += 1
    return None, position


if __name__ == "__main__":
    raise SystemExit(main())

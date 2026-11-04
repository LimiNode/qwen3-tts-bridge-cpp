"""Strictly validate a captured QTB1 byte stream without resynchronizing."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct


HEADER = struct.Struct("<4sHHHHIQ")
MAGIC = b"QTB1"
KNOWN_TYPES = {1: "control_json", 2: "audio_pcm", 3: "error_json"}


def context(data: bytes, offset: int, radius: int = 32) -> dict:
    start = max(0, offset - radius)
    end = min(len(data), offset + radius)
    return {
        "start": start,
        "end": end,
        "hex": data[start:end].hex(),
        "ascii": data[start:end].decode("ascii", errors="replace"),
    }


def validate(data: bytes) -> dict:
    frames = []
    offset = 0
    first_invalid = None
    while offset < len(data):
        remaining = len(data) - offset
        if remaining < HEADER.size:
            first_invalid = {
                "offset": offset,
                "reason": "truncated_header",
                "remaining": remaining,
                "context": context(data, offset),
            }
            break
        magic, version, header_size, frame_type, flags, payload_size, request_id = (
            HEADER.unpack_from(data, offset)
        )
        if magic != MAGIC:
            first_invalid = {
                "offset": offset,
                "reason": "invalid_magic",
                "expected": MAGIC.decode("ascii"),
                "observed_hex": magic.hex(),
                "context": context(data, offset),
            }
            break
        if version != 1 or header_size < HEADER.size or flags != 0:
            first_invalid = {
                "offset": offset,
                "reason": "invalid_header_fields",
                "version": version,
                "header_size": header_size,
                "flags": flags,
                "context": context(data, offset),
            }
            break
        total = header_size + payload_size
        if total > remaining:
            first_invalid = {
                "offset": offset,
                "reason": "truncated_frame",
                "frame_type": frame_type,
                "request_id": request_id,
                "payload_size": payload_size,
                "remaining": remaining,
                "context": context(data, offset),
            }
            break
        payload = data[offset + header_size:offset + total]
        frames.append({
            "offset": offset,
            "header_size": header_size,
            "frame_type": frame_type,
            "frame_name": KNOWN_TYPES.get(frame_type, "unknown"),
            "flags": flags,
            "payload_size": payload_size,
            "request_id": request_id,
            "nested_magic_offset": (
                offset + header_size + payload.find(MAGIC)
                if MAGIC in payload else None
            ),
        })
        offset += total
    return {
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "valid_stream": first_invalid is None,
        "first_invalid": first_invalid,
        "frames": frames,
        "parsed_bytes": offset,
    }


def validate_publication(data: bytes) -> dict:
    records = []
    concatenated = bytearray()
    offset = 0
    invalid = None
    while offset < len(data):
        if len(data) - offset < 8:
            invalid = {"offset": offset, "reason": "truncated_record_length"}
            break
        (size,) = struct.unpack_from("<Q", data, offset)
        record_offset = offset + 8
        if size > len(data) - record_offset:
            invalid = {
                "offset": offset,
                "reason": "truncated_record",
                "record_size": size,
                "remaining": len(data) - record_offset,
            }
            break
        record = data[record_offset:record_offset + size]
        concatenated.extend(record)
        result = validate(record)
        records.append({"offset": offset, "size": size, "validation": result})
        if not result["valid_stream"] and invalid is None:
            invalid = {"offset": offset, "reason": "invalid_frame", "validation": result}
        offset = record_offset + size
    return {
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "concatenated_sha256": hashlib.sha256(concatenated).hexdigest(),
        "valid_records": invalid is None,
        "first_invalid": invalid,
        "records": records,
        "parsed_bytes": offset,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--publication", action="store_true")
    args = parser.parse_args()
    result = validate_publication(args.capture.read_bytes()) if args.publication else validate(args.capture.read_bytes())
    output = json.dumps(result, indent=2)
    if args.report:
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if (result["valid_records"] if args.publication else result["valid_stream"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

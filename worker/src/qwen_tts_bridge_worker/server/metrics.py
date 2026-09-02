"""Structured runtime metrics for worker diagnostics."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import TextIO


@dataclass(slots=True)
class MetricsWriter:
    """Writes structured worker metrics to a text diagnostics stream."""

    stream: TextIO
    prefix: str = "qtb_metric "
    _lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )

    def emit(self, event: str, **fields: object) -> None:
        """Write one metric event and suppress diagnostics failures."""

        payload = {"event": event, **fields}
        try:
            line = (
                self.prefix
                + json.dumps(
                    payload,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            )
            with self._lock:
                self.stream.write(line)
                self.stream.flush()
        except Exception:
            return

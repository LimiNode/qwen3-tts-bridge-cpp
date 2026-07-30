from __future__ import annotations

import json
import unittest

from scripts.extract_qtb_metrics import _decode_source, _extract_metrics


class ExtractQtbMetricsTests(unittest.TestCase):
    def test_recovers_wrapped_json_and_ignores_diagnostics(self) -> None:
        source = (
            "warning from a dependency\r\n"
            'qtb_metric {"event":"request_finished","request_\r\nid":1}\r\n'
            'qtb_metric {"event":"request_finished","request_id":2}\r\n'
        )

        metrics = _extract_metrics(source)

        self.assertEqual(
            [
                {"event": "request_finished", "request_id": 1},
                {"event": "request_finished", "request_id": 2},
            ],
            [json.loads(metric) for metric in metrics],
        )

    def test_rejects_incomplete_json(self) -> None:
        self.assertEqual([], _extract_metrics('qtb_metric {"event":"broken"'))

    def test_decodes_utf16_powershell_capture(self) -> None:
        source = 'qtb_metric {"event":"request_finished","request_id":1}\n'

        decoded = _decode_source(source.encode("utf-16"))

        self.assertEqual(source, decoded)


if __name__ == "__main__":
    unittest.main()

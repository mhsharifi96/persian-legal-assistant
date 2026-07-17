from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "persian-legal-assistant-codex-skills"
    / "persian-legal-lawyer-fetcher"
    / "scripts"
    / "fetch_lawyers.py"
)
SPEC = importlib.util.spec_from_file_location("lawyer_fetcher_skill", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
fetcher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fetcher
SPEC.loader.exec_module(fetcher)

DADRAH_SCRIPT = SCRIPT.with_name("fetch_dadrah.py")
DADRAH_SPEC = importlib.util.spec_from_file_location("dadrah_fetcher_skill", DADRAH_SCRIPT)
assert DADRAH_SPEC is not None and DADRAH_SPEC.loader is not None
dadrah = importlib.util.module_from_spec(DADRAH_SPEC)
sys.modules[DADRAH_SPEC.name] = dadrah
DADRAH_SPEC.loader.exec_module(dadrah)


class LawyerFetcherSkillTests(unittest.TestCase):
    def test_empty_body_has_specific_error_type(self) -> None:
        bar = fetcher.Bar(id="bar-1", name="اردبیل")

        with self.assertRaises(fetcher.EmptySourceResponseError):
            fetcher.decode_response(b"", bar, content_type="")

    def test_run_continues_after_empty_bar_without_checkpointing_it(self) -> None:
        empty_bar = fetcher.Bar(id="bar-empty", name="اردبیل")
        populated_bar = fetcher.Bar(id="bar-data", name="اصفهان")
        source_row = {
            "id": "lawyer-1",
            "name": "علی",
            "family": "رضایی",
            "personNumber": "123",
        }

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "lawyers.jsonl"
            args = argparse.Namespace(
                bar=[],
                all_bars=True,
                output=output,
                checkpoint=None,
                input_json=None,
                delay_seconds=2.0,
                timeout_seconds=1.0,
                max_attempts=1,
            )

            with (
                patch.object(fetcher, "resolve_bars", return_value=[empty_bar, populated_bar]),
                patch.object(fetcher, "build_opener", return_value=object()),
                patch.object(fetcher, "bootstrap_session"),
                patch.object(
                    fetcher,
                    "fetch_bar",
                    side_effect=[
                        fetcher.EmptySourceResponseError("empty اردبیل"),
                        [source_row],
                    ],
                ),
                patch.object(fetcher.time, "sleep"),
            ):
                self.assertEqual(fetcher.run(args), 0)

            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["lawyer_id"] for row in rows], ["hamivakil:lawyer-1"])
            checkpoint = json.loads(
                output.with_suffix(".jsonl.checkpoint.json").read_text(encoding="utf-8")
            )
            self.assertEqual(checkpoint["completed_bar_ids"], ["bar-data"])

    def test_fetch_bar_refreshes_once_after_html_then_accepts_json(self) -> None:
        bar = fetcher.Bar(id="bar-1", name="اصفهان")
        response = MagicMock()
        response.__enter__.return_value.read.side_effect = [
            b"<html>session page</html>",
            b"[]",
        ]
        response.__enter__.return_value.headers.get.side_effect = [
            "text/html; charset=utf-8",
            "application/json",
        ]
        opener = MagicMock()
        opener.open.return_value = response

        with (
            patch.object(fetcher, "reset_session") as reset_session,
            patch.object(fetcher.time, "sleep"),
        ):
            self.assertEqual(
                fetcher.fetch_bar(opener, bar, timeout=1.0, max_attempts=2), []
            )

        reset_session.assert_called_once_with(opener, 1.0)
        self.assertEqual(opener.open.call_count, 2)

    def test_fetch_bar_stops_after_second_html_response(self) -> None:
        bar = fetcher.Bar(id="bar-1", name="اصفهان")
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"<html>blocked</html>"
        response.__enter__.return_value.headers.get.return_value = "text/html"
        opener = MagicMock()
        opener.open.return_value = response

        with (
            patch.object(fetcher, "reset_session") as reset_session,
            patch.object(fetcher.time, "sleep"),
        ):
            with self.assertRaises(fetcher.HtmlSourceResponseError):
                fetcher.fetch_bar(opener, bar, timeout=1.0, max_attempts=5)

        reset_session.assert_called_once_with(opener, 1.0)
        self.assertEqual(opener.open.call_count, 2)


class DadrahRangeFetcherTests(unittest.TestCase):
    def test_requested_range_is_split_into_ten_contiguous_chunks(self) -> None:
        chunks = dadrah.split_id_range(800_000, 891_818, 10)

        self.assertEqual(len(chunks), 10)
        self.assertEqual((chunks[0].start_id, chunks[0].end_id), (800_000, 809_181))
        self.assertEqual((chunks[-1].start_id, chunks[-1].end_id), (882_638, 891_818))
        self.assertEqual(
            sum(chunk.end_id - chunk.start_id + 1 for chunk in chunks),
            91_819,
        )
        self.assertTrue(
            all(left.end_id + 1 == right.start_id for left, right in zip(chunks, chunks[1:]))
        )

    def test_old_records_schema_is_rejected_before_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "chunk.jsonl"
            output.write_text('{"request_id":"10","records":[]}\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Old JSONL schema"):
                dadrah.validate_output_schema(output)

    def test_chunk_writes_jsonl_and_resumes_from_checkpoint(self) -> None:
        chunk = dadrah.IdChunk(number=1, start_id=10, end_id=11)
        html = """
        <html><body>
          <div class="bg-question">
            <div class="card-title"><h3>عنوان پرسش</h3></div>
            <div class="card-body">متن پرسش</div>
          </div>
          <div class="tags"><a href="/tag/test">خانواده</a></div>
          <div class="answer-card">
            <div class="answer-text">متن پاسخ</div>
            <a class="lawyer-name" href="/lawyer-one">وکیل نمونه</a>
            <div class="lawyer-meta">شهر تهران</div>
            <img class="lawyer-img" src="/images/one.jpg" alt="وکیل نمونه">
            <div class="date-time-item"><i class="fa-calendar"></i><span>۱۴۰۵/۳/۱</span></div>
            <div class="date-time-item"><i class="fa-clock"></i><span>۰۹:۰۶:۳۹</span></div>
            <div class="btn-actions">
              <a href="/lawyer-one/call">مشاوره تلفنی</a>
              <a href="/lawyer-one/meet">مشاوره حضوری</a>
            </div>
          </div>
        </body></html>
        """.encode()
        session = MagicMock()

        with tempfile.TemporaryDirectory() as temporary:
            output_directory = Path(temporary)
            limiter = dadrah.GlobalRateLimiter(0)
            stop_event = dadrah.threading.Event()

            with (
                patch.object(dadrah, "create_session", return_value=session),
                patch.object(
                    dadrah,
                    "fetch_html",
                    side_effect=[
                        (html, "https://www.dadrah.ir/consulting-paper.php?requestID=10"),
                        (html, "https://www.dadrah.ir/consulting-paper.php?requestID=11"),
                    ],
                ) as fetch_html,
            ):
                first = dadrah.fetch_chunk(
                    chunk,
                    output_directory=output_directory,
                    timeout_seconds=1,
                    rate_limiter=limiter,
                    stop_event=stop_event,
                )

            self.assertEqual(first["last_processed_id"], 11)
            self.assertEqual(fetch_html.call_count, 2)
            output, checkpoint = dadrah.chunk_paths(output_directory, chunk)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["request_id"] for row in rows], ["10", "11"])
            self.assertNotIn("records", rows[0])
            self.assertEqual(rows[0]["question"]["title"], "عنوان پرسش")
            self.assertEqual(rows[0]["question"]["text"], "متن پرسش")
            self.assertEqual(rows[0]["question"]["tags"][0]["name"], "خانواده")
            self.assertEqual(rows[0]["answers"][0]["text"], "متن پاسخ")
            self.assertEqual(rows[0]["answers"][0]["lawyer"]["city"], "تهران")
            self.assertEqual(json.loads(checkpoint.read_text())["last_processed_id"], 11)

            with (
                patch.object(dadrah, "create_session", return_value=session),
                patch.object(dadrah, "fetch_html") as fetch_html,
            ):
                resumed = dadrah.fetch_chunk(
                    chunk,
                    output_directory=output_directory,
                    timeout_seconds=1,
                    rate_limiter=limiter,
                    stop_event=stop_event,
                )

            self.assertEqual(resumed["last_processed_id"], 11)
            fetch_html.assert_not_called()

if __name__ == "__main__":
    unittest.main()

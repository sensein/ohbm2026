import json
import unittest
from types import SimpleNamespace

from scripts import openai_batch_smoke


class OpenAIBatchSmokeTest(unittest.TestCase):
    def test_build_batch_jsonl_line_targets_responses_endpoint(self) -> None:
        line = openai_batch_smoke.build_batch_jsonl_line("gpt-5-nano", "1. Smith A. Example title.")
        payload = json.loads(line)

        self.assertEqual(payload["method"], "POST")
        self.assertEqual(payload["url"], "/v1/responses")
        self.assertEqual(payload["body"]["model"], "gpt-5-nano")
        self.assertEqual(payload["body"]["reasoning"]["effort"], "minimal")
        self.assertIn("estimated_reference_count", payload["body"]["text"]["format"]["schema"]["properties"])

    def test_extract_output_text_prefers_output_text_then_message_content(self) -> None:
        direct = openai_batch_smoke.extract_output_text({"output_text": '{"estimated_reference_count": 1, "references": []}'})
        fallback = openai_batch_smoke.extract_output_text(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"estimated_reference_count": 2, "references": []}'}],
                    }
                ]
            }
        )

        self.assertEqual(direct, '{"estimated_reference_count": 1, "references": []}')
        self.assertEqual(fallback, '{"estimated_reference_count": 2, "references": []}')

    def test_run_batch_probe_reads_completed_output(self) -> None:
        class DummyTextResponse:
            def __init__(self, text: str) -> None:
                self.text = text

        class DummyFilesClient:
            def create(self, *, file, purpose):
                self.created_purpose = purpose
                return SimpleNamespace(id="file_in_1")

            def content(self, file_id: str):
                self.last_content_id = file_id
                return DummyTextResponse(
                    json.dumps(
                        {
                            "custom_id": "reference-split-smoke-1",
                            "response": {
                                "body": {
                                    "output_text": json.dumps(
                                        {
                                            "estimated_reference_count": 2,
                                            "references": [
                                                {"reference": "Ref A", "title": "Ref A", "doi": None},
                                                {"reference": "Ref B", "title": "Ref B", "doi": None},
                                            ],
                                        }
                                    )
                                }
                            },
                        }
                    )
                )

        class DummyBatchesClient:
            def create(self, **kwargs):
                self.create_kwargs = kwargs
                return SimpleNamespace(
                    id="batch_1",
                    status="completed",
                    output_file_id="file_out_1",
                    error_file_id=None,
                    request_counts=SimpleNamespace(total=1, completed=1, failed=0),
                )

            def retrieve(self, batch_id: str):
                raise AssertionError("retrieve should not be called for a completed batch")

        client = SimpleNamespace(files=DummyFilesClient(), batches=DummyBatchesClient())
        result = openai_batch_smoke.run_batch_probe(
            client,
            model="gpt-5-nano",
            reference_text="1. Smith A. Example title.",
            metadata_name="smoke",
            completion_window="24h",
            poll_seconds=0.01,
            max_wait_seconds=0.01,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["request_counts"]["completed"], 1)
        self.assertEqual(result["first_output"]["estimated_reference_count"], 2)


if __name__ == "__main__":
    unittest.main()

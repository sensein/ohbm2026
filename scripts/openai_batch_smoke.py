from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from openai import OpenAI

from ohbm2026.graphql_api import load_dotenv
from ohbm2026.openalex import (
    reference_split_response_schema,
    reference_split_system_prompt,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit a tiny OpenAI Batch API probe for reference splitting")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--api-var", default="OPENAI_API_KEY")
    parser.add_argument("--model", default="gpt-5-nano")
    parser.add_argument("--metadata-name", default="reference-split-batch-smoke")
    parser.add_argument("--window", default="24h")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--max-wait-seconds", type=float, default=60.0)
    parser.add_argument("--reference-text-file")
    parser.add_argument(
        "--reference-text",
        default=(
            "1. Cooper SR, Gonthier C, Barch DM, Braver TS. The Role of Psychometrics in Individual "
            "Differences Research in Cognition: A Case Study of the AX-CPT. Front Psychol. 2017;8. "
            "doi:10.3389/fpsyg.2017.01482\n\n"
            "2. Ceko M, Hirshfield L, Doherty E, Southwell R, D'Mello SK. Cortical cognitive processing "
            "during reading captured using functional-near infrared spectroscopy. Sci Rep. 2024;14(1):19483. "
            "doi:10.1038/s41598-024-69630-x"
        ),
    )
    return parser.parse_args()


def get_api_key(env_file: Path, api_var: str) -> str:
    env_values = load_dotenv(env_file)
    api_key = env_values.get(api_var)
    if not api_key:
        raise SystemExit(f"Missing {api_var} in {env_file}")
    return api_key


def load_reference_text(args: argparse.Namespace) -> str:
    if args.reference_text_file:
        return Path(args.reference_text_file).read_text(encoding="utf-8")
    return args.reference_text


def build_batch_request_body(model: str, reference_text: str) -> dict[str, object]:
    return {
        "model": model,
        "store": False,
        "reasoning": {"effort": "minimal"},
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": reference_split_system_prompt()}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": reference_text}],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "reference_split",
                "strict": True,
                "schema": reference_split_response_schema(),
            }
        },
    }


def build_batch_jsonl_line(model: str, reference_text: str, *, custom_id: str = "reference-split-smoke-1") -> str:
    payload = {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/responses",
        "body": build_batch_request_body(model, reference_text),
    }
    return json.dumps(payload, ensure_ascii=False)


def extract_output_text(response_body: dict[str, object]) -> str:
    output_text = response_body.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    for item in response_body.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text
    return ""


def run_batch_probe(
    client: OpenAI,
    *,
    model: str,
    reference_text: str,
    metadata_name: str,
    completion_window: str,
    poll_seconds: float,
    max_wait_seconds: float,
) -> dict[str, object]:
    started_at = time.perf_counter()
    with TemporaryDirectory() as temp_dir:
        batch_input_path = Path(temp_dir) / "reference_split_batch.jsonl"
        batch_input_path.write_text(
            build_batch_jsonl_line(model, reference_text) + "\n",
            encoding="utf-8",
        )
        with batch_input_path.open("rb") as handle:
            uploaded = client.files.create(file=handle, purpose="batch")
        batch = client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/responses",
            completion_window=completion_window,
            metadata={"name": metadata_name},
        )
        status_history = [getattr(batch, "status", None)]
        deadline = time.perf_counter() + max_wait_seconds
        current = batch
        while time.perf_counter() < deadline:
            if getattr(current, "status", None) in {"completed", "failed", "expired", "cancelled"}:
                break
            time.sleep(poll_seconds)
            current = client.batches.retrieve(batch.id)
            status_history.append(getattr(current, "status", None))

        result: dict[str, object] = {
            "upload_file_id": getattr(uploaded, "id", None),
            "batch_id": getattr(current, "id", None),
            "status": getattr(current, "status", None),
            "status_history": status_history,
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
            "request_counts": {
                "total": getattr(current, "request_counts", None).total if getattr(current, "request_counts", None) else None,
                "completed": getattr(current, "request_counts", None).completed if getattr(current, "request_counts", None) else None,
                "failed": getattr(current, "request_counts", None).failed if getattr(current, "request_counts", None) else None,
            },
        }
        output_file_id = getattr(current, "output_file_id", None)
        error_file_id = getattr(current, "error_file_id", None)
        result["output_file_id"] = output_file_id
        result["error_file_id"] = error_file_id
        if output_file_id:
            output_text = client.files.content(output_file_id).text
            output_lines = [json.loads(line) for line in output_text.splitlines() if line.strip()]
            result["output_line_count"] = len(output_lines)
            if output_lines:
                first_line = output_lines[0]
                response_body = first_line.get("response", {}).get("body", {})
                parsed_text = extract_output_text(response_body)
                result["first_output"] = json.loads(parsed_text) if parsed_text else None
        if error_file_id:
            result["error_file_preview"] = client.files.content(error_file_id).text[:1000]
        return result


def main() -> int:
    args = parse_args()
    api_key = get_api_key(Path(args.env_file), args.api_var)
    reference_text = load_reference_text(args)
    client = OpenAI(api_key=api_key, timeout=max(60.0, args.max_wait_seconds + 10.0))
    result = run_batch_probe(
        client,
        model=args.model,
        reference_text=reference_text,
        metadata_name=args.metadata_name,
        completion_window=args.window,
        poll_seconds=args.poll_seconds,
        max_wait_seconds=args.max_wait_seconds,
    )
    print(
        json.dumps(
            {
                "model": args.model,
                "poll_seconds": args.poll_seconds,
                "max_wait_seconds": args.max_wait_seconds,
                **result,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

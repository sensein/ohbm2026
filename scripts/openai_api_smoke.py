from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel

from ohbm2026.fetch.graphql_api import load_dotenv


class SmokeResponse(BaseModel):
    answer: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure OpenAI API latency for small smoke requests")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--api-var", default="OPENAI_API_KEY")
    parser.add_argument("--model", default="gpt-4o-2024-08-06")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--mode", choices=["responses", "chat-parse"], default="responses")
    parser.add_argument("--max-output-tokens", type=int, default=64)
    parser.add_argument("--reasoning-effort", choices=["minimal", "low", "medium", "high"], default=None)
    parser.add_argument(
        "--prompt",
        default="Reply with the single word pong.",
        help="Prompt to send for the smoke test.",
    )
    return parser.parse_args()


def get_api_key(env_file: Path, api_var: str) -> str:
    env_values = load_dotenv(env_file)
    api_key = env_values.get(api_var)
    if not api_key:
        raise SystemExit(f"Missing {api_var} in {env_file}")
    return api_key


def run_responses(
    client: OpenAI,
    model: str,
    prompt: str,
    max_output_tokens: int,
    reasoning_effort: str | None,
) -> dict[str, object]:
    started_at = time.perf_counter()
    kwargs: dict[str, object] = {
        "model": model,
        "input": prompt,
        "max_output_tokens": max_output_tokens,
    }
    if reasoning_effort:
        kwargs["reasoning"] = {"effort": reasoning_effort}
    response = client.responses.create(**kwargs)
    elapsed = time.perf_counter() - started_at
    output_text = getattr(response, "output_text", "")
    usage = getattr(response, "usage", None)
    return {
        "mode": "responses",
        "elapsed_seconds": round(elapsed, 3),
        "output_text": output_text.strip(),
        "response_id": getattr(response, "id", None),
        "usage": {
            "input_tokens": getattr(usage, "input_tokens", None) if usage else None,
            "output_tokens": getattr(usage, "output_tokens", None) if usage else None,
            "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
        },
    }


def run_chat_parse(
    client: OpenAI,
    model: str,
    prompt: str,
    max_output_tokens: int,
    reasoning_effort: str | None,
) -> dict[str, object]:
    started_at = time.perf_counter()
    kwargs: dict[str, object] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": SmokeResponse,
        "max_completion_tokens": max_output_tokens,
    }
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort
    completion = client.beta.chat.completions.parse(**kwargs)
    elapsed = time.perf_counter() - started_at
    parsed = completion.choices[0].message.parsed
    usage = getattr(completion, "usage", None)
    return {
        "mode": "chat-parse",
        "elapsed_seconds": round(elapsed, 3),
        "output_text": parsed.answer.strip() if parsed else "",
        "response_id": getattr(completion, "id", None),
        "usage": {
            "input_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
            "output_tokens": getattr(usage, "completion_tokens", None) if usage else None,
            "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
        },
    }


def main() -> int:
    args = parse_args()
    api_key = get_api_key(Path(args.env_file), args.api_var)
    client = OpenAI(api_key=api_key, timeout=args.timeout)

    if args.mode == "responses":
        result = run_responses(
            client,
            args.model,
            args.prompt,
            max_output_tokens=args.max_output_tokens,
            reasoning_effort=args.reasoning_effort,
        )
    else:
        result = run_chat_parse(
            client,
            args.model,
            args.prompt,
            max_output_tokens=args.max_output_tokens,
            reasoning_effort=args.reasoning_effort,
        )

    print(
        json.dumps(
            {
                "model": args.model,
                "timeout_seconds": args.timeout,
                "max_output_tokens": args.max_output_tokens,
                "reasoning_effort": args.reasoning_effort,
                **result,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

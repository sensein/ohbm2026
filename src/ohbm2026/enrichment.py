from __future__ import annotations

import argparse
import base64
import importlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ohbm2026 import artifacts
from ohbm2026.assets import extract_target_figure_urls
from ohbm2026.fetch.graphql_api import load_dotenv
from ohbm2026.titles import cleaned_abstract_title

SECTION_ORDER = [
    ("introduction", "Introduction"),
    ("methods", "Methods"),
    ("results", "Results"),
    ("discussion", "Discussion"),
    ("conclusion", "Conclusion"),
    ("references", "References"),
    ("acknowledgement", "Acknowledgement"),
]
CLAIM_SECTION_ORDER = [
    ("introduction", "Introduction"),
    ("methods", "Methods"),
    ("results", "Results"),
    ("discussion", "Discussion"),
    ("conclusion", "Conclusion"),
]
SECTION_MARKDOWN_KEYS = {section_key: f"{section_key}_markdown" for section_key, _ in SECTION_ORDER}
CONTENT_QUESTION_NAMES = {
    "Primary Parent Category & Sub-Category",
    "Secondary Parent Category & Sub-Category",
    "Keywords",
    "Which processing packages did you use for your study?",
    "For human MRI, what field strength scanner do you use?",
    'Please indicate below if your study was a "resting state" or "task-activation” study.',
    "Please indicate which methods were used in your research:",
    "Healthy subjects only or patients (note that patient studies may also involve healthy subjects).",
    "If other, please specify:",
    "If Other, please list the terms below. Multiple terms must be separated by semi-colons ( ; ).",
    "If yes:",
    "If other, please explain:",
}
NORMALIZED_CONTENT_QUESTION_NAMES = {normalize.lower() for normalize in CONTENT_QUESTION_NAMES}

OLLAMA_API = "http://127.0.0.1:11434/api"
DEFAULT_VISION_MODEL = "qwen3.5:35b"
DEFAULT_OPENAI_VISION_MODEL = "gpt-4.1-mini"
OPENAI_CHAT_API = "https://api.openai.com/v1/chat/completions"
DEFAULT_OPENAI_MAX_IMAGES_PER_REQUEST = 48
DEFAULT_OPENAI_MAX_REQUEST_BYTES = 40_000_000
DEFAULT_OPENAI_REQUEST_TIMEOUT_SECONDS = 600
DEFAULT_CLLM_PROVIDER = "openai"
DEFAULT_CLLM_OPENAI_MODEL = "gpt-4o-2024-08-06"
DEFAULT_CLLM_ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
DEFAULT_CLLM_OPENAI_MAX_COMPLETION_TOKENS = 4096
DEFAULT_CLLM_OPENAI_REASONING_EFFORT: str | None = None


class EnrichmentError(RuntimeError):
    """Raised when the enrichment pipeline cannot continue."""


@dataclass
class OllamaModelStatus:
    available: bool
    models: list[str]


def _cli_option_present(argv: list[str] | None, option: str) -> bool:
    return argv is not None and option in argv


def _database_input_digest(base_database: dict[str, Any]) -> str:
    abstract_ids = [abstract.get("id") for abstract in base_database.get("abstracts", []) if isinstance(abstract.get("id"), int)]
    return artifacts.build_state_key(
        {
            "event_ids": list(base_database.get("event_ids", [])),
            "abstract_ids": abstract_ids,
        }
    )


def default_image_analysis_cache_path(
    input_path: Path = artifacts.PRIMARY_ABSTRACTS_PATH,
    *,
    backend: str = "ollama",
    model: str | None = None,
    max_images: int | None = None,
) -> Path:
    resolved_model = model or (DEFAULT_OPENAI_VISION_MODEL if backend == "openai" else DEFAULT_VISION_MODEL)
    basis = artifacts.build_dependency_basis(
        input_sources=[str(input_path)],
        backend=backend,
        model=resolved_model,
        options={"max_images": max_images} if max_images is not None else None,
        env_boundary=["OPENAI_API_KEY"] if backend == "openai" else None,
    )
    return artifacts.build_cache_path("figure_analysis", f"image_analyses_{backend}", artifacts.build_state_key(basis))


def default_claim_analysis_cache_path(
    input_path: Path = artifacts.PRIMARY_ABSTRACTS_PATH,
    *,
    llm_provider: str = DEFAULT_CLLM_PROVIDER,
    model: str | None = None,
    max_abstracts: int | None = None,
) -> Path:
    resolved_model = model or (DEFAULT_CLLM_OPENAI_MODEL if llm_provider == "openai" else DEFAULT_CLLM_ANTHROPIC_MODEL)
    env_boundary = ["OPENAI_API_KEY"] if llm_provider == "openai" else ["ANTHROPIC_API_KEY"]
    basis = artifacts.build_dependency_basis(
        input_sources=[str(input_path)],
        backend=llm_provider,
        model=resolved_model,
        options={"max_abstracts": max_abstracts} if max_abstracts is not None else None,
        env_boundary=env_boundary,
    )
    return artifacts.build_cache_path("claim_analysis", "claim_analyses_cllm", artifacts.build_state_key(basis))


DEFAULT_CLAIM_ANALYSES_OUTPUT = str(default_claim_analysis_cache_path())


class HTMLToMarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.list_stack: list[dict[str, Any]] = []
        self.link_stack: list[str | None] = []
        self.format_stack: list[str] = []

    def _append(self, text: str) -> None:
        if text:
            self.parts.append(text)

    def _ensure_block_break(self) -> None:
        current = "".join(self.parts)
        if not current.endswith("\n\n"):
            if current.endswith("\n"):
                self.parts.append("\n")
            elif current:
                self.parts.append("\n\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag in {"p", "div"}:
            self._ensure_block_break()
        elif tag == "br":
            self._append("\n")
        elif tag in {"strong", "b"}:
            self._append("**")
            self.format_stack.append("**")
        elif tag in {"em", "i"}:
            self._append("_")
            self.format_stack.append("_")
        elif tag == "sup":
            self._append("^(")
            self.format_stack.append(")")
        elif tag == "ul":
            self.list_stack.append({"type": "ul", "index": 0})
            self._ensure_block_break()
        elif tag == "ol":
            self.list_stack.append({"type": "ol", "index": 1})
            self._ensure_block_break()
        elif tag == "li":
            self._append("\n")
            indent = "  " * max(len(self.list_stack) - 1, 0)
            if self.list_stack and self.list_stack[-1]["type"] == "ol":
                prefix = f"{self.list_stack[-1]['index']}. "
                self.list_stack[-1]["index"] += 1
            else:
                prefix = "- "
            self._append(indent + prefix)
        elif tag == "a":
            href = attr_map.get("href")
            self.link_stack.append(href)
            self._append("[")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div"}:
            self._ensure_block_break()
        elif tag in {"strong", "b", "em", "i", "sup"} and self.format_stack:
            self._append(self.format_stack.pop())
        elif tag in {"ul", "ol"}:
            if self.list_stack:
                self.list_stack.pop()
            self._ensure_block_break()
        elif tag == "a":
            href = self.link_stack.pop() if self.link_stack else None
            self._append(f"]({href})" if href else "]")

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data)
        if text.strip():
            self._append(text)

    def markdown(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def html_to_markdown(value: str | None) -> str:
    if not value:
        return ""
    if "<" not in value or ">" not in value:
        return value.strip()
    parser = HTMLToMarkdownParser()
    parser.feed(value)
    parser.close()
    return parser.markdown()


def normalize_question_name(question_name: str | None) -> str:
    return (question_name or "").strip().lower()


def question_to_section(question_name: str | None) -> str | None:
    normalized = normalize_question_name(question_name)
    if normalized == "title":
        return "title"
    if normalized.startswith("introduction"):
        return "introduction"
    if normalized.startswith("methods") and "figure" not in normalized:
        return "methods"
    if normalized.startswith("results") and "figure" not in normalized:
        return "results"
    if normalized.startswith("discussion"):
        return "discussion"
    if normalized.startswith("conclusion"):
        return "conclusion"
    if normalized.startswith("references"):
        return "references"
    if normalized.startswith("acknowledgement") or normalized.startswith("acknowledgment"):
        return "acknowledgement"
    return None


def parse_list_value(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return [raw_value.strip()] if raw_value.strip() else []
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    if isinstance(parsed, str) and parsed.strip():
        return [parsed.strip()]
    return []


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def build_sections_markdown(abstract: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, str]]]:
    sections: dict[str, list[str]] = {key: [] for key, _ in SECTION_ORDER}
    unmapped: list[dict[str, str]] = []
    for response_index, response in enumerate(abstract.get("responses", [])):
        value = response.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        section_key = question_to_section(response.get("question_name"))
        markdown = html_to_markdown(value)
        if not markdown:
            continue
        if section_key is None:
            unmapped.append(
                {
                    "question_name": response.get("question_name") or "",
                    "markdown": markdown,
                    "response_index": response_index,
                }
            )
        elif section_key != "title":
            sections[section_key].append(markdown)

    return {key: "\n\n".join(values).strip() for key, values in sections.items() if values}, unmapped


def is_content_question(question_name: str | None) -> bool:
    if not question_name:
        return False
    normalized = normalize_question_name(question_name)
    if normalized in NORMALIZED_CONTENT_QUESTION_NAMES:
        return True
    return False


def build_section_markdown_fields(sections_markdown: dict[str, str]) -> dict[str, str]:
    return {
        SECTION_MARKDOWN_KEYS[section_key]: value
        for section_key, value in sections_markdown.items()
        if section_key in SECTION_MARKDOWN_KEYS and value
    }


def content_question_sort_key(item: dict[str, str]) -> tuple[int, str]:
    response_index = item.get("response_index")
    if isinstance(response_index, int):
        return (response_index, str(item.get("question_name") or ""))
    return (10_000, str(item.get("question_name") or ""))


def filter_content_questions_markdown(items: list[dict[str, str]]) -> list[dict[str, str]]:
    filtered = [
        item
        for item in items
        if is_content_question(item.get("question_name")) and item.get("markdown")
    ]
    ordered = sorted(filtered, key=content_question_sort_key)
    return [
        {
            "question_name": str(item.get("question_name") or ""),
            "markdown": str(item.get("markdown") or "").strip(),
        }
        for item in ordered
    ]


def figure_analysis_sort_key(entry: dict[str, Any]) -> tuple[int, str, str]:
    question_name = str(entry.get("question_name") or entry.get("source_question_name") or "").strip()
    normalized = normalize_question_name(question_name)
    if "methods" in normalized and "figure" in normalized:
        group = 0
    elif "results" in normalized and "figure" in normalized:
        group = 1
    else:
        group = 2
    return (
        group,
        question_name,
        str(entry.get("local_path") or ""),
    )


def sort_figure_analysis_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(list(entries), key=figure_analysis_sort_key)


def render_abstract_markdown(title: str, sections_markdown: dict[str, str]) -> str:
    parts = [f"# {title}"] if title else []
    for section_key, heading in SECTION_ORDER:
        section_value = sections_markdown.get(section_key)
        if section_value:
            parts.append(f"## {heading}\n\n{section_value}")
    return "\n\n".join(parts).strip()


def render_claim_section_markdown(title: str, sections_markdown: dict[str, str]) -> str:
    parts = [f"# {title}"] if title else []
    for section_key, heading in CLAIM_SECTION_ORDER:
        section_value = sections_markdown.get(section_key)
        if section_value:
            parts.append(f"## {heading}\n\n{section_value}")
    return "\n\n".join(parts).strip()


def render_additional_content_questions_markdown(items: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for item in items:
        question_name = str(item.get("question_name") or "").strip()
        markdown = str(item.get("markdown") or "").strip()
        if not markdown:
            continue
        if question_name:
            parts.append(f"### {question_name}\n\n{markdown}")
        else:
            parts.append(markdown)
    return "\n\n".join(parts).strip()


def render_figure_analyses_markdown(figure_analyses: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for index, entry in enumerate(sort_figure_analysis_entries(figure_analyses), start=1):
        analysis = entry.get("analysis") if isinstance(entry, dict) else {}
        if not isinstance(analysis, dict):
            analysis = {}
        subsection_parts: list[str] = []
        label = str(entry.get("question_name") or "").strip() if isinstance(entry, dict) else ""
        heading = label or f"Figure {index}"
        caption_guess = str(analysis.get("caption_guess") or "").strip()
        rich_markdown = str(analysis.get("rich_markdown") or "").strip()
        ocr_text = str(analysis.get("ocr_text") or "").strip()
        notes = str(analysis.get("notes") or "").strip()
        if caption_guess:
            subsection_parts.append(f"**Caption guess:** {caption_guess}")
        if rich_markdown:
            subsection_parts.append(rich_markdown)
        if ocr_text:
            subsection_parts.append(f"**OCR text:** {ocr_text}")
        if notes:
            subsection_parts.append(f"**Notes:** {notes}")
        if subsection_parts:
            parts.append(f"### {heading}\n\n" + "\n\n".join(subsection_parts))
    return "\n\n".join(parts).strip()


def build_claim_manuscript_markdown(
    title: str,
    sections_markdown: dict[str, str],
    additional_content_questions: list[dict[str, str]],
    figure_analyses: list[dict[str, Any]] | None = None,
) -> str:
    parts: list[str] = []
    abstract_markdown = render_claim_section_markdown(title, sections_markdown)
    if abstract_markdown:
        parts.append(abstract_markdown)
    elif title:
        parts.append(f"# {title}")
    figure_markdown = render_figure_analyses_markdown(list(figure_analyses or []))
    if figure_markdown:
        parts.append(f"## Figure Analyses\n\n{figure_markdown}")
    additional_content_markdown = render_additional_content_questions_markdown(additional_content_questions)
    if additional_content_markdown:
        parts.append(f"## Additional Content\n\n{additional_content_markdown}")
    manuscript = "\n\n".join(part for part in parts if part).strip()
    return manuscript or (title.strip() if title else "Untitled abstract")


def load_image_analysis_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"analyses": {}, "model": None, "updated_at": None}
    return load_json(path)


def save_image_analysis_cache(path: Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json(path, payload)


def load_claim_analysis_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"analyses": {}, "updated_at": None}
    return load_json(path)


def save_claim_analysis_cache(path: Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json(path, payload)


def _update_cache_metadata(
    cache: dict[str, Any],
    *,
    workflow: str,
    artifact_name: str,
    dependency_basis: dict[str, Any],
    status: str,
) -> None:
    cache["artifact_metadata"] = artifacts.build_artifact_metadata(
        workflow=workflow,
        artifact_name=artifact_name,
        artifact_class="cache",
        state_key=artifacts.build_state_key(dependency_basis),
        dependency_basis=dependency_basis,
        status=status,
        producer=f"ohbm2026.{workflow}",
    )


def analysis_entry_succeeded(entry: dict[str, Any] | None) -> bool:
    if not isinstance(entry, dict):
        return False
    analysis = entry.get("analysis")
    return isinstance(analysis, dict) and bool(analysis)


def claim_analysis_entry_completed(entry: dict[str, Any] | None) -> bool:
    return isinstance(entry, dict) and entry.get("status") == "ok"


def refresh_analysis_cache_stats(cache: dict[str, Any]) -> None:
    analyses = cache.get("analyses") or {}
    cache["processed_count"] = len(analyses)
    cache["error_count"] = sum(1 for entry in analyses.values() if isinstance(entry, dict) and entry.get("error"))


def refresh_claim_analysis_cache_stats(cache: dict[str, Any]) -> None:
    analyses = cache.get("analyses") or {}
    cache["processed_count"] = len(analyses)
    cache["completed_count"] = sum(
        1 for entry in analyses.values() if isinstance(entry, dict) and entry.get("status") == "ok"
    )
    cache["error_count"] = sum(
        1 for entry in analyses.values() if isinstance(entry, dict) and entry.get("status") == "error"
    )


def image_to_data_url(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    direct_mime_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    mime_type = direct_mime_types.get(suffix)
    if mime_type:
        image_bytes = image_path.read_bytes()
        return f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    if suffix in {".tif", ".tiff"}:
        try:
            from PIL import Image
        except ImportError as exc:
            raise EnrichmentError(f"TIFF figure requires Pillow conversion: {image_path}") from exc
        with Image.open(image_path) as image:
            converted = BytesIO()
            image.save(converted, format="PNG")
        return f"data:image/png;base64,{base64.b64encode(converted.getvalue()).decode('ascii')}"
    raise EnrichmentError(f"Unsupported local image format for OpenAI vision: {image_path.suffix or '<none>'}")


def estimate_openai_payload_bytes(data_url: str) -> int:
    # Include some structural JSON headroom so batches stay under the effective payload cap.
    return len(data_url.encode("utf-8")) + 2048


def ollama_model_status(model: str) -> OllamaModelStatus:
    completed = subprocess.run(["ollama", "list"], check=True, capture_output=True, text=True)
    models = [line.split()[0] for line in completed.stdout.splitlines()[1:] if line.strip()]
    return OllamaModelStatus(available=model in models, models=models)


def ensure_ollama_model(model: str, pull_if_missing: bool = False) -> None:
    status = ollama_model_status(model)
    if status.available:
        return
    if not pull_if_missing:
        raise EnrichmentError(
            f"Ollama model '{model}' is not available locally. Existing models: {', '.join(status.models)}"
        )
    subprocess.run(["ollama", "pull", model], check=True)


def parse_jsonish_content(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, flags=re.DOTALL)
        if fenced_match:
            return json.loads(fenced_match.group(1))
        object_match = re.search(r"(\{.*\})", content, flags=re.DOTALL)
        if object_match:
            return json.loads(object_match.group(1))
        raise exc


def ollama_chat_multimodal(model: str, prompt: str, image_path: Path) -> dict[str, Any]:
    request_payload = json.dumps(
        {
            "model": model,
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [base64.b64encode(image_path.read_bytes()).decode("ascii")],
                }
            ],
        }
    ).encode("utf-8")
    request = Request(
        f"{OLLAMA_API}/chat",
        data=request_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=600) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload.get("message", {}).get("content", "")
    try:
        return parse_jsonish_content(content)
    except json.JSONDecodeError as exc:
        raise EnrichmentError(f"Ollama response was not valid JSON for {image_path}") from exc


def openai_chat_multimodal(
    model: str,
    prompt: str,
    image_path: Path,
    api_key: str,
) -> dict[str, Any]:
    data_url = image_to_data_url(image_path)
    request_payload = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url,
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
        }
    ).encode("utf-8")
    request = Request(
        OPENAI_CHAT_API,
        data=request_payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=DEFAULT_OPENAI_REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise EnrichmentError(f"OpenAI vision request failed with HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise EnrichmentError(f"OpenAI vision request failed: {exc.reason}") from exc
    content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    try:
        return parse_jsonish_content(content)
    except json.JSONDecodeError as exc:
        raise EnrichmentError(f"OpenAI response was not valid JSON for {image_path}") from exc


def normalize_openai_batch_response(
    payload: dict[str, Any] | list[Any],
    batch_assets: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if isinstance(payload, dict):
        items = payload.get("images")
        if items is None and all(key in payload for key in ("caption_guess", "rich_markdown", "ocr_text", "keywords", "notes")):
            items = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        raise EnrichmentError("OpenAI batch response was not a JSON object or array")

    if not isinstance(items, list):
        raise EnrichmentError("OpenAI batch response did not include an 'images' array")

    assets_by_key = {asset["cache_key"]: asset for asset in batch_assets}
    assets_by_index = {index: asset for index, asset in enumerate(batch_assets, start=1)}
    normalized: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        cache_key = str(item.get("local_path") or "").strip()
        if cache_key and cache_key in assets_by_key:
            target_asset = assets_by_key[cache_key]
        else:
            input_index = item.get("input_index")
            try:
                target_asset = assets_by_index[int(input_index)]
            except (TypeError, ValueError, KeyError):
                continue
        normalized[target_asset["cache_key"]] = {
            "caption_guess": str(item.get("caption_guess") or "").strip(),
            "rich_markdown": str(item.get("rich_markdown") or "").strip(),
            "ocr_text": str(item.get("ocr_text") or "").strip(),
            "keywords": [str(keyword).strip() for keyword in (item.get("keywords") or []) if str(keyword).strip()],
            "notes": str(item.get("notes") or "").strip(),
        }
    return normalized


def openai_chat_multimodal_batch(
    model: str,
    prompt: str,
    batch_assets: list[dict[str, Any]],
    api_key: str,
    timeout_seconds: int = DEFAULT_OPENAI_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"{prompt} "
                "You will receive multiple figures. Return strict JSON with key 'images', "
                "an array the same length and order as the inputs. Each item must contain: "
                "input_index (1-based integer), local_path (string exactly matching the identifier), "
                "caption_guess (string), rich_markdown (string), ocr_text (string), "
                "keywords (array of short strings), notes (string)."
            ),
        }
    ]
    for index, asset in enumerate(batch_assets, start=1):
        content.append(
            {
                "type": "text",
                "text": f"Image {index} identifier: {asset['cache_key']}",
            }
        )
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": asset["data_url"],
                    "detail": "high",
                },
            }
        )

    request_payload = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": content,
                }
            ],
        }
    ).encode("utf-8")
    request = Request(
        OPENAI_CHAT_API,
        data=request_payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise EnrichmentError(f"OpenAI vision batch request failed with HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise EnrichmentError(f"OpenAI vision batch request failed: {exc.reason}") from exc

    content_payload = response_payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    if isinstance(content_payload, list):
        content_payload = "".join(part.get("text", "") for part in content_payload if isinstance(part, dict))
    try:
        parsed = parse_jsonish_content(content_payload)
    except json.JSONDecodeError as exc:
        raise EnrichmentError("OpenAI batch response was not valid JSON") from exc

    normalized = normalize_openai_batch_response(parsed, batch_assets)
    if len(normalized) != len(batch_assets):
        missing = [asset["cache_key"] for asset in batch_assets if asset["cache_key"] not in normalized]
        raise EnrichmentError(f"OpenAI batch response missing analyses for {len(missing)} images")
    return normalized


def iter_openai_batch_assets(
    candidate_assets: list[tuple[Path, Any, Any]],
    analyses: dict[str, Any],
    max_images: int | None,
    max_images_per_request: int,
    max_request_bytes: int,
) -> Any:
    current: list[dict[str, Any]] = []
    current_bytes = 0
    pending_count = 0

    for image_path, question_name, abstract_id in candidate_assets:
        cache_key = str(image_path)
        if analysis_entry_succeeded(analyses.get(cache_key)):
            continue
        if max_images is not None and pending_count >= max_images:
            break
        try:
            data_url = image_to_data_url(image_path)
            estimated_bytes = estimate_openai_payload_bytes(data_url)
            prep_error = None
        except Exception as exc:
            data_url = ""
            estimated_bytes = 0
            prep_error = str(exc)
        asset = {
            "image_path": image_path,
            "question_name": question_name,
            "abstract_id": abstract_id,
            "cache_key": cache_key,
            "data_url": data_url,
            "estimated_bytes": estimated_bytes,
            "prep_error": prep_error,
        }

        if prep_error:
            if current:
                yield current
                current = []
                current_bytes = 0
            yield [asset]
            pending_count += 1
            continue

        if estimated_bytes > max_request_bytes:
            if current:
                yield current
                current = []
                current_bytes = 0
            yield [asset]
            pending_count += 1
            continue

        would_overflow = (
            current
            and (
                len(current) >= max(max_images_per_request, 1)
                or current_bytes + estimated_bytes > max_request_bytes
            )
        )
        if would_overflow:
            yield current
            current = []
            current_bytes = 0

        current.append(asset)
        current_bytes += estimated_bytes
        pending_count += 1

    if current:
        yield current


def resolve_openai_api_key(env_file: Path, api_var: str) -> str:
    env_values = load_dotenv(env_file)
    api_key = env_values.get(api_var)
    if not api_key:
        raise EnrichmentError(f"Missing OpenAI API key '{api_var}' in {env_file}")
    return api_key


def build_cllm_environment(
    env_file: Path,
    llm_provider: str,
    openai_api_var: str,
    openai_model: str,
    anthropic_api_var: str,
    anthropic_model: str,
) -> dict[str, str]:
    env_values = load_dotenv(env_file)
    environment = os.environ.copy()
    environment["LLM_PROVIDER"] = llm_provider
    if llm_provider == "openai":
        api_key = os.environ.get(openai_api_var) or env_values.get(openai_api_var)
        if not api_key:
            raise EnrichmentError(f"Missing OpenAI API key '{openai_api_var}' in {env_file}")
        environment["OPENAI_API_KEY"] = api_key
        environment["OPENAI_MODEL"] = openai_model
    elif llm_provider == "anthropic":
        api_key = os.environ.get(anthropic_api_var) or env_values.get(anthropic_api_var)
        if not api_key:
            raise EnrichmentError(f"Missing Anthropic API key '{anthropic_api_var}' in {env_file}")
        environment["ANTHROPIC_API_KEY"] = api_key
        environment["ANTHROPIC_MODEL"] = anthropic_model
    else:
        raise EnrichmentError(f"Unsupported cllm provider: {llm_provider}")
    return environment


def load_cllm_verification_module(environment: dict[str, str]) -> Any:
    for key in ("LLM_PROVIDER", "OPENAI_API_KEY", "OPENAI_MODEL", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"):
        if key in environment:
            os.environ[key] = environment[key]
    try:
        import cllm.config as cllm_config
        import cllm.verification as cllm_verification
    except ModuleNotFoundError as exc:
        raise EnrichmentError(
            "cllm is not installed in the current environment. "
            "Install it with: UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python "
            "git+https://github.com/OpenEvalProject/cllm.git"
        ) from exc
    importlib.reload(cllm_config)
    return importlib.reload(cllm_verification)


def extract_claims_from_cllm_module(
    manuscript_text: str,
    cllm_verification: Any,
    llm_provider: str,
    openai_max_completion_tokens: int,
    openai_reasoning_effort: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prompt = cllm_verification.STAGE1_PROMPT_TEMPLATE.replace("$MANUSCRIPT_TEXT", manuscript_text)
    cllm_verification.warn_if_prompt_too_long(
        prompt,
        cllm_verification.MAX_PROMPT_TOKENS,
        "STAGE 1: Extract Claims From Manuscript",
    )
    start_time = time.time()
    if llm_provider == "openai":
        client = cllm_verification.get_llm_client()
        request_kwargs: dict[str, Any] = {
            "model": cllm_verification.config.openai_model,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            "response_format": cllm_verification.LLMClaimsResponseV3,
            "max_completion_tokens": openai_max_completion_tokens,
        }
        if openai_reasoning_effort:
            request_kwargs["reasoning_effort"] = openai_reasoning_effort
        completion = client.beta.chat.completions.parse(**request_kwargs)
        response = completion.choices[0].message.parsed
        if response is None:
            raise EnrichmentError(
                f"OpenAI returned no parsed response. Refusal: {completion.choices[0].message.refusal}"
            )
        usage = {
            "input_tokens": completion.usage.prompt_tokens,
            "output_tokens": completion.usage.completion_tokens,
        }
    else:
        client = cllm_verification.get_llm_client()
        response, usage, _ = cllm_verification.call_llm_structured(
            client=client,
            prompt=prompt,
            response_model=cllm_verification.LLMClaimsResponseV3,
            max_tokens=64_000,
        )
    claims = [
        {
            "claim_id": f"C{index}",
            "claim": claim.claim,
            "claim_type": claim.claim_type,
            "source": claim.source,
            "source_type": list(claim.source_type or []),
            "evidence": claim.evidence,
            "evidence_type": list(claim.evidence_type or []),
        }
        for index, claim in enumerate(response.claims, start=1)
    ]
    model_name = (
        cllm_verification.config.openai_model
        if llm_provider == "openai"
        else cllm_verification.config.anthropic_model
    )
    metrics = {
        "model": model_name,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "num_claims": len(claims),
        "processing_time_seconds": time.time() - start_time,
    }
    return claims, metrics


def extract_claims_with_cllm(
    base_database: dict[str, Any],
    cache_path: Path,
    image_analysis_cache: dict[str, Any] | None = None,
    env_file: Path = Path(".env"),
    llm_provider: str = DEFAULT_CLLM_PROVIDER,
    openai_api_var: str = "OPENAI_API_KEY",
    openai_model: str = DEFAULT_CLLM_OPENAI_MODEL,
    anthropic_api_var: str = "ANTHROPIC_API_KEY",
    anthropic_model: str = DEFAULT_CLLM_ANTHROPIC_MODEL,
    openai_max_completion_tokens: int = DEFAULT_CLLM_OPENAI_MAX_COMPLETION_TOKENS,
    openai_reasoning_effort: str = DEFAULT_CLLM_OPENAI_REASONING_EFFORT,
    max_abstracts: int | None = None,
    save_every: int = 1,
    force: bool = False,
) -> dict[str, Any]:
    image_analysis_cache = image_analysis_cache or {"analyses": {}}
    image_lookup = image_analysis_cache.get("analyses", {})
    environment = build_cllm_environment(
        env_file=env_file,
        llm_provider=llm_provider,
        openai_api_var=openai_api_var,
        openai_model=openai_model,
        anthropic_api_var=anthropic_api_var,
        anthropic_model=anthropic_model,
    )
    cache = load_claim_analysis_cache(cache_path)
    analyses = cache.setdefault("analyses", {})
    refresh_claim_analysis_cache_stats(cache)
    processed = 0
    selected_model = openai_model if llm_provider == "openai" else anthropic_model
    dependency_basis = artifacts.build_dependency_basis(
        input_digest=_database_input_digest(base_database),
        backend=llm_provider,
        model=selected_model,
        options={"max_abstracts": max_abstracts, "force": force},
        env_boundary=["OPENAI_API_KEY"] if llm_provider == "openai" else ["ANTHROPIC_API_KEY"],
    )
    cllm_verification = load_cllm_verification_module(environment)

    def persist_progress() -> None:
        refresh_claim_analysis_cache_stats(cache)
        if processed % max(save_every, 1) == 0:
            cache["backend"] = "cllm"
            cache["llm_provider"] = llm_provider
            cache["llm_model"] = selected_model
            _update_cache_metadata(
                cache,
                workflow="claim_analysis",
                artifact_name="claim_analyses_cllm",
                dependency_basis=dependency_basis,
                status="running",
            )
            save_claim_analysis_cache(cache_path, cache)

    for abstract in base_database.get("abstracts", []):
        abstract_id = abstract.get("id")
        if not isinstance(abstract_id, int):
            continue
        cache_key = str(abstract_id)
        if not force and claim_analysis_entry_completed(analyses.get(cache_key)):
            continue
        if max_abstracts is not None and processed >= max_abstracts:
            break

        sections_markdown, unmapped_responses = build_sections_markdown(abstract)
        additional_content_questions = filter_content_questions_markdown(unmapped_responses)
        figure_analyses: list[dict[str, Any]] = []
        for asset in abstract.get("local_assets", []):
            local_path = asset.get("local_path")
            analysis_entry = image_lookup.get(local_path) if local_path else None
            if analysis_entry:
                figure_analyses.append(analysis_entry)
        manuscript_markdown = build_claim_manuscript_markdown(
            title=cleaned_abstract_title(abstract.get("title")),
            sections_markdown=sections_markdown,
            additional_content_questions=additional_content_questions,
            figure_analyses=sort_figure_analysis_entries(figure_analyses),
        )

        entry: dict[str, Any] = {
            "abstract_id": abstract_id,
            "title": cleaned_abstract_title(abstract.get("title")),
            "backend": "cllm",
            "llm_provider": llm_provider,
            "llm_model": selected_model,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            claims, metrics = extract_claims_from_cllm_module(
                manuscript_text=manuscript_markdown,
                cllm_verification=cllm_verification,
                llm_provider=llm_provider,
                openai_max_completion_tokens=openai_max_completion_tokens,
                openai_reasoning_effort=openai_reasoning_effort,
            )
        except Exception as exc:
            entry.update(
                {
                    "status": "error",
                    "claims": [],
                    "claim_count": 0,
                    "error": str(exc),
                }
            )
        else:
            entry.update(
                {
                    "status": "ok",
                    "claims": claims,
                    "claim_count": len(claims),
                    "metrics": metrics,
                    "llm_model": str(metrics.get("model") or selected_model),
                }
            )
        analyses[cache_key] = entry

        processed += 1
        persist_progress()

    cache["backend"] = "cllm"
    cache["llm_provider"] = llm_provider
    cache["llm_model"] = selected_model
    refresh_claim_analysis_cache_stats(cache)
    _update_cache_metadata(
        cache,
        workflow="claim_analysis",
        artifact_name="claim_analyses_cllm",
        dependency_basis=dependency_basis,
        status="ready",
    )
    save_claim_analysis_cache(cache_path, cache)
    return cache


def analyze_figures(
    base_database: dict[str, Any],
    analysis_cache_path: Path,
    backend: str = "ollama",
    model: str = DEFAULT_VISION_MODEL,
    openai_api_key: str | None = None,
    pull_model_if_missing: bool = False,
    max_images: int | None = None,
    save_every: int = 1,
    enriched_output_path: Path | None = None,
    enrich_every: int = 25,
    openai_max_images_per_request: int = DEFAULT_OPENAI_MAX_IMAGES_PER_REQUEST,
    openai_max_request_bytes: int = DEFAULT_OPENAI_MAX_REQUEST_BYTES,
    openai_request_timeout_seconds: int = DEFAULT_OPENAI_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if backend == "ollama":
        ensure_ollama_model(model, pull_if_missing=pull_model_if_missing)
    elif backend == "openai":
        if not openai_api_key:
            raise EnrichmentError("openai_api_key is required when backend='openai'")
    else:
        raise EnrichmentError(f"Unsupported vision backend: {backend}")
    cache = load_image_analysis_cache(analysis_cache_path)
    analyses = cache.setdefault("analyses", {})
    refresh_analysis_cache_stats(cache)
    dependency_basis = artifacts.build_dependency_basis(
        input_digest=_database_input_digest(base_database),
        backend=backend,
        model=model,
        options={"max_images": max_images, "enrich_every": enrich_every},
        env_boundary=["OPENAI_API_KEY"] if backend == "openai" else None,
    )
    prompt = (
        "Analyze this scientific figure and return strict JSON with keys: "
        "caption_guess (string), rich_markdown (string), ocr_text (string), "
        "keywords (array of short strings), notes (string)."
    )

    candidate_assets = []
    for abstract in base_database.get("abstracts", []):
        for asset in abstract.get("local_assets", []):
            local_path = asset.get("local_path")
            if local_path:
                candidate_assets.append((Path(local_path), asset.get("source_question_name"), abstract["id"]))

    processed = 0

    def persist_progress() -> None:
        refresh_analysis_cache_stats(cache)
        if processed % max(save_every, 1) == 0:
            cache["model"] = model
            cache["backend"] = backend
            _update_cache_metadata(
                cache,
                workflow="figure_analysis",
                artifact_name=f"image_analyses_{backend}",
                dependency_basis=dependency_basis,
                status="running",
            )
            save_image_analysis_cache(analysis_cache_path, cache)
        if enriched_output_path is not None and processed % max(enrich_every, 1) == 0:
            write_json(enriched_output_path, enrich_database(base_database, cache))

    def store_analysis_entry(asset: dict[str, Any], analysis: dict[str, Any] | None = None, error: str | None = None) -> None:
        nonlocal processed
        analyses[asset["cache_key"]] = {
            "abstract_id": asset["abstract_id"],
            "question_name": asset["question_name"],
            "local_path": asset["cache_key"],
            "model": model,
            "backend": backend,
            "analysis": analysis or {},
        }
        if error:
            analyses[asset["cache_key"]]["error"] = error
        processed += 1
        persist_progress()

    def process_openai_batch(batch_assets: list[dict[str, Any]]) -> None:
        if not batch_assets:
            return
        if len(batch_assets) == 1 and batch_assets[0].get("prep_error"):
            store_analysis_entry(batch_assets[0], error=str(batch_assets[0]["prep_error"]))
            return
        try:
            batch_results = openai_chat_multimodal_batch(
                model,
                prompt,
                batch_assets,
                openai_api_key or "",
                timeout_seconds=openai_request_timeout_seconds,
            )
        except Exception as exc:
            if len(batch_assets) == 1:
                store_analysis_entry(batch_assets[0], error=str(exc))
                return
            midpoint = max(1, len(batch_assets) // 2)
            process_openai_batch(batch_assets[:midpoint])
            process_openai_batch(batch_assets[midpoint:])
            return

        for asset in batch_assets:
            store_analysis_entry(asset, analysis=batch_results[asset["cache_key"]])

    if backend == "openai":
        for batch_assets in iter_openai_batch_assets(
            candidate_assets,
            analyses,
            max_images=max_images,
            max_images_per_request=openai_max_images_per_request,
            max_request_bytes=openai_max_request_bytes,
        ):
            process_openai_batch(batch_assets)
    else:
        for image_path, question_name, abstract_id in candidate_assets:
            cache_key = str(image_path)
            if analysis_entry_succeeded(analyses.get(cache_key)):
                continue
            try:
                analysis = ollama_chat_multimodal(model, prompt, image_path)
                analyses[cache_key] = {
                    "abstract_id": abstract_id,
                    "question_name": question_name,
                    "local_path": cache_key,
                    "model": model,
                    "backend": backend,
                    "analysis": analysis,
                }
            except Exception as exc:
                analyses[cache_key] = {
                    "abstract_id": abstract_id,
                    "question_name": question_name,
                    "local_path": cache_key,
                    "model": model,
                    "backend": backend,
                    "analysis": {},
                    "error": str(exc),
                }
            processed += 1
            persist_progress()
            if max_images is not None and processed >= max_images:
                break

    cache["model"] = model
    cache["backend"] = backend
    refresh_analysis_cache_stats(cache)
    _update_cache_metadata(
        cache,
        workflow="figure_analysis",
        artifact_name=f"image_analyses_{backend}",
        dependency_basis=dependency_basis,
        status="ready",
    )
    save_image_analysis_cache(analysis_cache_path, cache)
    if enriched_output_path is not None:
        write_json(enriched_output_path, enrich_database(base_database, cache))
    return cache


def extract_original_keywords(abstract: dict[str, Any]) -> list[str]:
    for response in abstract.get("responses", []):
        if normalize_question_name(response.get("question_name")) == "keywords":
            if isinstance(response.get("value"), str):
                return parse_list_value(response["value"])
    return []


def enrich_database(
    base_database: dict[str, Any],
    image_analysis_cache: dict[str, Any] | None = None,
    claim_analysis_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    image_analysis_cache = image_analysis_cache or {"analyses": {}}
    image_lookup = image_analysis_cache.get("analyses", {})
    claim_analysis_cache = claim_analysis_cache or {"analyses": {}}
    claim_lookup = claim_analysis_cache.get("analyses", {})
    enriched_abstracts: list[dict[str, Any]] = []

    for abstract in base_database.get("abstracts", []):
        sections_markdown, unmapped_responses = build_sections_markdown(abstract)
        section_fields = build_section_markdown_fields(sections_markdown)
        additional_content_questions = filter_content_questions_markdown(unmapped_responses)
        original_keywords = extract_original_keywords(abstract)
        figure_analyses = []
        figure_keywords: list[str] = []
        for asset in abstract.get("local_assets", []):
            local_path = asset.get("local_path")
            analysis_entry = image_lookup.get(local_path) if local_path else None
            if analysis_entry:
                figure_analyses.append(analysis_entry)
                figure_keywords.extend(analysis_entry.get("analysis", {}).get("keywords", []))
        figure_analyses = sort_figure_analysis_entries(figure_analyses)
        claim_entry = claim_lookup.get(str(abstract.get("id")))
        claim_extraction = None
        if isinstance(claim_entry, dict):
            claim_extraction = {
                "status": claim_entry.get("status") or "unknown",
                "backend": claim_entry.get("backend") or "cllm",
                "llm_provider": claim_entry.get("llm_provider") or "",
                "llm_model": claim_entry.get("llm_model") or "",
                "claim_count": int(claim_entry.get("claim_count") or len(claim_entry.get("claims") or [])),
                "claims": list(claim_entry.get("claims") or []),
                "metrics": claim_entry.get("metrics") or {},
                "error": str(claim_entry.get("error") or "").strip(),
                "updated_at": claim_entry.get("updated_at"),
            }

        enriched = {
            "id": abstract.get("id"),
            "accepted_for": abstract.get("accepted_for"),
            **section_fields,
            "additional_content_questions_markdown": additional_content_questions,
            "figure_analyses": figure_analyses,
            "figure_keywords": unique_preserve_order(figure_keywords),
        }
        if claim_extraction is not None:
            enriched["claim_extraction"] = claim_extraction
        enriched_abstracts.append(enriched)

    return {
        "enriched_at": datetime.now(timezone.utc).isoformat(),
        "abstract_count": len(enriched_abstracts),
        "event_ids": base_database.get("event_ids", []),
        "abstracts": enriched_abstracts,
    }


def build_enrich_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build enriched OHBM 2026 abstracts from local databases")
    parser.add_argument("--input", default=str(artifacts.PRIMARY_ABSTRACTS_PATH))
    parser.add_argument("--image-analyses-input", default=str(default_image_analysis_cache_path(backend="openai")))
    parser.add_argument("--claim-analyses-input", default=DEFAULT_CLAIM_ANALYSES_OUTPUT)
    parser.add_argument("--enriched-output", default=str(artifacts.PRIMARY_ENRICHED_ABSTRACTS_PATH))
    return parser


def parse_enrich_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_enrich_parser().parse_args(argv)


def enrich_main(argv: list[str] | None = None) -> int:
    args = parse_enrich_args(argv)
    base_database = load_json(Path(args.input))
    image_cache = load_image_analysis_cache(Path(args.image_analyses_input))
    claim_cache = load_claim_analysis_cache(Path(args.claim_analyses_input))
    enriched_database = enrich_database(base_database, image_cache, claim_analysis_cache=claim_cache)
    write_json(Path(args.enriched_output), enriched_database)
    print(
        json.dumps(
            {
                "input": args.input,
                "image_analyses_input": args.image_analyses_input,
                "claim_analyses_input": args.claim_analyses_input,
                "enriched_output": args.enriched_output,
                "abstract_count": enriched_database["abstract_count"],
            },
            indent=2,
        )
    )
    return 0


def build_claim_extraction_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract claim lists for OHBM 2026 abstracts with cllm")
    parser.add_argument("--input", default=str(artifacts.PRIMARY_ABSTRACTS_PATH))
    parser.add_argument("--image-analyses-input", default=str(default_image_analysis_cache_path(backend="openai")))
    parser.add_argument("--claim-analyses-output", default=DEFAULT_CLAIM_ANALYSES_OUTPUT)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--llm-provider", choices=["openai", "anthropic"], default=DEFAULT_CLLM_PROVIDER)
    parser.add_argument("--openai-api-var", default="OPENAI_API_KEY")
    parser.add_argument("--openai-model", default=DEFAULT_CLLM_OPENAI_MODEL)
    parser.add_argument("--openai-max-completion-tokens", type=int, default=DEFAULT_CLLM_OPENAI_MAX_COMPLETION_TOKENS)
    parser.add_argument(
        "--openai-reasoning-effort",
        choices=["minimal", "low", "medium", "high"],
        default=DEFAULT_CLLM_OPENAI_REASONING_EFFORT,
    )
    parser.add_argument("--anthropic-api-var", default="ANTHROPIC_API_KEY")
    parser.add_argument("--anthropic-model", default=DEFAULT_CLLM_ANTHROPIC_MODEL)
    parser.add_argument("--max-abstracts", type=int, default=None)
    parser.add_argument("--save-every", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    return parser


def parse_claim_extraction_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_claim_extraction_parser().parse_args(argv)


def extract_claims_main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else None
    args = parse_claim_extraction_args(argv)
    input_path = Path(args.input)
    image_analyses_input = (
        Path(args.image_analyses_input)
        if _cli_option_present(raw_argv, "--image-analyses-input")
        else default_image_analysis_cache_path(input_path, backend="openai")
    )
    claim_analyses_output = (
        Path(args.claim_analyses_output)
        if _cli_option_present(raw_argv, "--claim-analyses-output")
        else default_claim_analysis_cache_path(
            input_path,
            llm_provider=args.llm_provider,
            model=args.openai_model if args.llm_provider == "openai" else args.anthropic_model,
            max_abstracts=args.max_abstracts,
        )
    )
    base_database = load_json(input_path)
    image_cache = load_image_analysis_cache(image_analyses_input)
    claim_cache = extract_claims_with_cllm(
        base_database=base_database,
        cache_path=claim_analyses_output,
        image_analysis_cache=image_cache,
        env_file=Path(args.env_file),
        llm_provider=args.llm_provider,
        openai_api_var=args.openai_api_var,
        openai_model=args.openai_model,
        anthropic_api_var=args.anthropic_api_var,
        anthropic_model=args.anthropic_model,
        openai_max_completion_tokens=args.openai_max_completion_tokens,
        openai_reasoning_effort=args.openai_reasoning_effort,
        max_abstracts=args.max_abstracts,
        save_every=args.save_every,
        force=args.force,
    )
    print(
        json.dumps(
            {
                "input": args.input,
                "image_analyses_input": str(image_analyses_input),
                "claim_analyses_output": str(claim_analyses_output),
                "llm_provider": args.llm_provider,
                "llm_model": args.openai_model if args.llm_provider == "openai" else args.anthropic_model,
                "processed_count": claim_cache.get("processed_count", 0),
                "completed_count": claim_cache.get("completed_count", 0),
                "error_count": claim_cache.get("error_count", 0),
            },
            indent=2,
        )
    )
    return 0


def build_figure_analysis_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze local OHBM 2026 figure assets with Ollama")
    parser.add_argument("--input", default=str(artifacts.PRIMARY_ABSTRACTS_PATH))
    parser.add_argument("--image-analyses-output", default=str(default_image_analysis_cache_path()))
    parser.add_argument("--vision-backend", choices=["ollama", "openai"], default="ollama")
    parser.add_argument("--vision-model", default=DEFAULT_VISION_MODEL)
    parser.add_argument("--openai-model", default=DEFAULT_OPENAI_VISION_MODEL)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--openai-api-var", default="OPENAI_API_KEY")
    parser.add_argument("--vision-max-images", type=int, default=None)
    parser.add_argument("--openai-max-images-per-request", type=int, default=DEFAULT_OPENAI_MAX_IMAGES_PER_REQUEST)
    parser.add_argument("--openai-max-request-bytes", type=int, default=DEFAULT_OPENAI_MAX_REQUEST_BYTES)
    parser.add_argument("--openai-request-timeout-seconds", type=int, default=DEFAULT_OPENAI_REQUEST_TIMEOUT_SECONDS)
    parser.add_argument("--pull-missing-vision-model", action="store_true")
    parser.add_argument("--save-every", type=int, default=1)
    parser.add_argument("--enriched-output", default=None)
    parser.add_argument("--enrich-every", type=int, default=25)
    return parser


def parse_figure_analysis_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_figure_analysis_parser().parse_args(argv)


def analyze_figures_main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else None
    args = parse_figure_analysis_args(argv)
    input_path = Path(args.input)
    base_database = load_json(input_path)
    model = args.vision_model if args.vision_backend == "ollama" else args.openai_model
    image_analyses_output = (
        Path(args.image_analyses_output)
        if _cli_option_present(raw_argv, "--image-analyses-output")
        else default_image_analysis_cache_path(
            input_path,
            backend=args.vision_backend,
            model=model,
            max_images=args.vision_max_images,
        )
    )
    openai_api_key = (
        resolve_openai_api_key(Path(args.env_file), args.openai_api_var)
        if args.vision_backend == "openai"
        else None
    )
    image_cache = analyze_figures(
        base_database,
        image_analyses_output,
        backend=args.vision_backend,
        model=model,
        openai_api_key=openai_api_key,
        pull_model_if_missing=args.pull_missing_vision_model,
        max_images=args.vision_max_images,
        save_every=args.save_every,
        enriched_output_path=Path(args.enriched_output) if args.enriched_output else None,
        enrich_every=args.enrich_every,
        openai_max_images_per_request=args.openai_max_images_per_request,
        openai_max_request_bytes=args.openai_max_request_bytes,
        openai_request_timeout_seconds=args.openai_request_timeout_seconds,
    )
    print(
        json.dumps(
            {
                "input": args.input,
                "image_analyses_output": str(image_analyses_output),
                "vision_backend": args.vision_backend,
                "vision_model": model,
                "analysis_count": len(image_cache.get("analyses", {})),
                "enriched_output": args.enriched_output,
            },
            indent=2,
        )
    )
    return 0

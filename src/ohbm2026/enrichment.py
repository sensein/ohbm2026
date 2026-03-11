from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ohbm2026.assets import extract_target_figure_urls
from ohbm2026.graphql_api import fetch_author_details, get_api_key, load_dotenv

SECTION_ORDER = [
    ("introduction", "Introduction"),
    ("methods", "Methods"),
    ("results", "Results"),
    ("discussion", "Discussion"),
    ("conclusion", "Conclusion"),
    ("references", "References"),
    ("acknowledgement", "Acknowledgement"),
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


class EnrichmentError(RuntimeError):
    """Raised when the enrichment pipeline cannot continue."""


@dataclass
class OllamaModelStatus:
    available: bool
    models: list[str]


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


def extract_author_ids(database: dict[str, Any]) -> list[int]:
    author_ids = {
        author["id"]
        for abstract in database.get("abstracts", [])
        for author in abstract.get("authors", [])
        if isinstance(author.get("id"), int)
    }
    return sorted(author_ids)


def build_author_database(base_database: dict[str, Any], api_key: str) -> dict[str, Any]:
    author_ids = extract_author_ids(base_database)
    authors = fetch_author_details(api_key, author_ids)
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "author_count": len(authors),
        "authors": authors,
    }


def build_sections_markdown(abstract: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, str]]]:
    sections: dict[str, list[str]] = {key: [] for key, _ in SECTION_ORDER}
    unmapped: list[dict[str, str]] = []
    for response in abstract.get("responses", []):
        value = response.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        section_key = question_to_section(response.get("question_name"))
        markdown = html_to_markdown(value)
        if not markdown:
            continue
        if section_key is None:
            unmapped.append({"question_name": response.get("question_name") or "", "markdown": markdown})
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
    question_name = str(item.get("question_name") or "")
    normalized = normalize_question_name(question_name)
    if normalized == normalize_question_name("Which processing packages did you use for your study?"):
        return (100, question_name)
    if normalized == normalize_question_name("If other, please specify:"):
        return (101, question_name)
    return (0, question_name)


def filter_content_questions_markdown(items: list[dict[str, str]]) -> list[dict[str, str]]:
    filtered = [
        item
        for item in items
        if is_content_question(item.get("question_name")) and item.get("markdown")
    ]
    return sorted(filtered, key=content_question_sort_key)


def render_abstract_markdown(title: str, sections_markdown: dict[str, str]) -> str:
    parts = [f"# {title}"] if title else []
    for section_key, heading in SECTION_ORDER:
        section_value = sections_markdown.get(section_key)
        if section_value:
            parts.append(f"## {heading}\n\n{section_value}")
    return "\n\n".join(parts).strip()


def load_image_analysis_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"analyses": {}, "model": None, "updated_at": None}
    return load_json(path)


def save_image_analysis_cache(path: Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json(path, payload)


def analysis_entry_succeeded(entry: dict[str, Any] | None) -> bool:
    if not isinstance(entry, dict):
        return False
    analysis = entry.get("analysis")
    return isinstance(analysis, dict) and bool(analysis)


def refresh_analysis_cache_stats(cache: dict[str, Any]) -> None:
    analyses = cache.get("analyses") or {}
    cache["processed_count"] = len(analyses)
    cache["error_count"] = sum(1 for entry in analyses.values() if isinstance(entry, dict) and entry.get("error"))


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
    image_bytes = image_path.read_bytes()
    data_url = f"data:image/{image_path.suffix.lstrip('.') or 'png'};base64,{base64.b64encode(image_bytes).decode('ascii')}"
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
        with urlopen(request, timeout=600) as response:
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


def resolve_openai_api_key(env_file: Path, api_var: str) -> str:
    env_values = load_dotenv(env_file)
    api_key = env_values.get(api_var)
    if not api_key:
        raise EnrichmentError(f"Missing OpenAI API key '{api_var}' in {env_file}")
    return api_key


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
    errors = 0
    for image_path, question_name, abstract_id in candidate_assets:
        cache_key = str(image_path)
        if analysis_entry_succeeded(analyses.get(cache_key)):
            continue
        try:
            if backend == "ollama":
                analysis = ollama_chat_multimodal(model, prompt, image_path)
            else:
                analysis = openai_chat_multimodal(model, prompt, image_path, openai_api_key or "")
            analyses[cache_key] = {
                "abstract_id": abstract_id,
                "question_name": question_name,
                "local_path": cache_key,
                "model": model,
                "backend": backend,
                "analysis": analysis,
            }
        except Exception as exc:
            errors += 1
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
        refresh_analysis_cache_stats(cache)
        if processed % max(save_every, 1) == 0:
            cache["model"] = model
            cache["backend"] = backend
            save_image_analysis_cache(analysis_cache_path, cache)
        if enriched_output_path is not None and processed % max(enrich_every, 1) == 0:
            write_json(enriched_output_path, enrich_database(base_database, cache))
        if max_images is not None and processed >= max_images:
            break

    cache["model"] = model
    cache["backend"] = backend
    refresh_analysis_cache_stats(cache)
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
) -> dict[str, Any]:
    image_analysis_cache = image_analysis_cache or {"analyses": {}}
    image_lookup = image_analysis_cache.get("analyses", {})
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

        enriched = {
            "id": abstract.get("id"),
            "accepted_for": abstract.get("accepted_for"),
            **section_fields,
            "additional_content_questions_markdown": additional_content_questions,
            "figure_analyses": figure_analyses,
            "figure_keywords": unique_preserve_order(figure_keywords),
        }
        enriched_abstracts.append(enriched)

    return {
        "enriched_at": datetime.now(timezone.utc).isoformat(),
        "abstract_count": len(enriched_abstracts),
        "event_ids": base_database.get("event_ids", []),
        "abstracts": enriched_abstracts,
    }


def build_authors_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export author metadata for OHBM 2026 abstracts")
    parser.add_argument("--input", default="data/abstracts.json")
    parser.add_argument("--authors-output", default="data/authors.json")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--ohbm-api-var", default="OHBM2026_API")
    return parser


def parse_authors_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_authors_parser().parse_args(argv)


def authors_main(argv: list[str] | None = None) -> int:
    args = parse_authors_args(argv)
    base_database = load_json(Path(args.input))
    author_database = build_author_database(base_database, get_api_key(Path(args.env_file), args.ohbm_api_var))
    write_json(Path(args.authors_output), author_database)
    print(
        json.dumps(
            {
                "input": args.input,
                "authors_output": args.authors_output,
                "author_count": author_database["author_count"],
            },
            indent=2,
        )
    )
    return 0


def build_enrich_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build enriched OHBM 2026 abstracts from local databases")
    parser.add_argument("--input", default="data/abstracts.json")
    parser.add_argument("--image-analyses-input", default="data/image_analyses.json")
    parser.add_argument("--enriched-output", default="data/abstracts_enriched.json")
    return parser


def parse_enrich_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_enrich_parser().parse_args(argv)


def enrich_main(argv: list[str] | None = None) -> int:
    args = parse_enrich_args(argv)
    base_database = load_json(Path(args.input))
    image_cache = load_image_analysis_cache(Path(args.image_analyses_input))
    enriched_database = enrich_database(base_database, image_cache)
    write_json(Path(args.enriched_output), enriched_database)
    print(
        json.dumps(
            {
                "input": args.input,
                "image_analyses_input": args.image_analyses_input,
                "enriched_output": args.enriched_output,
                "abstract_count": enriched_database["abstract_count"],
            },
            indent=2,
        )
    )
    return 0


def build_figure_analysis_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze local OHBM 2026 figure assets with Ollama")
    parser.add_argument("--input", default="data/abstracts.json")
    parser.add_argument("--image-analyses-output", default="data/image_analyses.json")
    parser.add_argument("--vision-backend", choices=["ollama", "openai"], default="ollama")
    parser.add_argument("--vision-model", default=DEFAULT_VISION_MODEL)
    parser.add_argument("--openai-model", default=DEFAULT_OPENAI_VISION_MODEL)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--openai-api-var", default="OPENAI_API_KEY")
    parser.add_argument("--vision-max-images", type=int, default=None)
    parser.add_argument("--pull-missing-vision-model", action="store_true")
    parser.add_argument("--save-every", type=int, default=1)
    parser.add_argument("--enriched-output", default=None)
    parser.add_argument("--enrich-every", type=int, default=25)
    return parser


def parse_figure_analysis_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_figure_analysis_parser().parse_args(argv)


def analyze_figures_main(argv: list[str] | None = None) -> int:
    args = parse_figure_analysis_args(argv)
    base_database = load_json(Path(args.input))
    model = args.vision_model if args.vision_backend == "ollama" else args.openai_model
    openai_api_key = (
        resolve_openai_api_key(Path(args.env_file), args.openai_api_var)
        if args.vision_backend == "openai"
        else None
    )
    image_cache = analyze_figures(
        base_database,
        Path(args.image_analyses_output),
        backend=args.vision_backend,
        model=model,
        openai_api_key=openai_api_key,
        pull_model_if_missing=args.pull_missing_vision_model,
        max_images=args.vision_max_images,
        save_every=args.save_every,
        enriched_output_path=Path(args.enriched_output) if args.enriched_output else None,
        enrich_every=args.enrich_every,
    )
    print(
        json.dumps(
            {
                "input": args.input,
                "image_analyses_output": args.image_analyses_output,
                "vision_backend": args.vision_backend,
                "vision_model": model,
                "analysis_count": len(image_cache.get("analyses", {})),
                "enriched_output": args.enriched_output,
            },
            indent=2,
        )
    )
    return 0

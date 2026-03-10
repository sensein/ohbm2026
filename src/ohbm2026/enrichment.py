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
from urllib.request import Request, urlopen

from ohbm2026.assets import extract_target_figure_urls
from ohbm2026.graphql_api import fetch_author_details, get_api_key

SECTION_ORDER = [
    ("introduction", "Introduction"),
    ("methods", "Methods"),
    ("results", "Results"),
    ("discussion", "Discussion"),
    ("conclusion", "Conclusion"),
    ("references", "References"),
    ("acknowledgement", "Acknowledgement"),
]

OLLAMA_API = "http://127.0.0.1:11434/api"
DEFAULT_VISION_MODEL = "qwen3.5:35b"


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


def build_author_lookup(author_database: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {author["id"]: author for author in author_database.get("authors", [])}


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


def analyze_figures(
    enriched_database: dict[str, Any],
    analysis_cache_path: Path,
    model: str = DEFAULT_VISION_MODEL,
    pull_model_if_missing: bool = False,
    max_images: int | None = None,
) -> dict[str, Any]:
    ensure_ollama_model(model, pull_if_missing=pull_model_if_missing)
    cache = load_image_analysis_cache(analysis_cache_path)
    analyses = cache.setdefault("analyses", {})
    prompt = (
        "Analyze this scientific figure and return strict JSON with keys: "
        "caption_guess (string), rich_markdown (string), ocr_text (string), "
        "keywords (array of short strings), notes (string)."
    )

    candidate_assets = []
    for abstract in enriched_database.get("abstracts", []):
        for asset in abstract.get("local_assets", []):
            local_path = asset.get("local_path")
            if local_path:
                candidate_assets.append((Path(local_path), asset.get("source_question_name"), abstract["id"]))

    processed = 0
    for image_path, question_name, abstract_id in candidate_assets:
        cache_key = str(image_path)
        if cache_key in analyses:
            continue
        analyses[cache_key] = {
            "abstract_id": abstract_id,
            "question_name": question_name,
            "local_path": cache_key,
            "model": model,
            "analysis": ollama_chat_multimodal(model, prompt, image_path),
        }
        processed += 1
        if processed % 5 == 0:
            cache["model"] = model
            save_image_analysis_cache(analysis_cache_path, cache)
        if max_images is not None and processed >= max_images:
            break

    cache["model"] = model
    save_image_analysis_cache(analysis_cache_path, cache)
    return cache


def extract_original_keywords(abstract: dict[str, Any]) -> list[str]:
    for response in abstract.get("responses", []):
        if normalize_question_name(response.get("question_name")) == "keywords":
            if isinstance(response.get("value"), str):
                return parse_list_value(response["value"])
    return []


def build_embedding_text(abstract: dict[str, Any]) -> str:
    parts = [abstract.get("title", "").strip()]
    for section_key, heading in SECTION_ORDER:
        section_text = abstract.get("sections_markdown", {}).get(section_key)
        if section_text:
            parts.append(f"{heading}:\n{section_text}")
    keywords = abstract.get("generated_keywords", [])
    if keywords:
        parts.append("Keywords: " + ", ".join(keywords))
    return "\n\n".join(part for part in parts if part).strip()


def enrich_database(
    base_database: dict[str, Any],
    author_database: dict[str, Any],
    image_analysis_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    author_lookup = build_author_lookup(author_database)
    image_analysis_cache = image_analysis_cache or {"analyses": {}}
    image_lookup = image_analysis_cache.get("analyses", {})
    enriched_abstracts: list[dict[str, Any]] = []

    for abstract in base_database.get("abstracts", []):
        sections_markdown, unmapped_responses = build_sections_markdown(abstract)
        original_keywords = extract_original_keywords(abstract)
        figure_analyses = []
        figure_keywords: list[str] = []
        for asset in abstract.get("local_assets", []):
            local_path = asset.get("local_path")
            analysis_entry = image_lookup.get(local_path) if local_path else None
            if analysis_entry:
                figure_analyses.append(analysis_entry)
                figure_keywords.extend(analysis_entry.get("analysis", {}).get("keywords", []))

        enriched = dict(abstract)
        enriched["figure_urls"] = extract_target_figure_urls(abstract.get("responses", []))
        enriched["authors_resolved"] = [
            author_lookup.get(author["id"], {"id": author["id"]})
            for author in abstract.get("authors", [])
        ]
        enriched["sections_markdown"] = sections_markdown
        enriched["abstract_markdown"] = render_abstract_markdown(abstract.get("title", ""), sections_markdown)
        enriched["unmapped_responses_markdown"] = unmapped_responses
        enriched["original_keywords"] = original_keywords
        enriched["figure_analyses"] = figure_analyses
        enriched["figure_keywords"] = unique_preserve_order(figure_keywords)
        enriched["generated_keywords"] = unique_preserve_order(original_keywords + figure_keywords)
        enriched["embedding_text"] = build_embedding_text(enriched)
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
    parser.add_argument("--authors-input", default="data/authors.json")
    parser.add_argument("--image-analyses-input", default="data/image_analyses.json")
    parser.add_argument("--enriched-output", default="data/abstracts_enriched.json")
    return parser


def parse_enrich_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_enrich_parser().parse_args(argv)


def enrich_main(argv: list[str] | None = None) -> int:
    args = parse_enrich_args(argv)
    base_database = load_json(Path(args.input))
    author_database = load_json(Path(args.authors_input))
    image_cache = load_image_analysis_cache(Path(args.image_analyses_input))
    enriched_database = enrich_database(base_database, author_database, image_cache)
    write_json(Path(args.enriched_output), enriched_database)
    print(
        json.dumps(
            {
                "input": args.input,
                "authors_input": args.authors_input,
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
    parser.add_argument("--input", default="data/abstracts_enriched.json")
    parser.add_argument("--image-analyses-output", default="data/image_analyses.json")
    parser.add_argument("--vision-model", default=DEFAULT_VISION_MODEL)
    parser.add_argument("--vision-max-images", type=int, default=None)
    parser.add_argument("--pull-missing-vision-model", action="store_true")
    return parser


def parse_figure_analysis_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_figure_analysis_parser().parse_args(argv)


def analyze_figures_main(argv: list[str] | None = None) -> int:
    args = parse_figure_analysis_args(argv)
    enriched_database = load_json(Path(args.input))
    image_cache = analyze_figures(
        enriched_database,
        Path(args.image_analyses_output),
        model=args.vision_model,
        pull_model_if_missing=args.pull_missing_vision_model,
        max_images=args.vision_max_images,
    )
    print(
        json.dumps(
            {
                "input": args.input,
                "image_analyses_output": args.image_analyses_output,
                "vision_model": args.vision_model,
                "analysis_count": len(image_cache.get("analyses", {})),
            },
            indent=2,
        )
    )
    return 0

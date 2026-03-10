from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ohbm2026.graphql_api import chunked

DEFAULT_VOYAGE_MODEL = "voyage-large-2-instruct"
DEFAULT_MINILM_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class NeuroScapeError(RuntimeError):
    """Raised when embedding or relationship generation fails."""


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def voyage_embed(
    texts: list[str],
    api_key: str,
    model: str = DEFAULT_VOYAGE_MODEL,
    batch_size: int = 64,
) -> list[list[float]]:
    endpoint = "https://api.voyageai.com/v1/embeddings"
    vectors: list[list[float]] = []
    for text_batch in chunked(list(range(len(texts))), batch_size):
        batch_inputs = [texts[index] for index in text_batch]
        payload = json.dumps(
            {"input": batch_inputs, "model": model, "input_type": "document"}
        ).encode("utf-8")
        request = Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=600) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise NeuroScapeError(f"Voyage embeddings failed with HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise NeuroScapeError(f"Voyage embeddings failed: {exc.reason}") from exc
        vectors.extend(item["embedding"] for item in parsed.get("data", []))
    return vectors


def minilm_embed(texts: list[str], model_name: str = DEFAULT_MINILM_MODEL) -> list[list[float]]:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    embeddings = model.encode(
        texts,
        batch_size=64,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=False,
    )
    return embeddings.tolist()


def write_embedding_bundle(
    output_dir: Path,
    embedding_name: str,
    model_name: str,
    abstracts: list[dict[str, Any]],
    vectors: list[list[float]],
) -> dict[str, Any]:
    import numpy as np

    output_dir.mkdir(parents=True, exist_ok=True)
    matrix = np.asarray(vectors, dtype=np.float32)
    ids = [abstract["id"] for abstract in abstracts]
    metadata = [
        {"id": abstract["id"], "title": abstract.get("title"), "accepted_for": abstract.get("accepted_for")}
        for abstract in abstracts
    ]
    np.save(output_dir / "vectors.npy", matrix)
    write_json(
        output_dir / "metadata.json",
        {
            "embedding_name": embedding_name,
            "model_name": model_name,
            "count": len(metadata),
            "metadata": metadata,
            "ids": ids,
        },
    )
    return {"ids": ids, "matrix": matrix, "metadata": metadata}


def compute_neighbors(ids: list[int], matrix: Any, top_k: int = 10) -> dict[str, Any]:
    import numpy as np

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalized = matrix / norms
    similarities = normalized @ normalized.T
    neighbors: dict[str, list[dict[str, float]]] = {}
    for index, abstract_id in enumerate(ids):
        row = similarities[index].copy()
        row[index] = -1.0
        neighbor_indices = np.argsort(row)[-top_k:][::-1]
        neighbors[str(abstract_id)] = [
            {"id": int(ids[neighbor_index]), "score": float(row[neighbor_index])}
            for neighbor_index in neighbor_indices
        ]
    return {"top_k": top_k, "neighbors": neighbors}


def write_neuroscape_manifest(output_path: Path) -> None:
    write_json(
        output_path,
        {
            "status": "stage1_ready_stage2_pending_validation",
            "base_embedding_model": DEFAULT_VOYAGE_MODEL,
            "local_stage1_model": DEFAULT_MINILM_MODEL,
            "zenodo_record": "https://zenodo.org/records/14865161",
            "repository": "https://github.com/ccnmaastricht/NeuroScape",
            "note": (
                "The published NeuroScape domain model depends on Voyage stage-one embeddings "
                "and still requires the Zenodo artifact download before stage-two projection can run. "
                "A local-retraining path using a local stage-one model should be treated as a separate "
                "track until validated against the NeuroScape training workflow."
            ),
        },
    )


def load_embedding_inputs(path: Path) -> list[dict[str, Any]]:
    database = json.loads(path.read_text(encoding="utf-8"))
    return database.get("abstracts", [])


def build_minilm_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate local MiniLM embeddings for OHBM 2026 abstracts")
    parser.add_argument("--input", default="data/abstracts_enriched.json")
    parser.add_argument("--embeddings-dir", default="data/embeddings")
    parser.add_argument("--minilm-model", default=DEFAULT_MINILM_MODEL)
    return parser


def minilm_main(argv: list[str] | None = None) -> int:
    args = build_minilm_parser().parse_args(argv)
    abstracts = load_embedding_inputs(Path(args.input))
    embedding_texts = [abstract.get("embedding_text", "") for abstract in abstracts]
    output_dir = Path(args.embeddings_dir) / "minilm_stage1"
    vectors = minilm_embed(embedding_texts, model_name=args.minilm_model)
    bundle = write_embedding_bundle(output_dir, "minilm_stage1", args.minilm_model, abstracts, vectors)
    write_json(output_dir / "neighbors.json", compute_neighbors(bundle["ids"], bundle["matrix"]))
    print(
        json.dumps(
            {
                "input": args.input,
                "embeddings_dir": str(output_dir),
                "model_name": args.minilm_model,
                "abstract_count": len(abstracts),
            },
            indent=2,
        )
    )
    return 0


def build_voyage_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Voyage embeddings for OHBM 2026 abstracts")
    parser.add_argument("--input", default="data/abstracts_enriched.json")
    parser.add_argument("--embeddings-dir", default="data/embeddings")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--voyage-api-var", default="VOYAGE_API")
    parser.add_argument("--voyage-model", default=DEFAULT_VOYAGE_MODEL)
    return parser


def voyage_main(argv: list[str] | None = None) -> int:
    from ohbm2026.graphql_api import get_api_key

    args = build_voyage_parser().parse_args(argv)
    abstracts = load_embedding_inputs(Path(args.input))
    embedding_texts = [abstract.get("embedding_text", "") for abstract in abstracts]
    output_dir = Path(args.embeddings_dir) / "voyage_stage1"
    vectors = voyage_embed(
        embedding_texts,
        get_api_key(Path(args.env_file), args.voyage_api_var),
        model=args.voyage_model,
    )
    bundle = write_embedding_bundle(output_dir, "voyage_stage1", args.voyage_model, abstracts, vectors)
    write_json(output_dir / "neighbors.json", compute_neighbors(bundle["ids"], bundle["matrix"]))
    print(
        json.dumps(
            {
                "input": args.input,
                "embeddings_dir": str(output_dir),
                "model_name": args.voyage_model,
                "abstract_count": len(abstracts),
            },
            indent=2,
        )
    )
    return 0


def build_manifest_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write the NeuroScape handoff manifest for OHBM 2026 embeddings")
    parser.add_argument("--output", default="data/embeddings/neuroscape_stage2_manifest.json")
    return parser


def manifest_main(argv: list[str] | None = None) -> int:
    args = build_manifest_parser().parse_args(argv)
    write_neuroscape_manifest(Path(args.output))
    print(json.dumps({"output": args.output}, indent=2))
    return 0

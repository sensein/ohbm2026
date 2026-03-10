from __future__ import annotations

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

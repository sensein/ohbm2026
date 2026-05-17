"""Stage 3 NeuroScape Stage-2 model surface.

Canonical Stage 3 home for the NeuroScape Stage-2 transformer
(model architecture, checkpoint loader, applier, training entry-
points, plus the bundle helpers Stage 3 needs). This file replaces
the old re-export façade — the implementations now live here
physically instead of inside `analyze.py`.

Surfaces:

- Constants (`PUBLISHED_STAGE2_HIDDEN_DIMENSIONS`,
  `PUBLISHED_STAGE2_OUTPUT_DIMENSION`,
  `DEFAULT_STAGE2_HIDDEN_DIMENSIONS`,
  `DEFAULT_STAGE2_OUTPUT_DIMENSION`).
- Device + hyperparameter helpers (`choose_torch_device`,
  `normalize_hidden_dimensions`).
- Architecture + training
  (`build_stage2_network`, `split_stage2_matrix`,
  `dimension_correlation`, `compute_stage2_losses`,
  `evaluate_stage2_model`, `train_stage2_model`).
- Application + checkpoint I/O
  (`apply_stage2_model`, `load_pretrained_stage2_model`,
  `write_stage2_bundle`, `write_pretrained_stage2_bundle`).
- CLI surface (`stage2_main`, `apply_pretrained_stage2_main`,
  `manifest_main`).
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from ohbm2026 import artifacts
from ohbm2026.analyze.storage import (
    DEFAULT_EMBEDDING_FIELDS,
    NeuroScapeError,
    compute_neighbors,
    load_embedding_bundle,
    load_embedding_inputs,
    load_stage1_bundle,
    model_name_slug,
    parse_string_list_value,
    unique_strings,
    write_embedding_bundle,
    write_json,
)

DEFAULT_STAGE2_OUTPUT_DIMENSION = 64
DEFAULT_STAGE2_HIDDEN_DIMENSIONS = (192, 96, 64)
PUBLISHED_STAGE2_HIDDEN_DIMENSIONS = (512, 256, 128)
PUBLISHED_STAGE2_OUTPUT_DIMENSION = 64


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


def normalize_hidden_dimensions(values: list[int] | tuple[int, ...]) -> tuple[int, int, int]:
    dimensions = tuple(int(value) for value in values)
    if len(dimensions) != 3 or any(value <= 0 for value in dimensions):
        raise NeuroScapeError("Stage-2 hidden dimensions must contain exactly three positive integers")
    return dimensions


def choose_torch_device(requested: str | None = None) -> str:
    import torch

    if requested:
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def split_stage2_matrix(
    matrix: Any, validation_size: float = 0.05, seed: int = 42
) -> tuple[Any, Any]:
    import numpy as np

    if not 0 < validation_size < 1:
        raise NeuroScapeError("validation_size must be between 0 and 1")
    if matrix.shape[0] < 20:
        raise NeuroScapeError("Stage-2 training requires at least 20 stage-1 vectors")

    indices = np.arange(matrix.shape[0])
    rng = np.random.default_rng(seed)
    rng.shuffle(indices)

    validation_count = max(1, int(round(matrix.shape[0] * validation_size)))
    train_indices = indices[validation_count:]
    validation_indices = indices[:validation_count]
    return matrix[train_indices].copy(), matrix[validation_indices].copy()


def build_stage2_network(
    input_dimension: int,
    hidden_dimensions: tuple[int, int, int] = DEFAULT_STAGE2_HIDDEN_DIMENSIONS,
    output_dimension: int = DEFAULT_STAGE2_OUTPUT_DIMENSION,
    dropout: float = 0.1,
) -> Any:
    import torch.nn as nn
    import torch.nn.functional as F

    class Network(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.first_stage = nn.Sequential(
                nn.Linear(input_dimension, hidden_dimensions[0]),
                nn.BatchNorm1d(hidden_dimensions[0]),
                nn.ELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dimensions[0], hidden_dimensions[1]),
                nn.ELU(),
            )
            self.second_stage = nn.Sequential(
                nn.Linear(hidden_dimensions[1], hidden_dimensions[2]),
                nn.BatchNorm1d(hidden_dimensions[2]),
                nn.ELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dimensions[2], output_dimension),
            )

        def forward(self, x: Any) -> Any:
            first_state = self.first_stage(x)
            second_state = self.second_stage(first_state)
            return F.normalize(second_state, p=2, dim=1)

    return Network()


def dimension_correlation(projected: Any) -> Any:
    import torch

    if projected.shape[0] < 2 or projected.shape[1] < 2:
        return torch.zeros((), dtype=projected.dtype, device=projected.device)
    corr_matrix = torch.corrcoef(projected.T)
    return torch.mean(torch.abs(torch.triu(corr_matrix, diagonal=1)))


def compute_stage2_losses(
    model: Any,
    batch: Any,
    temperature: float,
    cutoff_values: tuple[float, float],
    correlation_weight: float = 0.0,
) -> tuple[Any, Any, Any]:
    import torch

    positive_cutoff, negative_cutoff = cutoff_values
    projected = model(batch)
    source_similarity = torch.matmul(batch, batch.T)
    target_similarity = torch.matmul(projected, projected.T)
    positives_mask = source_similarity >= positive_cutoff
    positives_mask = positives_mask & ~torch.eye(batch.shape[0], dtype=torch.bool, device=batch.device)
    negatives_mask = source_similarity <= negative_cutoff

    positive_logsum = torch.logsumexp(target_similarity * positives_mask.float() / temperature, dim=1)
    negative_logsum = torch.logsumexp(target_similarity * negatives_mask.float() / temperature, dim=1)
    info_nce_loss = (-positive_logsum + negative_logsum).mean()
    correlation_loss = correlation_weight * dimension_correlation(projected)
    return info_nce_loss + correlation_loss, info_nce_loss, correlation_loss


def evaluate_stage2_model(
    model: Any,
    validation_tensor: Any,
    temperature: float,
    cutoff_values: tuple[float, float],
) -> float:
    import torch

    with torch.no_grad():
        _, info_nce_loss, _ = compute_stage2_losses(
            model,
            validation_tensor,
            temperature=temperature,
            cutoff_values=cutoff_values,
            correlation_weight=0.0,
        )
    return float(info_nce_loss.item())


def train_stage2_model(
    matrix: Any,
    hidden_dimensions: tuple[int, int, int] = DEFAULT_STAGE2_HIDDEN_DIMENSIONS,
    output_dimension: int = DEFAULT_STAGE2_OUTPUT_DIMENSION,
    dropout: float = 0.1,
    epochs: int = 120,
    batch_size: int = 256,
    validation_size: float = 0.05,
    initial_learning_rate: float = 1e-4,
    minimum_learning_rate: float = 1e-5,
    temperature: float = 0.1,
    cutoff_values: tuple[float, float] = (0.85, 0.75),
    correlation_weight: float = 0.1,
    seed: int = 42,
    device: str | None = None,
    report_every: int = 10,
) -> tuple[Any, dict[str, Any]]:
    import numpy as np
    import torch

    if epochs <= 0:
        raise NeuroScapeError("epochs must be positive")
    if batch_size <= 1:
        raise NeuroScapeError("batch_size must be greater than 1")

    torch.manual_seed(seed)
    np.random.seed(seed)

    train_matrix, validation_matrix = split_stage2_matrix(matrix, validation_size=validation_size, seed=seed)
    torch_device = choose_torch_device(device)
    model = build_stage2_network(
        int(matrix.shape[1]),
        hidden_dimensions=hidden_dimensions,
        output_dimension=output_dimension,
        dropout=dropout,
    ).to(torch_device)

    optimizer = torch.optim.Adam(model.parameters(), lr=initial_learning_rate, weight_decay=0.01)
    gamma = (minimum_learning_rate / initial_learning_rate) ** (1 / max(epochs, 1))
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=1, gamma=gamma)

    validation_tensor = torch.tensor(validation_matrix, dtype=torch.float32, device=torch_device)
    best_validation_loss = float("inf")
    best_state = copy.deepcopy(model.state_dict())
    train_history: list[dict[str, float]] = []

    for epoch in range(epochs):
        model.train()
        permutation = np.random.permutation(train_matrix.shape[0])
        shuffled = train_matrix[permutation]
        batch_losses: list[float] = []
        batch_info_losses: list[float] = []
        batch_correlation_losses: list[float] = []

        for start in range(0, shuffled.shape[0], batch_size):
            stop = min(start + batch_size, shuffled.shape[0])
            current_batch = shuffled[start:stop]
            if current_batch.shape[0] < 2:
                continue
            batch_tensor = torch.tensor(current_batch, dtype=torch.float32, device=torch_device)
            optimizer.zero_grad()
            total_loss, info_nce_loss, correlation_loss = compute_stage2_losses(
                model,
                batch_tensor,
                temperature=temperature,
                cutoff_values=cutoff_values,
                correlation_weight=correlation_weight,
            )
            total_loss.backward()
            optimizer.step()
            batch_losses.append(float(total_loss.item()))
            batch_info_losses.append(float(info_nce_loss.item()))
            batch_correlation_losses.append(float(correlation_loss.item()))

        scheduler.step()
        validation_loss = evaluate_stage2_model(
            model,
            validation_tensor,
            temperature=temperature,
            cutoff_values=cutoff_values,
        )
        if validation_loss < best_validation_loss:
            best_validation_loss = validation_loss
            best_state = copy.deepcopy(model.state_dict())

        epoch_record = {
            "epoch": float(epoch + 1),
            "training_loss": float(sum(batch_losses) / max(len(batch_losses), 1)),
            "training_info_nce_loss": float(sum(batch_info_losses) / max(len(batch_info_losses), 1)),
            "training_correlation_loss": float(sum(batch_correlation_losses) / max(len(batch_correlation_losses), 1)),
            "validation_loss": float(validation_loss),
        }
        train_history.append(epoch_record)
        if epoch == 0 or (epoch + 1) % report_every == 0 or epoch + 1 == epochs:
            print(json.dumps(epoch_record, sort_keys=True))

    model.load_state_dict(best_state)
    return model, {
        "device": torch_device,
        "epochs": epochs,
        "batch_size": batch_size,
        "validation_size": validation_size,
        "temperature": temperature,
        "cutoff_values": list(cutoff_values),
        "correlation_weight": correlation_weight,
        "best_validation_loss": best_validation_loss,
        "history": train_history,
    }


def apply_stage2_model(model: Any, matrix: Any, batch_size: int = 256, device: str | None = None) -> Any:
    import numpy as np
    import torch

    torch_device = choose_torch_device(device)
    model = model.to(torch_device)
    model.eval()
    projected_batches: list[Any] = []
    with torch.no_grad():
        for start in range(0, matrix.shape[0], batch_size):
            stop = min(start + batch_size, matrix.shape[0])
            batch_tensor = torch.tensor(matrix[start:stop], dtype=torch.float32, device=torch_device)
            projected_batches.append(model(batch_tensor).cpu().numpy())
    return np.concatenate(projected_batches, axis=0)


def load_pretrained_stage2_model(
    model_path: Path,
    input_dimension: int,
    hidden_dimensions: tuple[int, int, int] = PUBLISHED_STAGE2_HIDDEN_DIMENSIONS,
    output_dimension: int = PUBLISHED_STAGE2_OUTPUT_DIMENSION,
    dropout: float = 0.05,
    device: str | None = None,
) -> tuple[Any, str]:
    import torch

    torch_device = choose_torch_device(device)
    model = build_stage2_network(
        input_dimension,
        hidden_dimensions=hidden_dimensions,
        output_dimension=output_dimension,
        dropout=dropout,
    ).to(torch_device)
    state = torch.load(model_path, map_location=torch_device)
    model.load_state_dict(state)
    model.eval()
    return model, torch_device


def write_stage2_bundle(
    output_dir: Path,
    stage1_bundle: dict[str, Any],
    projected_matrix: Any,
    model: Any,
    training_summary: dict[str, Any],
    hidden_dimensions: tuple[int, int, int],
    output_dimension: int,
    dropout: float,
) -> None:
    import numpy as np
    import torch

    output_dir.mkdir(parents=True, exist_ok=True)
    np.save(output_dir / "vectors.npy", np.asarray(projected_matrix, dtype=np.float32))
    torch.save(model.state_dict(), output_dir / "domain_embedding_model_best.pth")
    write_json(output_dir / "neighbors.json", compute_neighbors(stage1_bundle["ids"], projected_matrix))
    write_json(output_dir / "training.json", training_summary)
    write_json(
        output_dir / "metadata.json",
        {
            "embedding_name": output_dir.name,
            "model_name": "neuroscape-stage2-local",
            "count": len(stage1_bundle["ids"]),
            "ids": stage1_bundle["ids"],
            "metadata": stage1_bundle["metadata"],
            "source_embedding_name": stage1_bundle["source_metadata"].get("embedding_name"),
            "source_model_name": stage1_bundle["source_metadata"].get("model_name"),
            "embedding_fields": stage1_bundle["source_metadata"].get("embedding_fields"),
            "stage2_config": {
                "hidden_dimensions": list(hidden_dimensions),
                "output_dimension": output_dimension,
                "dropout": dropout,
            },
            "training_summary": {
                "device": training_summary["device"],
                "epochs": training_summary["epochs"],
                "batch_size": training_summary["batch_size"],
                "best_validation_loss": training_summary["best_validation_loss"],
            },
        },
    )


def write_pretrained_stage2_bundle(
    output_dir: Path,
    stage1_bundle: dict[str, Any],
    projected_matrix: Any,
    model_path: Path,
    model_name: str,
    hidden_dimensions: tuple[int, int, int],
    output_dimension: int,
    dropout: float,
) -> None:
    import numpy as np
    import shutil

    output_dir.mkdir(parents=True, exist_ok=True)
    np.save(output_dir / "vectors.npy", np.asarray(projected_matrix, dtype=np.float32))
    shutil.copy2(model_path, output_dir / model_path.name)
    write_json(output_dir / "neighbors.json", compute_neighbors(stage1_bundle["ids"], projected_matrix))
    write_json(
        output_dir / "metadata.json",
        {
            "embedding_name": output_dir.name,
            "model_name": model_name,
            "count": len(stage1_bundle["ids"]),
            "ids": stage1_bundle["ids"],
            "metadata": stage1_bundle["metadata"],
            "source_embedding_name": stage1_bundle["source_metadata"].get("embedding_name"),
            "source_model_name": stage1_bundle["source_metadata"].get("model_name"),
            "embedding_fields": stage1_bundle["source_metadata"].get("embedding_fields"),
            "stage2_config": {
                "hidden_dimensions": list(hidden_dimensions),
                "output_dimension": output_dimension,
                "dropout": dropout,
                "pretrained_model_path": str(model_path),
            },
        },
    )


def build_stage2_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train and apply a local NeuroScape stage-2 model from an existing stage-1 embedding bundle"
    )
    parser.add_argument("--stage1-dir", default=str(artifacts.EMBEDDINGS_ROOT / "minilm_stage1"))
    parser.add_argument("--output-dir", default=str(artifacts.EMBEDDINGS_ROOT / "neuroscape_stage2_local"))
    parser.add_argument("--device")
    parser.add_argument("--hidden-dimensions", nargs="+", type=int, default=list(DEFAULT_STAGE2_HIDDEN_DIMENSIONS))
    parser.add_argument("--output-dimension", type=int, default=DEFAULT_STAGE2_OUTPUT_DIMENSION)
    parser.add_argument("--dropout", type=float, default=0.1)
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--validation-size", type=float, default=0.05)
    parser.add_argument("--initial-learning-rate", type=float, default=1e-4)
    parser.add_argument("--minimum-learning-rate", type=float, default=1e-5)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--positive-cutoff", type=float, default=0.85)
    parser.add_argument("--negative-cutoff", type=float, default=0.75)
    parser.add_argument("--correlation-weight", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--report-every", type=int, default=10)
    return parser


def build_apply_pretrained_stage2_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply the published NeuroScape stage-2 model to a compatible stage-1 embedding bundle"
    )
    parser.add_argument("--stage1-dir", default=str(artifacts.EMBEDDINGS_ROOT / "voyage_stage1"))
    parser.add_argument(
        "--model-path",
        default="/Users/satra/software/repronim/abcd-repronim/data/NeuroScape/Data/Models/domain_embedding_model.pth",
    )
    parser.add_argument("--output-dir", default=str(artifacts.EMBEDDINGS_ROOT / "voyage_stage2_published"))
    parser.add_argument("--device")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--dropout", type=float, default=0.05)
    return parser


def apply_pretrained_stage2_main(argv: list[str] | None = None) -> int:
    args = build_apply_pretrained_stage2_parser().parse_args(argv)
    stage1_bundle = load_stage1_bundle(Path(args.stage1_dir))
    matrix = stage1_bundle["matrix"]
    if int(matrix.shape[1]) != 1024:
        raise NeuroScapeError(
            f"Published NeuroScape stage-2 model expects 1024-dimensional stage-1 embeddings; got {int(matrix.shape[1])}"
        )
    model_path = Path(args.model_path)
    model, torch_device = load_pretrained_stage2_model(
        model_path,
        input_dimension=int(matrix.shape[1]),
        hidden_dimensions=PUBLISHED_STAGE2_HIDDEN_DIMENSIONS,
        output_dimension=PUBLISHED_STAGE2_OUTPUT_DIMENSION,
        dropout=args.dropout,
        device=args.device,
    )
    projected_matrix = apply_stage2_model(
        model,
        matrix,
        batch_size=args.batch_size,
        device=torch_device,
    )
    write_pretrained_stage2_bundle(
        Path(args.output_dir),
        stage1_bundle,
        projected_matrix,
        model_path=model_path,
        model_name="neuroscape-stage2-published",
        hidden_dimensions=PUBLISHED_STAGE2_HIDDEN_DIMENSIONS,
        output_dimension=PUBLISHED_STAGE2_OUTPUT_DIMENSION,
        dropout=args.dropout,
    )
    print(
        json.dumps(
            {
                "stage1_dir": args.stage1_dir,
                "model_path": str(model_path),
                "output_dir": args.output_dir,
                "count": len(stage1_bundle["ids"]),
                "input_dimension": int(matrix.shape[1]),
                "output_dimension": int(projected_matrix.shape[1]),
                "device": torch_device,
            },
            indent=2,
        )
    )
    return 0


def stage2_main(argv: list[str] | None = None) -> int:
    args = build_stage2_parser().parse_args(argv)
    stage1_bundle = load_stage1_bundle(Path(args.stage1_dir))
    hidden_dimensions = normalize_hidden_dimensions(args.hidden_dimensions)
    model, training_summary = train_stage2_model(
        stage1_bundle["matrix"],
        hidden_dimensions=hidden_dimensions,
        output_dimension=args.output_dimension,
        dropout=args.dropout,
        epochs=args.epochs,
        batch_size=args.batch_size,
        validation_size=args.validation_size,
        initial_learning_rate=args.initial_learning_rate,
        minimum_learning_rate=args.minimum_learning_rate,
        temperature=args.temperature,
        cutoff_values=(args.positive_cutoff, args.negative_cutoff),
        correlation_weight=args.correlation_weight,
        seed=args.seed,
        device=args.device,
        report_every=args.report_every,
    )
    projected_matrix = apply_stage2_model(
        model,
        stage1_bundle["matrix"],
        batch_size=args.batch_size,
        device=training_summary["device"],
    )
    write_stage2_bundle(
        Path(args.output_dir),
        stage1_bundle,
        projected_matrix,
        model,
        training_summary,
        hidden_dimensions=hidden_dimensions,
        output_dimension=args.output_dimension,
        dropout=args.dropout,
    )
    print(
        json.dumps(
            {
                "stage1_dir": args.stage1_dir,
                "output_dir": args.output_dir,
                "count": len(stage1_bundle["ids"]),
                "device": training_summary["device"],
                "best_validation_loss": training_summary["best_validation_loss"],
                "epochs": args.epochs,
            },
            indent=2,
        )
    )
    return 0


def build_manifest_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write the NeuroScape handoff manifest for OHBM 2026 embeddings")
    parser.add_argument("--output", default=str(artifacts.EMBEDDINGS_ROOT / "neuroscape_stage2_manifest.json"))
    return parser


def manifest_main(argv: list[str] | None = None) -> int:
    args = build_manifest_parser().parse_args(argv)
    write_neuroscape_manifest(Path(args.output))
    print(json.dumps({"output": args.output}, indent=2))
    return 0

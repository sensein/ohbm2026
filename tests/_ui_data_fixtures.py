"""Tiny synthetic fixtures shared by Stage 6 builder tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


CORPUS_PAYLOAD = {
    "fetched_at": "2026-05-17T00:00:00Z",
    "abstract_count": 3,
    "abstracts": [
        {
            "id": 1001,
            "poster_id": "0101",
            "title": "Memory fMRI in aging",
            "accepted_for": "Poster",
            "authors": [{"author_order": 0, "id": 5000}, {"author_order": 1, "id": 5001}],
            "responses": [
                {"question_name": "Keywords", "value": "Aging|MRI"},
                {"question_name": "Primary Parent Category & Sub-Category", "value": "Lifespan Development|Aging"},
                {"question_name": "Secondary Parent Category & Sub-Category", "value": "Neuroinformatics and Data Sharing|Informatics Other"},
                {"question_name": "Please indicate which methods were used in your research:", "value": "Functional MRI|Diffusion MRI"},
            ],
        },
        {
            "id": 1002,
            "poster_id": "0102",
            "title": "Withdrawn study",
            "accepted_for": "Withdrawn",
            "authors": [{"author_order": 0, "id": 5002}],
            "responses": [],
        },
        {
            "id": 1003,
            "poster_id": "0103",
            "title": "fMRI of default mode network",
            "accepted_for": "Oral",
            "authors": [{"author_order": 0, "id": 5000}],
            "responses": [
                {"question_name": "Keywords", "value": "DMN|resting-state"},
                {"question_name": "Primary Parent Category & Sub-Category", "value": "Cognition|Memory"},
                {"question_name": "Please indicate which methods were used in your research:", "value": "Functional MRI"},
            ],
        },
    ],
}

WITHDRAWN_PAYLOAD = {
    "fetched_at": "2026-05-17T00:00:00Z",
    "abstract_count": 1,
    "abstracts": [
        {"id": 1002, "poster_id": "0102", "accepted_for": "Withdrawn"},
    ],
}

AUTHORS_PAYLOAD = {
    "fetched_at": "2026-05-17T00:00:00Z",
    "author_count": 4,
    "authors": [
        {
            "id": 5000,
            "first_name": "Jane",
            "middle_initial": None,
            "last_name": "Smith",
            "submission_id": 1001,
            "affiliations": [
                {
                    "id": 9000,
                    "affiliation_order": 0,
                    "institution": "Stanford University",
                    "city": "Stanford",
                    "state": "CA",
                    "country": "United States",
                }
            ],
        },
        {
            "id": 5001,
            "first_name": "John",
            "middle_initial": "Q",
            "last_name": "Doe",
            "submission_id": 1001,
            "affiliations": [
                {"id": 9001, "affiliation_order": 0, "institution": "MIT", "city": "Cambridge", "state": "MA", "country": "United States"}
            ],
        },
        {
            "id": 5002,
            "first_name": "Foo",
            "middle_initial": None,
            "last_name": "Bar",
            "submission_id": 1002,  # withdrawn — should be filtered out
            "affiliations": [],
        },
        {
            "id": 5000,
            "first_name": "Jane",
            "middle_initial": None,
            "last_name": "Smith",
            "submission_id": 1003,
            "affiliations": [
                {"id": 9000, "affiliation_order": 0, "institution": "Stanford University", "city": "Stanford", "state": "CA", "country": "United States"}
            ],
        },
    ],
}


# Stage 23 — slim dimensions fixture (spec 023). Keyed by submission id.
# 1001 (exported, poster 101): all four dimensions. 1003 (exported, poster
# 103): missing theory_scope. 9999: not in the export → unmatched_in_file.
DIMENSIONS_SLIM_PAYLOAD = {
    "schema_version": "dimensions.slim.v1",
    "dimensions": {
        "1001": {
            "focus": ["Translational", "Clinical"],
            "research_modality": ["Observational", "Computational"],
            "theory_scope": ["Domain Framework"],
            "epistemic_basis": ["Data-driven"],
        },
        "1003": {
            "focus": ["Fundamental"],
            "research_modality": ["Experimental"],
            "theory_scope": [],
            "epistemic_basis": ["Hypothesis-driven"],
        },
        "9999": {
            "focus": ["Clinical"],
            "research_modality": ["Computational"],
            "theory_scope": ["Micro Theory"],
            "epistemic_basis": ["Data-driven"],
        },
    },
}


def _create_rollup(path: Path) -> None:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    # Mirror the production schema but with a minimal column subset that
    # covers two models × two inputs to exercise the wide-→long projection.
    cur.execute(
        """
        CREATE TABLE annotations (
            abstract_id INTEGER PRIMARY KEY,
            umap2d_neuroscape_x REAL, umap2d_neuroscape_y REAL,
            umap3d_neuroscape_x REAL, umap3d_neuroscape_y REAL, umap3d_neuroscape_z REAL,
            umap2d_minilm_x REAL, umap2d_minilm_y REAL,
            umap3d_minilm_x REAL, umap3d_minilm_y REAL, umap3d_minilm_z REAL,
            community_neuroscape_abstract INTEGER,
            community_neuroscape_methods INTEGER,
            community_minilm_abstract INTEGER,
            community_minilm_methods INTEGER,
            topic_cluster_neuroscape_abstract INTEGER,
            topic_cluster_neuroscape_methods INTEGER,
            topic_cluster_minilm_abstract INTEGER,
            topic_cluster_minilm_methods INTEGER,
            neuroscape_cluster_neuroscape_abstract INTEGER,
            neuroscape_cluster_distance_neuroscape_abstract REAL,
            neuroscape_cluster_neuroscape_methods INTEGER,
            neuroscape_cluster_distance_neuroscape_methods REAL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE cluster_topics (
            clustering_method TEXT, model_key TEXT, input_source TEXT, cluster_id INTEGER,
            topic_keywords TEXT, topic_title TEXT, topic_description TEXT, topic_focus TEXT,
            PRIMARY KEY (clustering_method, model_key, input_source, cluster_id)
        )
        """
    )
    cur.executemany(
        "INSERT INTO annotations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                1001,
                0.1, 0.2, 0.1, 0.2, 0.3,
                1.1, 1.2, 1.1, 1.2, 1.3,
                7, 7, 12, 12,
                100, 100, 200, 200,
                42, 0.5, 42, 0.5,
            ),
            (
                1003,
                0.4, 0.5, 0.4, 0.5, 0.6,
                1.4, 1.5, 1.4, 1.5, 1.6,
                7, 8, 12, 13,
                101, 101, 200, 201,
                42, 0.7, 43, 0.9,
            ),
        ],
    )
    cluster_rows = [
        # communities (per model/input)
        ("communities", "neuroscape", "abstract", 7, "memory|aging", "Memory & Aging", "...", "methodologies"),
        ("communities", "neuroscape", "methods", 7, "fmri", "fMRI cluster", "...", ""),
        ("communities", "neuroscape", "methods", 8, "dmn", "DMN", "...", ""),
        ("communities", "minilm", "abstract", 12, "k1", "T", "", ""),
        ("communities", "minilm", "methods", 12, "k1", "T", "", ""),
        ("communities", "minilm", "methods", 13, "k2", "T", "", ""),
        # topic_clusters
        ("topic_clusters", "neuroscape", "abstract", 100, "k", "T", "", ""),
        ("topic_clusters", "neuroscape", "abstract", 101, "k", "T", "", ""),
        ("topic_clusters", "neuroscape", "methods", 100, "k", "T", "", ""),
        ("topic_clusters", "neuroscape", "methods", 101, "k", "T", "", ""),
        ("topic_clusters", "minilm", "abstract", 200, "k", "T", "", ""),
        ("topic_clusters", "minilm", "methods", 200, "k", "T", "", ""),
        ("topic_clusters", "minilm", "methods", 201, "k", "T", "", ""),
        # neuroscape_clusters (neuroscape only)
        ("neuroscape_clusters", "neuroscape", "abstract", 42, "k", "T", "", ""),
        ("neuroscape_clusters", "neuroscape", "methods", 42, "k", "T", "", ""),
        ("neuroscape_clusters", "neuroscape", "methods", 43, "k", "T", "", ""),
    ]
    cur.executemany("INSERT INTO cluster_topics VALUES (?,?,?,?,?,?,?,?)", cluster_rows)
    conn.commit()
    conn.close()


def write_fixtures(root: Path) -> dict[str, Path]:
    """Populate *root* with all fixture artifacts and return their paths."""

    root.mkdir(parents=True, exist_ok=True)
    corpus = root / "abstracts.json"
    corpus.write_text(json.dumps(CORPUS_PAYLOAD))
    withdrawn = root / "abstracts_withdrawn.json"
    withdrawn.write_text(json.dumps(WITHDRAWN_PAYLOAD))
    authors = root / "authors.json"
    authors.write_text(json.dumps(AUTHORS_PAYLOAD))
    rollup = root / "annotations__test12345678.sqlite"
    _create_rollup(rollup)
    dimensions = root / "dimensions.slim.json"
    dimensions.write_text(json.dumps(DIMENSIONS_SLIM_PAYLOAD))
    return {
        "corpus": corpus,
        "withdrawn": withdrawn,
        "authors": authors,
        "rollup": rollup,
        "dimensions": dimensions,
        "analysis_root": root,
    }


BUILD_INFO = {
    "corpus_state_key": "test12345678",
    "code_revision": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
    "code_revision_short": "a1b2c3d",
    "stage4_rollup_state_key": "test12345678",
    "built_at": "2026-05-17T00:00:00+00:00",
}

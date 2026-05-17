"""Submission-form question helpers used by the Stage 6 UI data builders.

Stage 1 stores submitter responses as an array of ``{question_name, value}``
records on each raw abstract. The Stage 6 builders need a small set of
helpers to:

- Look up answers by question name.
- Resolve the (parent, subcategory) topic pair from the two topic
  questions.
- Apply pattern dictionaries (species / recording technology / brain
  regions / brain networks) to the full text blob to derive the
  domain-facet axes that the UI's facet panel exposes.

These helpers used to live in the legacy ``ohbm2026.ui.payload`` module
that drove the static UI bundle written by ``ohbmcli export-ui``. Now
that the Stage 6 SvelteKit site has replaced that path, the helpers were
extracted here and the legacy module retired.
"""

from __future__ import annotations

import re
from typing import Any

from ohbm2026.analyze.storage import parse_string_list_value
from ohbm2026.titles import cleaned_abstract_title

QUESTION_MAP = {
    "methods": "Please indicate which methods were used in your research:",
    "study_type": 'Please indicate below if your study was a "resting state" or "task-activation” study.',
    "population": "Healthy subjects only or patients (note that patient studies may also involve healthy subjects).",
    "field_strength": "For human MRI, what field strength scanner do you use?",
    "processing_packages": "Which processing packages did you use for your study?",
}
PRIMARY_TOPIC_QUESTION = "Primary Parent Category & Sub-Category"
SECONDARY_TOPIC_QUESTION = "Secondary Parent Category & Sub-Category"

SPECIES_PATTERNS: dict[str, tuple[str, ...]] = {
    "Human": (r"\bhuman(s)?\b", r"\bparticipant(s)?\b", r"\bpatient(s)?\b", r"\bhealthy subject(s)?\b"),
    "Mouse": (r"\bmouse\b", r"\bmice\b", r"\bmus musculus\b"),
    "Rat": (r"\brat(s)?\b", r"\brattus\b"),
    "Macaque": (r"\bmacaque(s)?\b", r"\bmonkey\b", r"\bnon-?human primate(s)?\b"),
    "Marmoset": (r"\bmarmoset(s)?\b",),
    "Zebrafish": (r"\bzebrafish\b",),
}
RECORDING_TECH_PATTERNS: dict[str, tuple[str, ...]] = {
    "fMRI": (r"\bfmri\b", r"\bbold\b"),
    "Structural MRI": (r"\bstructural mri\b", r"\bt1w?\b", r"\bt2w?\b"),
    "Diffusion MRI": (r"\bdiffusion mri\b", r"\bdti\b", r"\bdwi\b"),
    "EEG": (r"\beeg\b", r"\belectroencephalograph", r"\bscalp eeg\b"),
    "MEG": (r"\bmeg\b", r"\bmagnetoencephalograph"),
    "ECoG": (r"\becog\b", r"\belectrocorticograph"),
    "PET": (r"\bpet\b", r"\bpositron emission tomography\b"),
    "fNIRS": (r"\bfnirs\b", r"\bfunctional near infrared spectroscopy\b"),
    "MRS": (r"\bmrs\b", r"\bmagnetic resonance spectroscopy\b"),
    "TMS": (r"\btms\b", r"\btranscranial magnetic stimulation\b", r"\btheta burst stimulation\b", r"\btbs\b"),
    "tDCS/tES": (r"\btdcs\b", r"\btes\b", r"\btranscranial electrical stimulation\b"),
    "DBS": (r"\bdbs\b", r"\bdeep brain stimulation\b"),
    "Calcium Imaging": (r"\bcalcium imaging\b", r"\bgcamp\b"),
    "Electrophysiology": (r"\belectrophysiolog", r"\bspike(s)?\b", r"\blfp\b", r"\bsingle-unit\b", r"\bmulti-unit\b"),
}
BRAIN_REGION_PATTERNS: dict[str, tuple[str, ...]] = {
    "Amygdala": (r"\bamygdala\b",),
    "Hippocampus": (r"\bhippocamp",),
    "Thalamus": (r"\bthalam",),
    "Cerebellum": (r"\bcerebell",),
    "Striatum": (r"\bstriat", r"\bcaudate\b", r"\bputamen\b", r"\bnucleus accumbens\b"),
    "Basal Ganglia": (r"\bbasal ganglia\b", r"\bglobus pallidus\b", r"\bsubthalamic nucleus\b"),
    "Prefrontal Cortex": (r"\bprefrontal cortex\b", r"\bpfc\b", r"\bdlpfc\b", r"\bvm?pfc\b", r"\bfrontopolar\b", r"\bofc\b"),
    "Anterior Cingulate Cortex": (r"\banterior cingulate\b", r"\bacc\b"),
    "Posterior Cingulate Cortex": (r"\bposterior cingulate\b", r"\bpcc\b"),
    "Insula": (r"\binsula\b", r"\binsular\b"),
    "Motor Cortex": (r"\bmotor cortex\b", r"\bm1\b", r"\bpremotor\b", r"\bsma\b", r"\bsupplementary motor area\b"),
    "Visual Cortex": (r"\bvisual cortex\b", r"\bv1\b", r"\boccipital cortex\b"),
    "Somatosensory Cortex": (r"\bsomatosensory cortex\b", r"\bs1\b"),
    "Temporal Cortex": (r"\btemporal cortex\b", r"\btemporal lobe\b", r"\bsuperior temporal\b"),
    "Parietal Cortex": (r"\bparietal cortex\b", r"\bparietal lobe\b", r"\bintraparietal\b"),
    "Occipital Cortex": (r"\boccipital cortex\b", r"\boccipital lobe\b"),
    "Brainstem": (r"\bbrainstem\b", r"\bmidbrain\b", r"\bpons\b", r"\bmedulla\b"),
}
BRAIN_NETWORK_PATTERNS: dict[str, tuple[str, ...]] = {
    "Default Mode Network": (r"\bdefault mode network\b", r"\bdmn\b"),
    "Salience Network": (r"\bsalience network\b",),
    "Frontoparietal Network": (r"\bfrontoparietal network\b", r"\bexecutive control network\b", r"\bcontrol network\b"),
    "Dorsal Attention Network": (r"\bdorsal attention network\b", r"\bdan\b"),
    "Ventral Attention Network": (r"\bventral attention network\b", r"\bvan\b"),
    "Visual Network": (r"\bvisual network\b",),
    "Sensorimotor Network": (r"\bsensorimotor network\b", r"\bmotor network\b"),
    "Limbic Network": (r"\blimbic network\b",),
}


def question_lookup(abstract: dict[str, Any]) -> dict[str, Any]:
    return {
        str(response.get("question_name") or ""): response.get("value")
        for response in abstract.get("responses", [])
    }


def topic_pair_from_questions(questions: dict[str, Any], question_name: str) -> list[str]:
    return parse_string_list_value(questions.get(question_name))


def topic_parent(topic_values: list[str]) -> str:
    return topic_values[0] if topic_values else "Unknown"


def topic_subcategory(topic_values: list[str]) -> str:
    if len(topic_values) >= 2:
        return topic_values[1]
    if topic_values:
        return topic_values[0]
    return "Unknown"


def primary_topic_from_questions(questions: dict[str, Any]) -> str:
    return topic_parent(topic_pair_from_questions(questions, PRIMARY_TOPIC_QUESTION))


def _markdown_to_plain_text(text: str | None) -> str:
    value = str(text or "")
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", value)
    value = value.replace("**", "").replace("*", "").replace("_", "")
    value = re.sub(r"^#+\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s*[-*]\s+", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s*\d+\.\s+", "", value, flags=re.MULTILINE)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _figure_note_sort_key(record: dict[str, Any]) -> tuple[int, str]:
    question_name = str(record.get("question_name") or "").strip()
    normalized = question_name.lower()
    if "methods" in normalized and "figure" in normalized:
        group = 0
    elif "results" in normalized and "figure" in normalized:
        group = 1
    else:
        group = 2
    return (group, question_name)


def _build_figure_text_blob(enriched_abstract: dict[str, Any]) -> str:
    parts: list[str] = []
    records = sorted(enriched_abstract.get("figure_analyses", []) or [], key=_figure_note_sort_key)
    for record in records:
        analysis = record.get("analysis") or {}
        for value in (
            analysis.get("caption_guess"),
            analysis.get("notes"),
            analysis.get("ocr_text"),
        ):
            text = str(value or "").strip()
            if text:
                parts.append(text)
        rich_markdown = str(analysis.get("rich_markdown") or "").strip()
        if rich_markdown:
            parts.append(_markdown_to_plain_text(rich_markdown))
        keywords = [
            str(keyword).strip()
            for keyword in (analysis.get("keywords") or [])
            if str(keyword).strip()
        ]
        if keywords:
            parts.append(" ".join(keywords))
    return "\n".join(part for part in parts if part)


def _render_additional_content_markdown(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            question_name = str(item.get("question_name") or "").strip()
            markdown = str(item.get("markdown") or "").strip()
            if not markdown:
                continue
            if question_name:
                parts.append(f"### {question_name}\n\n{markdown}")
            else:
                parts.append(markdown)
        return "\n\n".join(parts).strip()
    return ""


def _find_pattern_matches(text: str, pattern_map: dict[str, tuple[str, ...]]) -> list[str]:
    matches: list[str] = []
    for label, patterns in pattern_map.items():
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            matches.append(label)
    return matches


def build_domain_facets(
    raw_abstract: dict[str, Any],
    enriched_abstract: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, list[str]]:
    """Apply species / tech / region / network pattern dictionaries.

    The text blob fed to the pattern matcher is the union of the
    abstract title, any methods/results markdown carried on the
    enriched record, the figure-note text blob (if present — Stage 2.1
    groups figures under ``figure_interpretation`` instead, so this
    typically returns empty), the rendered additional-content
    markdown, and the keyword + methods checklist values.
    """
    figure_text = _build_figure_text_blob(enriched_abstract)
    text = "\n".join(
        part
        for part in (
            cleaned_abstract_title(raw_abstract.get("title")),
            enriched_abstract.get("methods_markdown") or "",
            enriched_abstract.get("results_markdown") or "",
            _render_additional_content_markdown(enriched_abstract.get("additional_content_questions_markdown")),
            figure_text,
            " ".join(metadata.get("keywords") or []),
            " ".join(metadata.get("methods") or []),
        )
        if part
    )
    return {
        "species": _find_pattern_matches(text, SPECIES_PATTERNS),
        "recording_technology": _find_pattern_matches(text, RECORDING_TECH_PATTERNS),
        "brain_regions": _find_pattern_matches(text, BRAIN_REGION_PATTERNS),
        "brain_networks": _find_pattern_matches(text, BRAIN_NETWORK_PATTERNS),
    }

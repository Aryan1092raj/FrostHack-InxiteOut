"""
Email DNA Extractor & Signal Correlator

Innovation #2: Instead of tracking vague "tone" labels, extract measurable
structural features from each email and correlate them with actual EO/EC rates.

After probing, we know: "question subjects + early CTA + sparse emoji = 18% CTR"
vs "statement subjects + end CTA + heavy emoji = 7% CTR"

This turns subjective copywriting into a data-driven constraint system.
"""

import re
from typing import Any


# ── Feature Extraction ─────────────────────────────────────────────────────────

def extract_dna(subject: str, body: str, tone: str = "") -> dict[str, str]:
    """
    Extract structural DNA features from a single email.
    Returns a feature dict — all values are categorical strings for easy comparison.
    """

    # ── Subject Features ──────────────────────────────────────────────────────
    subj_len = len(subject.strip())
    if subj_len < 40:
        subject_length = "short"
    elif subj_len < 80:
        subject_length = "medium"
    else:
        subject_length = "long"

    # Opener type — the single most important subject feature
    stripped = subject.strip()
    words = stripped.split()
    first_word = words[0].lower() if words else ""

    if stripped.endswith("?"):
        subject_opener = "question"
    elif first_word and first_word[0].isdigit():
        subject_opener = "number"
    elif first_word in {"earn", "get", "discover", "unlock", "grow", "build",
                        "start", "boost", "maximise", "maximize", "save", "invest"}:
        subject_opener = "action_verb"
    elif first_word in {"dear", "hi", "hello", "hey"}:
        subject_opener = "greeting"
    elif first_word in {"why", "how", "what", "when", "where", "which"}:
        subject_opener = "question"  # implicit question
    else:
        subject_opener = "statement"

    # ── Body Features ─────────────────────────────────────────────────────────
    XDEPOSIT_MARKER = "superbfsi.com/xdeposit"
    body_lower = body.lower()
    url_positions = [m.start() for m in re.finditer(re.escape(XDEPOSIT_MARKER), body_lower)]

    if not url_positions:
        cta_position = "missing"
    elif len(url_positions) >= 2:
        cta_position = "multiple"
    else:
        relative = url_positions[0] / max(len(body), 1)
        if relative < 0.25:
            cta_position = "top"
        elif relative < 0.65:
            cta_position = "middle"
        else:
            cta_position = "end"

    body_len = len(body.strip())
    if body_len < 200:
        body_length = "short"
    elif body_len < 500:
        body_length = "medium"
    else:
        body_length = "long"

    # Emoji density
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F1FF\U00002700-\U000027BF"
        "\U0001F900-\U0001F9FF\U00002600-\U000026FF]+",
        flags=re.UNICODE,
    )
    emoji_count = len(emoji_pattern.findall(subject + body))
    if emoji_count == 0:
        emoji_density = "none"
    elif emoji_count < 4:
        emoji_density = "sparse"
    else:
        emoji_density = "heavy"

    # Bold usage (markdown **)
    bold_markers = body.count("**") // 2
    if bold_markers == 0:
        bold_usage = "none"
    elif bold_markers < 3:
        bold_usage = "sparse"
    else:
        bold_usage = "heavy"

    # Personalisation signal (uses "you"/"your" prominently)
    you_count = len(re.findall(r"\byou\b|\byour\b", body_lower))
    personalisation = "high" if you_count >= 5 else ("medium" if you_count >= 2 else "low")

    # Numeric evidence (uses actual numbers/percentages)
    has_numbers = bool(re.search(r"\d+\.?\d*\s*%|\d+\s*percent|₹\s*\d+|\d+\s*lakh", body_lower + subject.lower()))
    numeric_evidence = "yes" if has_numbers else "no"

    return {
        "subject_length":   subject_length,
        "subject_opener":   subject_opener,
        "cta_position":     cta_position,
        "body_length":      body_length,
        "emoji_density":    emoji_density,
        "bold_usage":       bold_usage,
        "personalisation":  personalisation,
        "numeric_evidence": numeric_evidence,
        "tone":             tone.split("/")[0].strip().lower() if tone else "neutral",
    }


# ── Signal Correlation ─────────────────────────────────────────────────────────

def compute_dna_signal(probe_results: list[dict]) -> dict[str, dict[str, float]]:
    """
    Given a list of probe results (each with dna + click_rate + open_rate),
    compute the average click_rate and open_rate for each feature value.

    Returns: {
        "subject_opener": {"question": 0.18, "number": 0.12, "statement": 0.07},
        "cta_position":   {"multiple": 0.20, "top": 0.15, "end": 0.06},
        ...
    }
    """
    accumulator: dict[str, dict[str, dict[str, float]]] = {}

    for result in probe_results:
        dna = result.get("dna", {})
        click_rate = float(result.get("click_rate", 0))
        open_rate = float(result.get("open_rate", 0))

        for feature, value in dna.items():
            accumulator.setdefault(feature, {}).setdefault(value, {"click_sum": 0.0, "open_sum": 0.0, "n": 0})
            accumulator[feature][value]["click_sum"] += click_rate
            accumulator[feature][value]["open_sum"] += open_rate
            accumulator[feature][value]["n"] += 1

    signal_map: dict[str, dict[str, float]] = {}
    for feature, values in accumulator.items():
        signal_map[feature] = {
            val: round(data["click_sum"] / data["n"], 4)
            for val, data in values.items()
            if data["n"] > 0
        }

    return signal_map


def get_winning_dna(signal_map: dict[str, dict[str, float]]) -> dict[str, str]:
    """
    For each feature dimension, pick the value with the highest avg click rate.
    This becomes the hard constraint for future content generation.
    """
    return {
        feature: max(values, key=values.get)
        for feature, values in signal_map.items()
        if values
    }


def dna_to_content_instructions(winning_dna: dict[str, str]) -> str:
    """
    Convert winning DNA dict into natural language instructions
    that can be injected directly into the content_gen LLM prompt.
    """
    if not winning_dna:
        return ""

    lines = ["🧬 DNA-CONSTRAINED WRITING RULES (learned from probe data — follow strictly):"]

    mapping = {
        "subject_opener": {
            "question":    "Subject MUST be a question (end with ?).",
            "number":      "Subject MUST start with a number or percentage (e.g. '1% more...').",
            "action_verb": "Subject MUST start with an action verb (Earn, Grow, Discover...).",
            "statement":   "Subject should be a clear declarative statement.",
            "greeting":    "Subject should open with a greeting (Hi, Dear...).",
        },
        "cta_position": {
            "multiple": "CTA URL must appear at LEAST twice — in the first paragraph AND at the end.",
            "top":      "CTA URL must appear in the FIRST 2-3 sentences.",
            "middle":   "CTA URL should appear roughly mid-way through the body.",
            "end":      "CTA URL at the end of the email.",
        },
        "body_length": {
            "short":  "Keep body SHORT — under 200 words. Be punchy.",
            "medium": "Keep body MEDIUM — 200-400 words. Balanced detail.",
            "long":   "Body can be LONG — 400+ words. Build the case thoroughly.",
        },
        "emoji_density": {
            "none":   "NO emojis anywhere — keep it text-only and professional.",
            "sparse": "Use 2-3 emojis maximum — placed at key moments only.",
            "heavy":  "Use emojis liberally (5+) — visual, energetic style.",
        },
        "bold_usage": {
            "none":   "No bold text — plain prose only.",
            "sparse": "Bold 1-2 key phrases (the rate advantage, the CTA).",
            "heavy":  "Bold all key numbers, product name, and CTA.",
        },
        "personalisation": {
            "high":   "Address the reader directly with 'you'/'your' at least 5 times.",
            "medium": "Use 'you' naturally 2-3 times.",
            "low":    "Write in a general broadcast voice.",
        },
        "numeric_evidence": {
            "yes": "Include specific numbers: '1% higher', '0.25% extra', actual rate figures.",
            "no":  "Focus on emotional/aspirational language over statistics.",
        },
    }

    for feature, value in winning_dna.items():
        instruction = mapping.get(feature, {}).get(value)
        if instruction:
            lines.append(f"  • {instruction}")

    return "\n".join(lines)

"""Rule/template parser — NL → InstructionSchema with no LLM (docs/02, rule baseline in 04).

Keyword + light-regex extraction sufficient for the seed episodes (direct / reference / quantity).
Deterministic and dependency-free, so it drives the W1 end-to-end run without any API key.
"""

from __future__ import annotations

import re

from ..schema.instruction import InstructionSchema

# intent keyword -> canonical intent (first match wins; order matters for multi-word phrases)
_INTENT_PATTERNS: list[tuple[str, str]] = [
    (r"\bpick up\b|\bpick\b|\bgrab\b|\btake\b|\blift\b", "pick"),
    (r"\bbring\b|\bfetch\b|\bget me\b|\bbring me\b", "bring"),
    (r"\bplace\b|\bput\b|\bset down\b", "place"),
    (r"\bopen\b", "open"),
    (r"\bclose\b|\bshut\b", "close"),
    (r"\bpour\b", "pour"),
    (r"\bclean\b|\bwash\b|\brinse\b", "clean"),
    (r"\bnavigate\b|\bgo to\b|\bmove to\b", "navigate"),
]

# category synonyms -> canonical object_category (longer phrases first)
_CATEGORY_SYNONYMS: list[tuple[str, str]] = [
    (r"conical (?:flask|bottle)|erlenmeyer", "conical_flask"),
    (r"test tube", "test_tube"),
    (r"petri dish", "petri_dish"),
    (r"glass rod|stir(?:ring)? rod", "glass_rod"),
    (r"beaker rack|rack", "beaker_rack"),
    (r"wash station|sink", "wash_station"),
    (r"drying oven|oven", "drying_oven"),
    (r"beaker", "beaker"),
    (r"bottle", "bottle"),
    (r"pipette", "pipette"),
    (r"drawer", "drawer"),
    (r"door", "door"),
    (r"tray", "tray"),
    (r"heater", "heater"),
    (r"centrifuge", "centrifuge"),
    (r"balance|scale", "balance"),
]

_NUM_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

# words that make the instruction a referring expression (object_ref) — kept in sync with the
# grounding resolver's spatial/attribute vocabulary (scene/grounding.py) so e.g. "the hazardous
# beaker" actually filters by attribute rather than staying ambiguous.
_QUALIFIERS = ("left", "right", "near", "inside", "nearest", "closest", "farthest", "furthest",
               "empty", "full", "filled", "hot", "capped", "open", "dirty", "contaminated",
               "clean", "hazardous")


class RuleParser:
    def parse(self, instruction: str) -> InstructionSchema:
        text = instruction.strip().lower()

        intent = next((canon for pat, canon in _INTENT_PATTERNS if re.search(pat, text)), "composite")
        category = next((canon for pat, canon in _CATEGORY_SYNONYMS if re.search(pat, text)), None)
        quantity = self._quantity(text)
        destination = self._destination(text)
        object_ref = instruction.strip() if any(q in text for q in _QUALIFIERS) else None

        missing: list[str] = []
        if intent in {"pick", "place", "pour", "clean", "bring", "mobile_pick"} and category is None:
            missing.append("object_category")

        return InstructionSchema(
            intent=intent,
            object_category=category,
            object_ref=object_ref,
            quantity=quantity,
            destination=destination,
            missing_slots=missing,
        )

    @staticmethod
    def _quantity(text: str) -> int:
        m = re.search(r"\b(\d+)\b", text)
        if m:
            return int(m.group(1))
        for word, n in _NUM_WORDS.items():
            if re.search(rf"\b{word}\b", text):
                return n
        return 1

    @staticmethod
    def _destination(text: str) -> str | None:
        m = re.search(r"\b(?:to|into|onto|on|in)\s+the\s+([a-z_ ]+?)(?:\s|$|\.)", text)
        if not m:
            return None
        phrase = m.group(1).strip()
        for pat, canon in _CATEGORY_SYNONYMS:
            if re.search(pat, phrase):
                return canon
        return phrase.replace(" ", "_")

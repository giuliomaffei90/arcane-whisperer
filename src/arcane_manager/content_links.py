from __future__ import annotations

from .platform import Any, re
from .data import Spell
from .dice import DICE_INLINE_PATTERN
from .resources import MAX_ALIAS_CHARS, MAX_SHORT_FIELD_CHARS, MAX_TEXT_FIELD_CHARS
from .text_utils import clean_text, normalize

COMPONENT_BADGE_PATTERN = re.compile(r"\[(?:V|S|M)\]")
ATTACK_BONUS_PATTERN = re.compile(
    r"\b(?:Melee|Ranged|Melee or Ranged)\s+(?:Weapon|Spell)\s+Attack:\s*([+-]\s*\d+)\s+to hit",
    flags=re.I,
)
CHECK_BONUS_LINE_PATTERN = re.compile(r"^(Saving Throws|Skills):[^\n]*", flags=re.M)
SIGNED_BONUS_PATTERN = re.compile(r"([+-]\s*\d+)")


def dice_ranges_for_body(body: str) -> list[tuple[int, int, str]]:
    return [
        (match.start(), match.end() - match.start(), re.sub(r"\s+", "", match.group(0)))
        for match in DICE_INLINE_PATTERN.finditer(body)
    ]


def d20_expression_for_bonus(bonus: int) -> str:
    return f"1d20+{bonus}" if bonus >= 0 else f"1d20{bonus}"


def attack_roll_ranges_for_body(body: str) -> list[tuple[int, int, str]]:
    ranges: list[tuple[int, int, str]] = []
    for match in ATTACK_BONUS_PATTERN.finditer(body):
        bonus_text = re.sub(r"\s+", "", match.group(1))
        try:
            bonus = int(bonus_text)
        except ValueError:
            continue
        start, end = match.start(1), match.end(1)
        ranges.append((start, end - start, d20_expression_for_bonus(bonus)))
    return ranges


def check_bonus_ranges_for_body(body: str) -> list[tuple[int, int, str]]:
    ranges: list[tuple[int, int, str]] = []
    for line_match in CHECK_BONUS_LINE_PATTERN.finditer(body):
        line = line_match.group(0)
        for bonus_match in SIGNED_BONUS_PATTERN.finditer(line):
            bonus_text = re.sub(r"\s+", "", bonus_match.group(1))
            try:
                bonus = int(bonus_text)
            except ValueError:
                continue
            start = line_match.start() + bonus_match.start(1)
            end = line_match.start() + bonus_match.end(1)
            ranges.append((start, end - start, d20_expression_for_bonus(bonus)))
    return ranges


def monster_roll_ranges_for_body(body: str) -> list[tuple[int, int, str]]:
    return sorted(
        dice_ranges_for_body(body) + attack_roll_ranges_for_body(body) + check_bonus_ranges_for_body(body),
        key=lambda item: item[0],
    )


def spell_section_ranges(body: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    section_start = None
    section_heading = re.compile(r"^[A-Za-z][A-Za-z ]+:$", flags=re.M)
    for match in section_heading.finditer(body):
        heading = match.group(0).rstrip(":").lower()
        if heading == "spells":
            section_start = match.end()
            continue
        if section_start is not None:
            ranges.append((section_start, match.start()))
            section_start = None
    if section_start is not None:
        ranges.append((section_start, len(body)))
    return ranges


def spell_ranges_for_body(body: str, spells: list[Spell], allowed_sections: list[tuple[int, int]] | None = None) -> list[tuple[int, int, Spell]]:
    candidates: list[tuple[int, str, Spell]] = []
    seen: set[tuple[str, str]] = set()
    for spell in spells:
        for name in (spell.name, spell.italian_name, *spell.aliases):
            cleaned = clean_text(name, MAX_ALIAS_CHARS)
            normalized = normalize(cleaned)
            if len(normalized) < 3:
                continue
            key = (normalized, spell.id)
            if key in seen:
                continue
            seen.add(key)
            candidates.append((len(normalized), normalized, spell))

    ranges: list[tuple[int, int, Spell]] = []
    occupied: list[tuple[int, int]] = []
    for _length, candidate, spell in sorted(candidates, key=lambda item: item[0], reverse=True):
        words = candidate.split()
        if not words:
            continue
        pattern_text = r"[^A-Za-z0-9]+".join(re.escape(word) for word in words)
        pattern = re.compile(rf"(?<![A-Za-z0-9]){pattern_text}(?![A-Za-z0-9])", flags=re.I)
        for match in pattern.finditer(body):
            start, end = match.start(), match.end()
            if allowed_sections is not None and not any(section_start <= start and end <= section_end for section_start, section_end in allowed_sections):
                continue
            if any(start < used_end and end > used_start for used_start, used_end in occupied):
                continue
            occupied.append((start, end))
            ranges.append((start, end - start, spell))
    ranges.sort(key=lambda item: item[0])
    return ranges


def _entry_display_text(entry: dict[str, Any]) -> str:
    name = clean_text(entry.get("name", ""), MAX_SHORT_FIELD_CHARS)
    desc = clean_text(entry.get("desc", ""), MAX_TEXT_FIELD_CHARS)
    damage = clean_text(entry.get("damage_dice", ""), MAX_SHORT_FIELD_CHARS)
    prefix = f"{name}. " if name else ""
    suffix = f" Damage dice: {damage}." if damage and damage not in desc else ""
    if name and desc.endswith(":") and not suffix:
        return f"{name}:\n{desc}"
    return f"{prefix}{desc}{suffix}".strip()


def _resolve_spell_link(link: Any, spells: list[Spell], spell_lookup: dict[str, Spell]) -> tuple[str, Spell] | None:
    if isinstance(link, str):
        text = clean_text(link, MAX_ALIAS_CHARS)
        spell = spell_lookup.get(normalize(text))
        return (text, spell) if text and spell is not None else None
    if not isinstance(link, dict):
        return None

    text = clean_text(link.get("text", ""), MAX_ALIAS_CHARS)
    spell_id = clean_text(link.get("spell_id", ""), MAX_SHORT_FIELD_CHARS)
    spell = next((candidate for candidate in spells if candidate.id == spell_id), None) if spell_id else None
    if spell is None and text:
        spell = spell_lookup.get(normalize(text))
    return (text, spell) if text and spell is not None else None


def explicit_spell_ranges_for_entries(
    body: str,
    entry_groups: list[Any],
    spells: list[Spell],
    spell_lookup: dict[str, Spell],
) -> list[tuple[int, int, Spell]]:
    ranges: list[tuple[int, int, Spell]] = []
    occupied: list[tuple[int, int]] = []
    search_start = 0
    for entries in entry_groups:
        if not isinstance(entries, (list, tuple)):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            text = _entry_display_text(entry)
            if not text:
                continue
            entry_start = body.find(text, search_start)
            if entry_start < 0:
                entry_start = body.find(text)
            if entry_start < 0:
                continue
            entry_end = entry_start + len(text)
            search_start = entry_end

            links = entry.get("spell_links")
            if not isinstance(links, list):
                continue
            for link in links:
                resolved = _resolve_spell_link(link, spells, spell_lookup)
                if resolved is None:
                    continue
                link_text, spell = resolved
                words = normalize(link_text).split()
                if not words:
                    continue
                pattern_text = r"[^A-Za-z0-9]+".join(re.escape(word) for word in words)
                pattern = re.compile(rf"(?<![A-Za-z0-9]){pattern_text}(?![A-Za-z0-9])", flags=re.I)
                for match in pattern.finditer(body, entry_start, entry_end):
                    start, end = match.start(), match.end()
                    if any(start < used_end and end > used_start for used_start, used_end in occupied):
                        continue
                    occupied.append((start, end))
                    ranges.append((start, end - start, spell))
    ranges.sort(key=lambda item: item[0])
    return ranges

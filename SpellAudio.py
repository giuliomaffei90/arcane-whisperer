#!/usr/bin/env python3
"""
Arcane Manager for macOS.

A local Dungeons & Dragons table assistant with an initiative tracker,
spell reference, bestiary lookup, and dice roller.
"""

from __future__ import annotations

import argparse
import functools
import html
import http.server
import json
import random
import re
import sys
import threading
import unicodedata
import warnings
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - startup dependency message covers installs
    BeautifulSoup = None

try:
    from markdown_it import MarkdownIt
except ImportError:  # pragma: no cover - Adventure tab shows a friendly message
    MarkdownIt = None

try:
    import objc
    warnings.filterwarnings("ignore", category=objc.ObjCPointerWarning)
    from AppKit import (
        NSApp,
        NSApplication,
        NSApplicationActivationPolicyRegular,
        NSAlert,
        NSBackingStoreBuffered,
        NSBezierPath,
        NSButton,
        NSColor,
        NSColorWell,
        NSCursor,
        NSFont,
        NSFontAttributeName,
        NSFontManager,
        NSForegroundColorAttributeName,
        NSGraphicsContext,
        NSImage,
        NSImageView,
        NSItalicFontMask,
        NSMakeRect,
        NSMenu,
        NSMenuItem,
        NSOpenPanel,
        NSMutableParagraphStyle,
        NSPanel,
        NSParagraphStyleAttributeName,
        NSPopUpButton,
        NSScrollView,
        NSScreen,
        NSStatusBar,
        NSTrackingActiveAlways,
        NSTrackingArea,
        NSTrackingInVisibleRect,
        NSTrackingMouseEnteredAndExited,
        NSTrackingMouseMoved,
        NSTextView,
        NSTextFieldCell,
        NSVariableStatusItemLength,
        NSView,
        NSWindow,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSWindowStyleMaskBorderless,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable,
        NSWindowStyleMaskResizable,
        NSWindowStyleMaskTitled,
        NSWindowStyleMaskUtilityWindow,
        NSWorkspace,
        NSWorkspaceRecycleOperation,
        NSTextField,
        NSCompositingOperationSourceOver,
    )
    from WebKit import (
        WKUserContentController,
        WKUserScript,
        WKUserScriptInjectionTimeAtDocumentStart,
        WKWebView,
        WKWebViewConfiguration,
    )
    from Foundation import (
        NSMutableAttributedString,
        NSString,
        NSURL,
        NSURLRequest,
        NSMakePoint,
        NSMakeRange,
        NSMakeSize,
        NSObject,
        NSTimer,
        NSUserDefaults,
    )
except ImportError as exc:  # pragma: no cover - helpful startup error
    raise SystemExit(
        "Missing macOS dependency. Run:\n"
        "  .venv/bin/python -m pip install -r requirements.txt\n"
    ) from exc


def resource_base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def bundled_resource_path(name: str) -> Path:
    direct_path = BASE_DIR / name
    if direct_path.exists():
        return direct_path
    return BASE_DIR / "resources" / name


BASE_DIR = resource_base_dir()
DEFAULT_SPELLS_FILE = bundled_resource_path("spells.json")
DEFAULT_BESTIARY_FILE = bundled_resource_path("bestiary_srd.json")
DEFAULT_DICE_ROLLER_HTML = bundled_resource_path("assets/dice_roller/index.html")
DEFAULT_ICON_DIR = bundled_resource_path("assets/icons")
LOG_FILE = Path.home() / "Library" / "Logs" / "Arcane Manager" / "arcane_manager.log"
APP_RETAINED_OBJECTS: list[Any] = []
DICE_ROLL_ANIMATOR: Any = None
THREE_D_DICE_ROLLER: Any = None
DICE_ASSET_SERVER: Any = None
DICE_ASSET_SERVER_THREAD: threading.Thread | None = None
DICE_ASSET_SERVER_URL = ""
MAX_SPELL_FILE_BYTES = 12 * 1024 * 1024
MAX_SPELLS = 2500
MAX_TEXT_FIELD_CHARS = 50000
MAX_SHORT_FIELD_CHARS = 500
MAX_ALIAS_CHARS = 140
MAX_ALIASES_PER_SPELL = 80
TRANSCRIPT_NORMALIZATION_REPLACEMENTS = {
    "appalla": "palla",
    "parla": "palla",
    "fuego": "fuoco",
    "fuega": "fuoco",
    "foco": "fuoco",
    "focca": "fuoco",
    "focco": "fuoco",
    "focore": "fuoco",
    "fogo": "fuoco",
    "forgo": "fuoco",
    "focor": "fuoco",
    "focori": "fuoco",
    "fuoco": "fuoco",
    "retardata": "ritardata",
    "riterdata": "ritardata",
    "ritedata": "ritardata",
    "tardata": "ritardata",
    "ritardato": "ritardata",
    "ritardo": "ritardata",
    "return": "ritardata",
    "focorita": "fuoco ritardata",
    "focoritardata": "fuoco ritardata",
    "ward": "word",
    "wards": "word",
    "words": "word",
}


PARTIES_PREF = "InitiativeParties"
ADVENTURE_VAULT_PREF = "AdventureVaultPath"
ADVENTURE_SELECTED_NOTE_PREF = "AdventureSelectedNotePath"
CLASS_OPTIONS = [
    "Artificer",
    "Barbarian",
    "Bard",
    "Cleric",
    "Druid",
    "Fighter",
    "Monk",
    "Paladin",
    "Ranger",
    "Rogue",
    "Sorcerer",
    "Warlock",
    "Wizard",
]
CONDITION_OPTIONS = [
    "Blinded",
    "Charmed",
    "Deafened",
    "Frightened",
    "Grappled",
    "Incapacitated",
    "Invisible",
    "Paralyzed",
    "Petrified",
    "Poisoned",
    "Prone",
    "Restrained",
    "Stunned",
    "Unconscious",
    "Exhaustion",
]
CONDITION_COLOR_VALUES = {
    "Blinded": (0.96, 0.78, 0.28),
    "Charmed": (0.95, 0.45, 0.78),
    "Deafened": (0.56, 0.74, 0.96),
    "Frightened": (1.0, 0.48, 0.36),
    "Grappled": (0.64, 0.86, 0.42),
    "Incapacitated": (0.78, 0.62, 0.94),
    "Invisible": (0.52, 0.88, 0.86),
    "Paralyzed": (0.99, 0.64, 0.28),
    "Petrified": (0.70, 0.72, 0.74),
    "Poisoned": (0.38, 0.82, 0.48),
    "Prone": (0.86, 0.70, 0.46),
    "Restrained": (0.48, 0.68, 0.96),
    "Stunned": (1.0, 0.86, 0.32),
    "Unconscious": (0.80, 0.50, 0.55),
    "Exhaustion": (0.62, 0.58, 0.50),
}
CLASS_ICONS = {
    "Artificer": "◇",
    "Barbarian": "◈",
    "Bard": "♪",
    "Cleric": "✚",
    "Druid": "◌",
    "Fighter": "⚔",
    "Monk": "◍",
    "Paladin": "✦",
    "Ranger": "⌖",
    "Rogue": "◒",
    "Sorcerer": "✹",
    "Warlock": "☾",
    "Wizard": "✧",
}
MONSTER_ICON = "☠"
CLASS_ICON_FILES = {
    class_name: f"{class_name.lower()}.png"
    for class_name in CLASS_OPTIONS
}
MONSTER_ICON_FILE = "monster.png"
ICON_IMAGE_CACHE: dict[str, Any] = {}


def normalize(text: str) -> str:
    """Normalize spoken commands and aliases for reliable lookup."""
    folded = unicodedata.normalize("NFKD", text.lower())
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    cleaned = []
    for char in ascii_text:
        cleaned.append(char if char.isalnum() else " ")
    return " ".join("".join(cleaned).split())


def normalize_transcript_for_matching(text: str) -> str:
    words = normalize(text).split()
    expanded_words = []
    for word in words:
        replacement = TRANSCRIPT_NORMALIZATION_REPLACEMENTS.get(word, word)
        expanded_words.extend(replacement.split())

    normalized_words = []
    for index, word in enumerate(expanded_words):
        previous_word = expanded_words[index - 1] if index > 0 else ""
        next_word = expanded_words[index + 1] if index + 1 < len(expanded_words) else ""
        if word in {"i", "e"} and previous_word == "fuoco" and next_word == "ritardata":
            continue
        normalized_words.append(word)
    return " ".join(normalized_words)


def clean_text(value: Any, max_chars: int = MAX_SHORT_FIELD_CHARS) -> str:
    """Convert untrusted JSON values to safe, bounded display text."""
    if value is None:
        return ""
    text = str(value)
    text = "".join(char for char in text if char in "\n\t" or not unicodedata.category(char).startswith("C"))
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def clean_text_list(values: Any, max_items: int, max_chars: int) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    cleaned = []
    for value in values[:max_items]:
        text = clean_text(value, max_chars)
        if text:
            cleaned.append(text)
    return tuple(dict.fromkeys(cleaned))


@dataclass(frozen=True)
class Spell:
    id: str
    name: str
    italian_name: str
    aliases: tuple[str, ...]
    level: str
    school: str
    casting_time: str
    range: str
    components: str
    duration: str
    description: str
    higher_levels: str = ""
    spell_lists: tuple[str, ...] = ()
    source: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Spell":
        if not isinstance(raw, dict):
            raise ValueError("Spell entries must be JSON objects.")

        raw_names = raw.get("names", {})
        names = raw_names if isinstance(raw_names, dict) else {}
        aliases = list(clean_text_list(raw.get("aliases", []), MAX_ALIASES_PER_SPELL, MAX_ALIAS_CHARS))
        for value in (raw.get("name"), names.get("en"), names.get("it")):
            if value:
                aliases.append(clean_text(value, MAX_ALIAS_CHARS))

        visible_name = clean_text(raw.get("name") or names.get("it") or names.get("en"), MAX_SHORT_FIELD_CHARS)
        if not visible_name:
            raise ValueError(f"Spell entry without a name: {raw!r}")

        return cls(
            id=clean_text(raw.get("id") or normalize(visible_name).replace(" ", "-"), MAX_SHORT_FIELD_CHARS),
            name=visible_name,
            italian_name=clean_text(names.get("it", ""), MAX_SHORT_FIELD_CHARS),
            aliases=tuple(dict.fromkeys(a.strip() for a in aliases if a.strip())),
            level=clean_text(raw.get("level", ""), MAX_SHORT_FIELD_CHARS),
            school=clean_text(raw.get("school", ""), MAX_SHORT_FIELD_CHARS),
            casting_time=clean_text(raw.get("casting_time", ""), MAX_SHORT_FIELD_CHARS),
            range=clean_text(raw.get("range", ""), MAX_SHORT_FIELD_CHARS),
            components=clean_text(raw.get("components", ""), MAX_SHORT_FIELD_CHARS),
            duration=clean_text(raw.get("duration", ""), MAX_SHORT_FIELD_CHARS),
            description=clean_text(raw.get("description", ""), MAX_TEXT_FIELD_CHARS),
            higher_levels=clean_text(raw.get("higher_levels", ""), MAX_TEXT_FIELD_CHARS),
            spell_lists=clean_text_list(raw.get("spell_lists", []), 40, MAX_SHORT_FIELD_CHARS),
            source=clean_text(raw.get("source", ""), MAX_SHORT_FIELD_CHARS),
        )


def load_spells(path: Path) -> tuple[list[Spell], dict[str, Spell]]:
    path = path.expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Spell file not found: {path}")
    if not path.is_file():
        raise ValueError(f"Spell path is not a regular file: {path}")
    if path.stat().st_size > MAX_SPELL_FILE_BYTES:
        raise ValueError(f"Spell file is too large: {path}")

    with path.open("r", encoding="utf-8") as handle:
        try:
            payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid spell JSON: {exc}") from exc

    raw_spells = payload.get("spells", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_spells, list):
        raise ValueError("Spell file must contain a list or an object with a 'spells' list.")
    if len(raw_spells) > MAX_SPELLS:
        raise ValueError(f"Spell file contains too many entries: {len(raw_spells)}")

    spells = [Spell.from_dict(item) for item in raw_spells]
    lookup: dict[str, Spell] = {}
    for spell in spells:
        for alias in spell.aliases:
            key = normalize(alias)
            if key:
                lookup[key] = spell
    return spells, lookup


@dataclass(frozen=True)
class Creature:
    name: str
    source: str
    size: str
    creature_type: str
    alignment: str
    ac: int | str
    hp: int
    speed: str
    stats: tuple[int, int, int, int, int, int]
    cr: str
    traits: tuple[dict[str, Any], ...]
    actions: tuple[dict[str, Any], ...]
    legendary_actions: tuple[dict[str, Any], ...]
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Creature":
        stats = raw.get("stats", [])
        if not isinstance(stats, list):
            stats = []
        padded_stats = [int(value or 10) for value in stats[:6]]
        padded_stats.extend([10] * (6 - len(padded_stats)))
        return cls(
            name=clean_text(raw.get("name", ""), MAX_SHORT_FIELD_CHARS),
            source=clean_text(raw.get("source", ""), MAX_SHORT_FIELD_CHARS),
            size=clean_text(raw.get("size", ""), MAX_SHORT_FIELD_CHARS),
            creature_type=clean_text(raw.get("type", ""), MAX_SHORT_FIELD_CHARS),
            alignment=clean_text(raw.get("alignment", ""), MAX_SHORT_FIELD_CHARS),
            ac=raw.get("ac", ""),
            hp=int(raw.get("hp") or 0),
            speed=clean_text(raw.get("speed", ""), MAX_SHORT_FIELD_CHARS),
            stats=tuple(padded_stats),  # type: ignore[arg-type]
            cr=clean_text(raw.get("cr", ""), MAX_SHORT_FIELD_CHARS),
            traits=tuple(item for item in raw.get("traits", []) if isinstance(item, dict)),
            actions=tuple(item for item in raw.get("actions", []) if isinstance(item, dict)),
            legendary_actions=tuple(item for item in raw.get("legendary_actions", []) if isinstance(item, dict)),
            raw=dict(raw),
        )


def load_bestiary(path: Path) -> list[Creature]:
    path = path.expanduser()
    if not path.exists():
        log(f"Bestiary file not found: {path}")
        return []
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    raw_creatures = payload.get("creatures", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_creatures, list):
        raise ValueError("Bestiary file must contain a list or an object with a 'creatures' list.")
    creatures = [Creature.from_dict(item) for item in raw_creatures if isinstance(item, dict)]
    return [creature for creature in creatures if creature.name]


def ability_modifier(score: int) -> int:
    return (score - 10) // 2


def display_ac(value: int | str) -> str:
    if isinstance(value, int):
        return str(value)
    return clean_text(value, MAX_SHORT_FIELD_CHARS) or "?"


def creature_summary(creature: Creature) -> str:
    return f"{creature.name}   HP: {creature.hp}   AC: {display_ac(creature.ac)}   CR: {creature.cr}"


def cr_sort_value(value: str) -> float:
    text = clean_text(value, MAX_SHORT_FIELD_CHARS)
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        try:
            return float(numerator) / float(denominator)
        except (TypeError, ValueError, ZeroDivisionError):
            return 999.0
    try:
        return float(text)
    except (TypeError, ValueError):
        return 999.0


def creature_cr_values(creatures: list[Creature]) -> list[str]:
    values = {creature.cr for creature in creatures if creature.cr}
    return sorted(values, key=lambda value: (cr_sort_value(value), value))


def search_creatures(query: str, creatures: list[Creature], cr_filter: str | None = None, limit: int | None = None) -> list[Creature]:
    filtered_creatures = [creature for creature in creatures if not cr_filter or creature.cr == cr_filter]
    normalized_query = normalize(query)
    if not normalized_query:
        results = sorted(filtered_creatures, key=lambda creature: normalize(creature.name))
        return results if limit is None else results[:limit]

    matched: list[Creature] = []
    compact_query = normalized_query.replace(" ", "")
    for creature in filtered_creatures:
        normalized_name = normalize(creature.name)
        compact_name = normalized_name.replace(" ", "")
        if normalized_name == normalized_query:
            score = 1.0
        elif normalized_name.startswith(normalized_query):
            score = 0.94
        elif normalized_query in normalized_name:
            score = 0.86
        elif compact_query and compact_query in compact_name:
            score = 0.82
        else:
            score = SequenceMatcher(None, normalized_query, normalized_name).ratio() * 0.78
        if score >= 0.45:
            matched.append(creature)
    matched.sort(key=lambda creature: normalize(creature.name))
    return matched if limit is None else matched[:limit]


def format_spell_for_detail(spell: Spell) -> tuple[str, str, str]:
    title = spell.name
    meta_parts = [
        part
        for part in (
            spell.level,
            spell.school,
            spell.casting_time,
        )
        if part
    ]

    body_parts = []
    if spell.description.strip():
        body_parts.append(spell.description.strip())
    if spell.higher_levels.strip():
        body_parts.append(f"At Higher Levels. {spell.higher_levels.strip()}")

    return title, " | ".join(meta_parts) or "Spell found", "\n\n".join(body_parts)


def component_flags(components: str) -> dict[str, bool]:
    normalized = normalize(components)
    tokens = normalized.split()
    return {
        "V": "v" in tokens,
        "S": "s" in tokens,
        "M": "m" in tokens,
    }


def component_material(components: str) -> str:
    material = ""
    material_start = components.find("(")
    if material_start >= 0:
        material = components[material_start:].strip()
    return material


DICE_PATTERN = re.compile(r"\b(\d+)d(\d+)(?:\s*([+-])\s*(\d+))?\b", flags=re.I)
DICE_FORMULA_PATTERN = re.compile(r"^\s*\d+d\d+(?:\s*\+\s*\d+d\d+)*(?:\s*[+-]\s*\d+)?\s*$", flags=re.I)
COMPONENT_BADGE_PATTERN = re.compile(r"\[(?:V|S|M)\]")
ATTACK_BONUS_PATTERN = re.compile(
    r"\b(?:Melee|Ranged|Melee or Ranged)\s+(?:Weapon|Spell)\s+Attack:\s*([+-]\s*\d+)\s+to hit",
    flags=re.I,
)
CHECK_BONUS_LINE_PATTERN = re.compile(r"^(Saving Throws|Skills):[^\n]*", flags=re.M)
SIGNED_BONUS_PATTERN = re.compile(r"([+-]\s*\d+)")


def dice_ranges_for_body(body: str) -> list[tuple[int, int, str]]:
    return [(match.start(), match.end() - match.start(), match.group(0)) for match in DICE_PATTERN.finditer(body)]


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


@dataclass(frozen=True)
class DiceRollResult:
    expression: str
    count: int
    sides: int
    modifier: int
    rolls: tuple[int, ...]
    total: int


def roll_dice(expression: str) -> DiceRollResult:
    match = DICE_PATTERN.fullmatch(expression.strip())
    if not match:
        raise ValueError(f"Invalid dice expression: {expression}")

    count = int(match.group(1))
    sides = int(match.group(2))
    sign = match.group(3) or "+"
    modifier_value = int(match.group(4) or 0)
    modifier = modifier_value if sign == "+" else -modifier_value
    if count < 1 or count > 100 or sides < 2 or sides > 1000:
        raise ValueError(f"Unsupported dice expression: {expression}")

    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier
    return DiceRollResult(
        expression=expression.strip(),
        count=count,
        sides=sides,
        modifier=modifier,
        rolls=tuple(rolls),
        total=total,
    )


def format_dice_roll(result: DiceRollResult) -> str:
    roll_details = ", ".join(str(value) for value in result.rolls)
    if result.modifier:
        sign = "+" if result.modifier > 0 else "-"
        roll_details = f"{roll_details} {sign} {abs(result.modifier)}"
    return f"Rolled {result.expression}: {result.total} ({roll_details})"


def roll_dice_formula(expression: str) -> str:
    normalized = re.sub(r"\s+", "", expression.strip())
    if DICE_PATTERN.fullmatch(normalized):
        return format_dice_roll(roll_dice(normalized))
    if not DICE_FORMULA_PATTERN.fullmatch(normalized):
        raise ValueError(f"Invalid dice expression: {expression}")

    token_pattern = re.compile(r"([+-]?)(?:(\d+)d(\d+)|(\d+))", flags=re.I)
    consumed = ""
    total = 0
    groups: list[str] = []
    modifier = 0
    for match in token_pattern.finditer(normalized):
        consumed += match.group(0)
        sign = -1 if match.group(1) == "-" else 1
        if match.group(3):
            if sign < 0:
                raise ValueError(f"Invalid dice expression: {expression}")
            count = int(match.group(2))
            sides = int(match.group(3))
            if count < 1 or count > 40 or sides < 2 or sides > 1000:
                raise ValueError(f"Unsupported dice expression: {expression}")
            rolls = [random.randint(1, sides) for _ in range(count)]
            total += sum(rolls)
            groups.append(f"{count}d{sides}: {', '.join(str(value) for value in rolls)}")
        else:
            modifier += sign * int(match.group(4))
    if consumed != normalized or not groups:
        raise ValueError(f"Invalid dice expression: {expression}")
    total += modifier
    modifier_text = ""
    if modifier:
        modifier_text = f" {'+' if modifier > 0 else '-'} {abs(modifier)}"
    return f"Rolled {normalized}: {total} ({'; '.join(groups)}{modifier_text})"


def roll_dice_expression(expression: str) -> str:
    return format_dice_roll(roll_dice(expression))


DICE_ROLL_HISTORY_LIMIT = 12
DICE_ROLL_HISTORY: list[str] = []
DICE_HISTORY_LISTENERS: list[Any] = []


def record_dice_roll_history(result: Any):
    text = str(result).strip()
    if not text.startswith("Rolled "):
        return
    DICE_ROLL_HISTORY.insert(0, text)
    del DICE_ROLL_HISTORY[DICE_ROLL_HISTORY_LIMIT:]
    for listener in list(DICE_HISTORY_LISTENERS):
        try:
            listener.refreshDiceHistory()
        except Exception:
            pass


def format_dice_roll_history() -> str:
    if not DICE_ROLL_HISTORY:
        return "No rolls yet."
    return "\n".join(f"{index + 1}. {entry}" for index, entry in enumerate(DICE_ROLL_HISTORY))


@dataclass
class AdventureNode:
    path: Path
    name: str
    is_dir: bool
    depth: int
    children: list["AdventureNode"]


ADVENTURE_COLOR_PALETTE = [
    ("Blue", "#3885d6"),
    ("Red", "#ea1f1f"),
    ("Green", "#5bc267"),
    ("Cyan", "#00e2e6"),
    ("yellow", "#d6b300"),
    ("orange", "#d66000"),
    ("pink", "#ff70e5"),
]


THEME_COLORS_PREF = "arcaneManagerThemeColors"


DEFAULT_THEME_RGB: dict[str, tuple[float, float, float]] = {
    "app_bg": (0x1A / 255, 0x1E / 255, 0x24 / 255),
    "panel": (0x1F / 255, 0x23 / 255, 0x2B / 255),
    "panel_alt": (0x1B / 255, 0x20 / 255, 0x27 / 255),
    "surface": (0x25 / 255, 0x29 / 255, 0x32 / 255),
    "surface_hover": (0x2B / 255, 0x30 / 255, 0x38 / 255),
    "surface_soft": (0x22 / 255, 0x26 / 255, 0x2E / 255),
    "border": (0x36 / 255, 0x3C / 255, 0x47 / 255),
    "border_soft": (0x2B / 255, 0x30 / 255, 0x38 / 255),
    "text": (0xE0 / 255, 0xE2 / 255, 0xE6 / 255),
    "text_strong": (0xF0 / 255, 0xF1 / 255, 0xF4 / 255),
    "muted": (0x8F / 255, 0x96 / 255, 0xA3 / 255),
    "link": (0x5A / 255, 0xA7 / 255, 0xF0 / 255),
    "dice": (0x6D / 255, 0xD6 / 255, 0x74 / 255),
    "gold": (0xE4 / 255, 0xC1 / 255, 0x61 / 255),
    "danger": (0xE1 / 255, 0x57 / 255, 0x63 / 255),
    "monster": (0xDC / 255, 0x5F / 255, 0x77 / 255),
    "blue_temp": (0x63 / 255, 0xA8 / 255, 0xF5 / 255),
    "selection": (0x3A / 255, 0x5F / 255, 0x94 / 255),
}


DEFAULT_DICE_THEME_RGB: dict[str, tuple[float, float, float]] = {
    "overlay_panel": (0x1F / 255, 0x23 / 255, 0x2B / 255),
    "overlay_border": (0x56 / 255, 0x60 / 255, 0x70 / 255),
    "overlay_stage": (0x1A / 255, 0x1E / 255, 0x24 / 255),
    "overlay_fallback": (0x1A / 255, 0x1E / 255, 0x24 / 255),
    "dice_red": (0xE1 / 255, 0x57 / 255, 0x63 / 255),
    "dice_text": (0xF0 / 255, 0xF1 / 255, 0xF4 / 255),
    "dice_green": (0x6D / 255, 0xD6 / 255, 0x74 / 255),
}


THEME_RGB = dict(DEFAULT_THEME_RGB)
DICE_THEME_RGB = dict(DEFAULT_DICE_THEME_RGB)


THEME_COLOR_LABELS = [
    ("app_bg", "App background"),
    ("panel", "Main panels"),
    ("panel_alt", "Sidebar panels"),
    ("surface_soft", "Soft surfaces"),
    ("surface", "Controls and rows"),
    ("surface_hover", "Hover and selected controls"),
    ("border_soft", "Subtle borders"),
    ("border", "Strong borders"),
    ("text", "Body text"),
    ("text_strong", "Heading text"),
    ("muted", "Muted text"),
    ("link", "Links"),
    ("dice", "Dice and HP"),
    ("gold", "Spell metadata"),
    ("danger", "Danger states"),
    ("monster", "Monster emphasis"),
    ("blue_temp", "Temporary HP"),
    ("selection", "Selection"),
]


DICE_THEME_COLOR_LABELS = [
    ("overlay_panel", "Overlay panel"),
    ("overlay_border", "Overlay border"),
    ("overlay_stage", "Stage tint"),
    ("overlay_fallback", "Fallback background"),
    ("dice_red", "Dice body"),
    ("dice_text", "Dice text"),
    ("dice_green", "Result green"),
]


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    values = [max(0, min(255, int(round(component * 255)))) for component in rgb]
    return "#{:02x}{:02x}{:02x}".format(*values)


def hex_to_rgb(value: str) -> tuple[float, float, float] | None:
    text = str(value or "").strip()
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", text):
        return None
    return (
        int(text[1:3], 16) / 255.0,
        int(text[3:5], 16) / 255.0,
        int(text[5:7], 16) / 255.0,
    )


def color_to_hex(color) -> str:
    converted = color
    if hasattr(color, "colorUsingColorSpaceName_"):
        try:
            converted = color.colorUsingColorSpaceName_("NSCalibratedRGBColorSpace") or color
        except Exception:
            converted = color
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, int(round(float(converted.redComponent()) * 255)))),
        max(0, min(255, int(round(float(converted.greenComponent()) * 255)))),
        max(0, min(255, int(round(float(converted.blueComponent()) * 255)))),
    )


def theme_snapshot() -> dict[str, dict[str, str]]:
    return {
        "app": {key: rgb_to_hex(THEME_RGB[key]) for key in DEFAULT_THEME_RGB},
        "dice": {key: rgb_to_hex(DICE_THEME_RGB[key]) for key in DEFAULT_DICE_THEME_RGB},
    }


def load_theme_overrides():
    global THEME_RGB, DICE_THEME_RGB
    THEME_RGB = dict(DEFAULT_THEME_RGB)
    DICE_THEME_RGB = dict(DEFAULT_DICE_THEME_RGB)
    raw = NSUserDefaults.standardUserDefaults().stringForKey_(THEME_COLORS_PREF)
    if not raw:
        return
    try:
        data = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    for section, target, defaults in (
        ("app", THEME_RGB, DEFAULT_THEME_RGB),
        ("dice", DICE_THEME_RGB, DEFAULT_DICE_THEME_RGB),
    ):
        values = data.get(section)
        if not isinstance(values, dict):
            continue
        for key in defaults:
            rgb = hex_to_rgb(str(values.get(key, "")))
            if rgb is not None:
                target[key] = rgb


def save_theme_overrides():
    defaults = NSUserDefaults.standardUserDefaults()
    defaults.setObject_forKey_(json.dumps(theme_snapshot()), THEME_COLORS_PREF)
    defaults.synchronize()


def reset_theme_overrides():
    global THEME_RGB, DICE_THEME_RGB
    THEME_RGB = dict(DEFAULT_THEME_RGB)
    DICE_THEME_RGB = dict(DEFAULT_DICE_THEME_RGB)
    defaults = NSUserDefaults.standardUserDefaults()
    defaults.removeObjectForKey_(THEME_COLORS_PREF)
    defaults.synchronize()


def css_rgba(name: str, alpha: float) -> str:
    red, green, blue = DICE_THEME_RGB[name]
    return f"rgba({int(round(red * 255))}, {int(round(green * 255))}, {int(round(blue * 255))}, {alpha:.2f})"


def dice_theme_payload() -> dict[str, str]:
    return {
        "overlayPanel": rgb_to_hex(DICE_THEME_RGB["overlay_panel"]),
        "overlayBorder": rgb_to_hex(DICE_THEME_RGB["overlay_border"]),
        "overlayStage": rgb_to_hex(DICE_THEME_RGB["overlay_stage"]),
        "overlayFallback": rgb_to_hex(DICE_THEME_RGB["overlay_fallback"]),
        "diceRed": rgb_to_hex(DICE_THEME_RGB["dice_red"]),
        "diceText": rgb_to_hex(DICE_THEME_RGB["dice_text"]),
        "diceGreen": rgb_to_hex(DICE_THEME_RGB["dice_green"]),
    }


ADVENTURE_MARKDOWN_CSS = """
:root {
  color-scheme: dark;
  --bg: #1a1e24;
  --panel: #1f232b;
  --surface: #252932;
  --surface-soft: #22262e;
  --text: #e0e2e6;
  --strong: #f0f1f4;
  --muted: #8f96a3;
  --border: #363c47;
  --link: #5aa7f0;
  --dice: #6dd674;
  --gold: #e4c161;
  --danger: #e15763;
}
* { box-sizing: border-box; }
html, body { min-height: 100%; margin: 0; background: var(--bg); }
body {
  color: var(--text);
  font: 16px/1.62 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif;
  padding: 36px 48px 72px;
}
main { max-width: 980px; margin: 0 auto; }
h1, h2, h3, h4 { color: var(--strong); line-height: 1.2; margin: 1.45em 0 0.55em; }
h1 { font-size: 2rem; margin-top: 0; }
h2 { font-size: 1.58rem; }
h3 { font-size: 1.28rem; }
p, ul, ol, table, blockquote, pre, .callout { margin: 0 0 1.05em; }
a { color: var(--link); text-decoration: none; cursor: pointer; }
a:hover { text-decoration: underline; }
.dice-link { color: var(--dice); font-weight: 700; white-space: nowrap; }
strong { color: var(--strong); }
em { color: #d8dbe2; }
code {
  color: var(--gold);
  background: var(--surface-soft);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 0.08em 0.32em;
  font-family: "SF Mono", Menlo, monospace;
  font-size: 0.88em;
}
pre {
  background: var(--surface-soft);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  overflow-x: auto;
}
pre code { border: 0; padding: 0; background: transparent; color: var(--text); }
table {
  width: 100%;
  border-collapse: collapse;
  background: var(--surface-soft);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
th, td { border: 1px solid var(--border); padding: 8px 10px; vertical-align: top; }
th { color: var(--gold); background: var(--surface); text-align: left; }
blockquote {
  border-left: 4px solid #4b5564;
  color: #c9cdd5;
  padding: 0.15em 0 0.15em 1em;
}
.callout {
  --callout-bg: #22262e;
  --callout-border: #363c47;
  --callout-accent: #8f96a3;
  --callout-title: #c3c8d1;
  background: var(--callout-bg);
  border: 1px solid var(--callout-border);
  border-left: 4px solid var(--callout-accent);
  border-radius: 7px;
  padding: 14px 18px 16px;
}
.callout-title {
  color: var(--callout-title);
  font-weight: 800;
  margin-bottom: 0.65em;
  display: flex;
  align-items: baseline;
  gap: 0.42em;
}
.callout-title::before {
  color: var(--callout-accent);
  content: "•";
  flex: 0 0 auto;
  font-weight: 800;
}
.callout-title a { color: inherit; }
.callout-quote {
  --callout-bg: #20242c;
  --callout-border: #2f3540;
  --callout-accent: #8f96a3;
  --callout-title: #c3c8d1;
}
.callout-quote .callout-title::before { content: "❞"; }
.callout-info, .callout-note, .callout-tip {
  --callout-bg: #202c40;
  --callout-border: #2b405c;
  --callout-accent: var(--link);
  --callout-title: var(--link);
}
.callout-info .callout-title::before,
.callout-note .callout-title::before,
.callout-tip .callout-title::before { content: "ⓘ"; }
.callout-warning, .callout-caution, .callout-attention {
  --callout-bg: #302d25;
  --callout-border: #463f2d;
  --callout-accent: var(--gold);
  --callout-title: var(--gold);
}
.callout-warning .callout-title::before,
.callout-caution .callout-title::before,
.callout-attention .callout-title::before { content: "⚠"; }
.callout-danger, .callout-failure, .callout-error {
  --callout-bg: #33262c;
  --callout-border: #50343d;
  --callout-accent: var(--danger);
  --callout-title: var(--danger);
}
img {
  max-width: 100%;
  height: auto;
  display: block;
  border-radius: 8px;
  border: 1px solid var(--border);
  margin: 0.5em 0 1.15em;
}
hr { border: 0; border-top: 1px solid var(--border); margin: 2em 0; }
.empty, .missing { color: var(--muted); font-style: italic; }
@media (max-width: 720px) {
  body { padding: 24px 26px 56px; font-size: 15px; }
}
"""


def adventure_markdown_css() -> str:
    replacements = {
        "--bg: #1a1e24;": f"--bg: {rgb_to_hex(THEME_RGB['app_bg'])};",
        "--panel: #1f232b;": f"--panel: {rgb_to_hex(THEME_RGB['panel'])};",
        "--surface: #252932;": f"--surface: {rgb_to_hex(THEME_RGB['surface'])};",
        "--surface-soft: #22262e;": f"--surface-soft: {rgb_to_hex(THEME_RGB['surface_soft'])};",
        "--text: #e0e2e6;": f"--text: {rgb_to_hex(THEME_RGB['text'])};",
        "--strong: #f0f1f4;": f"--strong: {rgb_to_hex(THEME_RGB['text_strong'])};",
        "--muted: #8f96a3;": f"--muted: {rgb_to_hex(THEME_RGB['muted'])};",
        "--border: #363c47;": f"--border: {rgb_to_hex(THEME_RGB['border'])};",
        "--link: #5aa7f0;": f"--link: {rgb_to_hex(THEME_RGB['link'])};",
        "--dice: #6dd674;": f"--dice: {rgb_to_hex(THEME_RGB['dice'])};",
        "--gold: #e4c161;": f"--gold: {rgb_to_hex(THEME_RGB['gold'])};",
        "--danger: #e15763;": f"--danger: {rgb_to_hex(THEME_RGB['danger'])};",
    }
    css = ADVENTURE_MARKDOWN_CSS
    for old, new in replacements.items():
        css = css.replace(old, new)
    return css


def safe_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def strip_markdown_frontmatter(markdown: str) -> str:
    if not markdown.startswith("---"):
        return markdown
    match = re.match(r"^---\s*\n.*?\n---\s*\n?", markdown, flags=re.S)
    if match:
        return markdown[match.end() :]
    return markdown


def separate_obsidian_callout_titles(markdown: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    for index, line in enumerate(lines):
        output.append(line)
        if not re.match(r"^\s*>\s*\[!\w+\]", line):
            continue
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if re.match(r"^\s*>\s*$", next_line):
            continue
        if re.match(r"^\s*>", next_line):
            output.append(">")
    trailing_newline = "\n" if markdown.endswith("\n") else ""
    return "\n".join(output) + trailing_newline


def natural_sort_key(value: str) -> list[Any]:
    parts = re.split(r"(\d+)", normalize(str(value)))
    return [int(part) if part.isdigit() else part for part in parts]


def markdown_parser():
    if MarkdownIt is None:
        return None
    parser = MarkdownIt("commonmark", {"html": True, "linkify": False})
    for rule in ("table", "strikethrough"):
        try:
            parser.enable(rule)
        except Exception:
            pass
    return parser


def component_badge_text(components: str) -> str:
    flags = component_flags(components)
    badges = [f"[{key}]" if flags[key] else f"{key}-" for key in ("V", "S", "M")]
    material = component_material(components)
    suffix = f"  {material}" if material else ""
    return " ".join(badges) + suffix


def add_colored_ranges(attributed, ranges: list[tuple[int, int, Any]], color):
    for start, length, _payload in ranges:
        attributed.addAttribute_value_range_(NSForegroundColorAttributeName, color, NSMakeRange(start, length))


def attributed_spell_body(body: str):
    dice_color = theme_color("dice")
    component_color = theme_color("gold")
    attributes = {
        NSFontAttributeName: NSFont.systemFontOfSize_(14),
        NSForegroundColorAttributeName: theme_color("text"),
    }
    attributed = NSMutableAttributedString.alloc().initWithString_attributes_(body, attributes)
    marker = "At Higher Levels."
    marker_start = body.find(marker)
    if marker_start >= 0:
        attributed.addAttribute_value_range_(
            NSFontAttributeName,
            NSFont.boldSystemFontOfSize_(15),
            NSMakeRange(marker_start, len(marker)),
        )

    for match in DICE_PATTERN.finditer(body):
        attributed.addAttribute_value_range_(
            NSForegroundColorAttributeName,
            dice_color,
            NSMakeRange(match.start(), match.end() - match.start()),
        )
    for match in COMPONENT_BADGE_PATTERN.finditer(body):
        attributed.addAttribute_value_range_(
            NSForegroundColorAttributeName,
            component_color,
            NSMakeRange(match.start(), match.end() - match.start()),
        )
        attributed.addAttribute_value_range_(
            NSFontAttributeName,
            NSFont.boldSystemFontOfSize_(14),
            NSMakeRange(match.start(), match.end() - match.start()),
        )
    return attributed


def attributed_monster_body(body: str, spell_ranges: list[tuple[int, int, Spell]], roll_ranges: list[tuple[int, int, str]] | None = None):
    dice_color = theme_color("dice")
    spell_color = theme_color("gold")
    base_font_size = 13.0
    base_font = NSFont.systemFontOfSize_(base_font_size)
    italic_font = NSFontManager.sharedFontManager().convertFont_toHaveTrait_(NSFont.userFontOfSize_(base_font_size), NSItalicFontMask)
    paragraph_style = NSMutableParagraphStyle.alloc().init()
    paragraph_style.setLineSpacing_(2.0)
    attributes = {
        NSFontAttributeName: base_font,
        NSForegroundColorAttributeName: theme_color("text"),
        NSParagraphStyleAttributeName: paragraph_style,
    }
    attributed = NSMutableAttributedString.alloc().initWithString_attributes_(body, attributes)
    cursor = 0
    for line in body.splitlines():
        start = cursor
        cursor += len(line) + 1
        if not line:
            continue
        if line.endswith(":"):
            attributed.addAttribute_value_range_(
                NSFontAttributeName,
                NSFont.boldSystemFontOfSize_(18),
                NSMakeRange(start, len(line)),
            )
            continue
        lower_line = line.lower()
        first_period = line.find(".")
        if 0 < first_period <= 42 and ":" not in line[:first_period]:
            attributed.addAttribute_value_range_(
                NSFontAttributeName,
                NSFont.boldSystemFontOfSize_(base_font_size),
                NSMakeRange(start, first_period + 1),
            )
    for start, length, _expression in (roll_ranges if roll_ranges is not None else dice_ranges_for_body(body)):
        attributed.addAttribute_value_range_(
            NSForegroundColorAttributeName,
            dice_color,
            NSMakeRange(start, length),
        )
    add_colored_ranges(attributed, spell_ranges, spell_color)
    cursor = 0
    for line in body.splitlines():
        start = cursor
        cursor += len(line) + 1
        lower_line = line.lower()
        if "spellcaster" in lower_line and "spellcasting ability" in lower_line:
            attributed.addAttribute_value_range_(
                NSFontAttributeName,
                italic_font,
                NSMakeRange(start, len(line)),
            )
    return attributed


def hp_bar(current: int | None, maximum: int | None, width: int = 12) -> tuple[str, float | None]:
    if current is None or maximum is None or maximum <= 0:
        return "─" * width, None
    ratio = max(0.0, min(1.0, current / maximum))
    filled = int(round(ratio * width))
    return "█" * filled + "░" * (width - filled), ratio


def attributed_tracker_body(body: str, bar_ranges: list[tuple[int, int, float | None]], current_ranges: list[tuple[int, int]]):
    attributes = {
        NSFontAttributeName: NSFont.monospacedSystemFontOfSize_weight_(13, 0),
        NSForegroundColorAttributeName: theme_color("text"),
    }
    attributed = NSMutableAttributedString.alloc().initWithString_attributes_(body, attributes)
    muted = theme_color("muted")
    healthy = theme_color("dice")
    danger = theme_color("monster")
    down = theme_color("danger")
    current_color = theme_color("gold")
    for start, length, ratio in bar_ranges:
        color = muted if ratio is None else down if ratio <= 0 else danger if ratio <= 0.35 else healthy
        attributed.addAttribute_value_range_(NSForegroundColorAttributeName, color, NSMakeRange(start, length))
    for start, length in current_ranges:
        attributed.addAttribute_value_range_(NSForegroundColorAttributeName, current_color, NSMakeRange(start, length))
        attributed.addAttribute_value_range_(NSFontAttributeName, NSFont.monospacedSystemFontOfSize_weight_(13, 0.35), NSMakeRange(start, length))
    return attributed


class CheckboxSquareView(NSView):
    checked: bool
    fill_color: Any
    stroke_color: Any

    def initWithFrame_(self, frame):
        self = objc.super(CheckboxSquareView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.checked = False
        self.fill_color = ui_color(1.0, 0.82, 0.26, 0.95)
        self.stroke_color = ui_color(1.0, 0.82, 0.26, 0.82)
        return self

    def setChecked_(self, checked):
        self.checked = bool(checked)
        self.setNeedsDisplay_(True)

    def setFillColor_strokeColor_(self, fill_color, stroke_color):
        self.fill_color = fill_color
        self.stroke_color = stroke_color
        self.setNeedsDisplay_(True)

    def drawRect_(self, _rect):
        bounds = self.bounds()
        box = NSMakeRect(1.5, 1.5, bounds.size.width - 3, bounds.size.height - 3)

        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(box, 3, 3)
        if self.checked:
            self.fill_color.set()
            path.fill()
        self.stroke_color.set()
        path.setLineWidth_(1.5)
        path.stroke()


class FlippedView(NSView):
    def isFlipped(self):
        return True


class ContextInputPanel(NSPanel):
    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return False


class CenteredTextFieldCell(NSTextFieldCell):
    def _centeredRectForBounds_(self, rect):
        draw_rect = objc.super(CenteredTextFieldCell, self).drawingRectForBounds_(rect)
        text_size = self.cellSizeForBounds_(rect)
        if draw_rect.size.height > text_size.height:
            draw_rect.origin.y += (draw_rect.size.height - text_size.height) / 2
            draw_rect.size.height = text_size.height
        return draw_rect

    def drawingRectForBounds_(self, rect):
        return self._centeredRectForBounds_(rect)

    def editWithFrame_inView_editor_delegate_event_(self, rect, control_view, text_obj, delegate, event):
        objc.super(CenteredTextFieldCell, self).editWithFrame_inView_editor_delegate_event_(
            self._centeredRectForBounds_(rect),
            control_view,
            text_obj,
            delegate,
            event,
        )

    def selectWithFrame_inView_editor_delegate_start_length_(self, rect, control_view, text_obj, delegate, start, length):
        objc.super(CenteredTextFieldCell, self).selectWithFrame_inView_editor_delegate_start_length_(
            self._centeredRectForBounds_(rect),
            control_view,
            text_obj,
            delegate,
            start,
            length,
        )


class PaddedCenteredTextFieldCell(CenteredTextFieldCell):
    def _centeredRectForBounds_(self, rect):
        inset = 10
        padded = NSMakeRect(rect.origin.x + inset, rect.origin.y, max(1, rect.size.width - inset * 2), rect.size.height)
        return objc.super(PaddedCenteredTextFieldCell, self)._centeredRectForBounds_(padded)


class DiceTextView(NSTextView):
    dice_ranges: list[tuple[int, int, str]]
    spell_ranges: list[tuple[int, int, Spell]]
    combatant_ranges: list[tuple[int, int, int]]
    roll_target: Any
    spell_target: Any
    combatant_target: Any
    tracking_area: Any

    def initWithFrame_(self, frame):
        self = objc.super(DiceTextView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.dice_ranges = []
        self.spell_ranges = []
        self.combatant_ranges = []
        self.roll_target = None
        self.spell_target = None
        self.combatant_target = None
        self.tracking_area = None
        self.setEditable_(False)
        self.setSelectable_(False)
        self.setDrawsBackground_(False)
        self.setTextContainerInset_(NSMakeSize(0, 0))
        self.setHorizontallyResizable_(False)
        self.setVerticallyResizable_(True)
        self.textContainer().setLineFragmentPadding_(0)
        return self

    def setDiceRanges_(self, dice_ranges):
        self.dice_ranges = list(dice_ranges)

    def setRollTarget_(self, target):
        self.roll_target = target

    def setSpellRanges_(self, spell_ranges):
        self.spell_ranges = list(spell_ranges)

    def setSpellTarget_(self, target):
        self.spell_target = target

    def setCombatantRanges_(self, combatant_ranges):
        self.combatant_ranges = list(combatant_ranges)

    def setCombatantTarget_(self, target):
        self.combatant_target = target

    def updateTrackingAreas(self):
        if self.tracking_area is not None:
            self.removeTrackingArea_(self.tracking_area)
        self.tracking_area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            NSTrackingMouseMoved
            | NSTrackingMouseEnteredAndExited
            | NSTrackingActiveAlways
            | NSTrackingInVisibleRect,
            self,
            None,
        )
        self.addTrackingArea_(self.tracking_area)
        objc.super(DiceTextView, self).updateTrackingAreas()

    def diceExpressionAtEvent_(self, event):
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        index = self.characterIndexForInsertionAtPoint_(point)
        for start, length, expression in self.dice_ranges:
            if start <= index < start + length:
                return expression
        return None

    def spellAtEvent_(self, event):
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        index = self.characterIndexForInsertionAtPoint_(point)
        for start, length, spell in self.spell_ranges:
            if start <= index < start + length:
                return spell
        return None

    def combatantIndexAtEvent_(self, event):
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        index = self.characterIndexForInsertionAtPoint_(point)
        for start, length, combatant_index in self.combatant_ranges:
            if start <= index < start + length:
                return combatant_index
        return None

    def mouseMoved_(self, event):
        if (
            self.diceExpressionAtEvent_(event) is not None
            or self.spellAtEvent_(event) is not None
            or self.combatantIndexAtEvent_(event) is not None
        ):
            NSCursor.pointingHandCursor().set()
        else:
            NSCursor.arrowCursor().set()

    def mouseExited_(self, _event):
        NSCursor.arrowCursor().set()

    def mouseDown_(self, event):
        expression = self.diceExpressionAtEvent_(event)
        if expression is not None:
            if self.roll_target is not None:
                self.roll_target.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "rollDice:",
                    expression,
                    False,
                )
            return
        spell = self.spellAtEvent_(event)
        if spell is not None:
            if self.spell_target is not None:
                self.spell_target.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "openSpell:",
                    spell,
                    False,
                )
            return
        combatant_index = self.combatantIndexAtEvent_(event)
        if combatant_index is not None:
            if self.combatant_target is not None:
                self.combatant_target.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "openCombatantIndex:",
                    combatant_index,
                    False,
                )
            return
        objc.super(DiceTextView, self).mouseDown_(event)


class DiceRollView(NSView):
    roll_result: DiceRollResult | None
    frame_index: int

    def initWithFrame_(self, frame):
        self = objc.super(DiceRollView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.roll_result = None
        self.frame_index = 0
        return self

    def setRollResult_(self, result):
        self.roll_result = result
        self.frame_index = 0
        self.setNeedsDisplay_(True)

    def setFrameIndex_(self, frame_index: int):
        self.frame_index = int(frame_index)
        self.setNeedsDisplay_(True)

    def _draw_text(self, text: str, rect, size: float, color, bold: bool = False, centered: bool = False):
        paragraph_style = None
        font = NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
        attributes = {
            NSFontAttributeName: font,
            NSForegroundColorAttributeName: color,
        }
        if paragraph_style is not None:
            attributes["NSParagraphStyle"] = paragraph_style
        string = NSString.alloc().initWithString_(str(text))
        if centered:
            text_size = string.sizeWithAttributes_(attributes)
            x = rect.origin.x + max(0, (rect.size.width - text_size.width) / 2)
            y = rect.origin.y + max(0, (rect.size.height - text_size.height) / 2)
            string.drawAtPoint_withAttributes_(NSMakePoint(x, y), attributes)
        else:
            string.drawInRect_withAttributes_(rect, attributes)

    def _draw_die(self, x: float, y: float, size: float, value: str, sides: int, active: bool):
        shadow = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(x + 5, y - 5, size, size), 10, 10)
        theme_color("app_bg", 0.42).set()
        shadow.fill()

        side = NSBezierPath.bezierPath()
        side.moveToPoint_(NSMakePoint(x + size, y + 8))
        side.lineToPoint_(NSMakePoint(x + size + 12, y + 18))
        side.lineToPoint_(NSMakePoint(x + size + 12, y + size - 8))
        side.lineToPoint_(NSMakePoint(x + size, y + size))
        side.closePath()
        (theme_color("dice") if active else theme_color("surface")).set()
        side.fill()

        top = NSBezierPath.bezierPath()
        top.moveToPoint_(NSMakePoint(x + 8, y + size))
        top.lineToPoint_(NSMakePoint(x + 20, y + size + 10))
        top.lineToPoint_(NSMakePoint(x + size + 12, y + size + 10))
        top.lineToPoint_(NSMakePoint(x + size, y + size))
        top.closePath()
        (ui_color(0.48, 0.84, 0.56, 1.0) if active else theme_color("surface_hover")).set()
        top.fill()

        face = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(x, y, size, size), 10, 10)
        (ui_color(0.28, 0.70, 0.46, 1.0) if active else theme_color("surface")).set()
        face.fill()
        ui_color(0.74, 0.95, 0.78, 1.0).set()
        face.setLineWidth_(1.5)
        face.stroke()

        self._draw_text(str(value), NSMakeRect(x + 4, y + 4, size - 8, size - 8), 19, theme_color("text_strong"), True, True)
        self._draw_text(f"d{sides}", NSMakeRect(x + 4, y + size - 16, size - 8, 12), 8, theme_color("text", 0.78), False, True)

    def drawRect_(self, _rect):
        bounds = self.bounds()
        background = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, 16, 16)
        theme_color("panel_alt", 0.96).set()
        background.fill()

        result = self.roll_result
        if result is None:
            return

        rolling = self.frame_index < 14
        title_color = theme_color("dice")
        self._draw_text(f"Rolling {result.expression}", NSMakeRect(20, bounds.size.height - 48, bounds.size.width - 40, 26), 16, title_color, True)

        dice_to_draw = min(result.count, 24)
        die_size = 50
        gap = 18
        per_row = max(1, min(8, int((bounds.size.width - 60) // (die_size + gap))))
        rows = max(1, (dice_to_draw + per_row - 1) // per_row)
        start_y = max(92, 118 + (rows - 1) * 70)
        for index in range(dice_to_draw):
            row = index // per_row
            column = index % per_row
            row_count = min(per_row, dice_to_draw - row * per_row)
            total_width = row_count * die_size + max(0, row_count - 1) * gap
            start_x = max(24, (bounds.size.width - total_width) / 2)
            die_x = start_x + column * (die_size + gap)
            die_y = start_y - row * 70
            if rolling:
                value = "?"
                wobble = ((self.frame_index + index) % 3 - 1) * 4
            else:
                value = str(result.rolls[index])
                wobble = 0
            self._draw_die(die_x, die_y + wobble, die_size, value, result.sides, rolling or value != "?")

        if result.count > dice_to_draw:
            self._draw_text(f"+ {result.count - dice_to_draw} more dice included in the total", NSMakeRect(24, 80, bounds.size.width - 48, 20), 12, theme_color("muted"), False, True)

        if not rolling:
            dice_sum = sum(result.rolls)
            details = f"Dice: {dice_sum}"
            if result.modifier:
                sign = "+" if result.modifier > 0 else "-"
                details = f"{details} {sign} {abs(result.modifier)}"
            self._draw_text(f"Total: {result.total}", NSMakeRect(24, 32, bounds.size.width - 48, 34), 24, theme_color("text_strong"), True, True)
            self._draw_text(details, NSMakeRect(24, 16, bounds.size.width - 48, 20), 12, theme_color("muted"), False, True)


class DiceRollAnimator(NSObject):
    panel: NSPanel
    view: DiceRollView
    timer: NSTimer | None
    hide_timer: NSTimer | None
    frame_index: int

    def init(self):
        self = objc.super(DiceRollAnimator, self).init()
        if self is None:
            return None
        self.timer = None
        self.hide_timer = None
        self.frame_index = 0
        screen = NSScreen.mainScreen().visibleFrame()
        width = min(820, int(screen.size.width * 0.82))
        height = 380
        x = screen.origin.x + (screen.size.width - width) / 2
        y = screen.origin.y + screen.size.height - height - 90
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskUtilityWindow
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setTitle_("Dice Roll")
        self.panel.setFloatingPanel_(True)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setLevel_(24)
        self.panel.setBackgroundColor_(theme_color("panel_alt", 0.96))
        self.view = DiceRollView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        self.panel.setContentView_(self.view)
        self.panel.orderOut_(None)
        return self

    def showRoll_(self, result):
        if self.timer is not None:
            self.timer.invalidate()
            self.timer = None
        if self.hide_timer is not None:
            self.hide_timer.invalidate()
            self.hide_timer = None
        self.frame_index = 0
        self.view.setRollResult_(result)
        self.panel.orderFrontRegardless()
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.055,
            self,
            "advance:",
            None,
            True,
        )

    def advance_(self, _timer):
        self.frame_index += 1
        self.view.setFrameIndex_(self.frame_index)
        if self.frame_index >= 22:
            if self.timer is not None:
                self.timer.invalidate()
                self.timer = None
            self.hide_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                6.0,
                self,
                "hide:",
                None,
                False,
            )

    def hide_(self, _timer):
        self.hide_timer = None
        self.panel.orderOut_(None)


def show_dice_roll_animation(result: DiceRollResult):
    global DICE_ROLL_ANIMATOR
    if DICE_ROLL_ANIMATOR is None:
        DICE_ROLL_ANIMATOR = DiceRollAnimator.alloc().init()
        APP_RETAINED_OBJECTS.append(DICE_ROLL_ANIMATOR)
    DICE_ROLL_ANIMATOR.showRoll_(result)


class DiceAssetRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def list_directory(self, _path):
        self.send_error(404, "No directory listing")
        return None


def start_dice_asset_server() -> str:
    global DICE_ASSET_SERVER, DICE_ASSET_SERVER_THREAD, DICE_ASSET_SERVER_URL
    if DICE_ASSET_SERVER_URL:
        return DICE_ASSET_SERVER_URL

    asset_root = DEFAULT_DICE_ROLLER_HTML.parent.parent
    if not asset_root.exists():
        raise FileNotFoundError(f"Dice asset root not found: {asset_root}")

    handler = functools.partial(DiceAssetRequestHandler, directory=str(asset_root))
    DICE_ASSET_SERVER = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    DICE_ASSET_SERVER.daemon_threads = True
    host, port = DICE_ASSET_SERVER.server_address
    DICE_ASSET_SERVER_URL = f"http://{host}:{port}"
    DICE_ASSET_SERVER_THREAD = threading.Thread(
        target=DICE_ASSET_SERVER.serve_forever,
        name="ArcaneManagerDiceAssets",
        daemon=True,
    )
    DICE_ASSET_SERVER_THREAD.start()
    log(f"3D dice asset server started: {DICE_ASSET_SERVER_URL}")
    return DICE_ASSET_SERVER_URL


class Dice3DRollerController(NSObject):
    panel: NSPanel
    web_view: WKWebView
    ready: bool
    pending_expression: str
    result_target: Any
    hide_timer: NSTimer | None

    def initWithHTMLPath_(self, html_path):
        self = objc.super(Dice3DRollerController, self).init()
        if self is None:
            return None
        self.ready = False
        self.pending_expression = ""
        self.result_target = None
        self.hide_timer = None

        screen = NSScreen.mainScreen().visibleFrame()
        width = screen.size.width
        height = screen.size.height
        style = NSWindowStyleMaskBorderless
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(screen.origin.x, screen.origin.y, width, height),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setTitle_("Arcane Manager Dice")
        self.panel.setFloatingPanel_(True)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setLevel_(24)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        user_content = WKUserContentController.alloc().init()
        user_content.addScriptMessageHandler_name_(self, "diceRoll")
        error_script = """
        window.addEventListener('error', function(event) {
          try {
            window.webkit.messageHandlers.diceRoll.postMessage({
              type: 'error',
              text: event.message + ' at ' + event.filename + ':' + event.lineno + ':' + event.colno
            });
          } catch (_) {}
        });
        window.addEventListener('unhandledrejection', function(event) {
          try {
            var reason = event.reason && event.reason.message ? event.reason.message : String(event.reason);
            window.webkit.messageHandlers.diceRoll.postMessage({ type: 'error', text: reason });
          } catch (_) {}
        });
        """
        user_script = WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
            error_script,
            WKUserScriptInjectionTimeAtDocumentStart,
            False,
        )
        user_content.addUserScript_(user_script)
        config = WKWebViewConfiguration.alloc().init()
        config.setUserContentController_(user_content)
        self.web_view = WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, width, height), config)
        self.web_view.setNavigationDelegate_(self)
        self.web_view.setValue_forKey_(False, "drawsBackground")
        self.panel.setContentView_(self.web_view)

        path = Path(str(html_path))
        if path.exists():
            base_url = start_dice_asset_server()
            request = NSURLRequest.requestWithURL_(NSURL.URLWithString_(f"{base_url}/dice_roller/index.html"))
            self.web_view.loadRequest_(request)
        else:
            log(f"3D dice roller HTML not found: {path}")
        self.panel.orderOut_(None)
        return self

    def webView_didFinishNavigation_(self, _web_view, _navigation):
        return

    def webView_didFailNavigation_withError_(self, _web_view, _navigation, error):
        log(f"3D dice web view navigation failed: {error}")

    def webView_didFailProvisionalNavigation_withError_(self, _web_view, _navigation, error):
        log(f"3D dice web view provisional navigation failed: {error}")

    @objc.python_method
    def applyTheme(self):
        payload = json.dumps(dice_theme_payload())
        script = f"if (window.arcaneApplyTheme) {{ window.arcaneApplyTheme({payload}); }}"
        self.web_view.evaluateJavaScript_completionHandler_(script, None)

    def showRoll_target_(self, expression: str, target):
        self.result_target = target
        self.pending_expression = str(expression).strip()
        if self.hide_timer is not None:
            self.hide_timer.invalidate()
            self.hide_timer = None
        self.panel.orderFrontRegardless()
        if self.ready:
            self.evaluateRollExpression(self.pending_expression)

    @objc.python_method
    def evaluateRollExpression(self, expression: str):
        script = (
            f"if (window.arcaneApplyTheme) {{ window.arcaneApplyTheme({json.dumps(dice_theme_payload())}); }};"
            "if (window.arcanePrepareRoll) { window.arcanePrepareRoll(); }"
            f"window.arcaneRoll({json.dumps(expression)});"
        )
        self.web_view.evaluateJavaScript_completionHandler_(script, None)

    def userContentController_didReceiveScriptMessage_(self, _user_content_controller, message):
        body = message.body()
        if hasattr(body, "items"):
            payload = dict(body)
        elif hasattr(body, "objectForKey_"):
            payload = {
                key: body.objectForKey_(key)
                for key in ("type", "notation", "values", "modifier", "diceTotal", "total", "text")
                if body.objectForKey_(key) is not None
            }
        else:
            payload = {}
        message_type = str(payload.get("type", ""))
        if message_type == "ready":
            self.ready = True
            self.applyTheme()
            if self.pending_expression:
                self.evaluateRollExpression(self.pending_expression)
            return
        if message_type == "error":
            text = str(payload.get("text", "3D dice roll failed."))
            log(f"3D dice error: {text}")
            if self.result_target is not None:
                self.result_target.displayDiceRollResult_(text)
            self.scheduleHideTimer()
            return
        if message_type == "hide":
            if self.hide_timer is not None:
                self.hide_timer.invalidate()
                self.hide_timer = None
            self.panel.orderOut_(None)
            return
        if message_type != "complete":
            return

        text = str(payload.get("text", "Dice roll complete."))
        if self.result_target is not None:
            self.result_target.displayDiceRollResult_(text)
        self.scheduleHideTimer()

    @objc.python_method
    def scheduleHideTimer(self):
        if self.hide_timer is not None:
            self.hide_timer.invalidate()
        self.hide_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            12.0,
            self,
            "hide:",
            None,
            False,
        )

    def hide_(self, _timer):
        self.hide_timer = None
        self.panel.orderOut_(None)


def show_3d_dice_roll(expression: str, target) -> bool:
    global THREE_D_DICE_ROLLER
    if not DEFAULT_DICE_ROLLER_HTML.exists():
        return False
    if THREE_D_DICE_ROLLER is None:
        THREE_D_DICE_ROLLER = Dice3DRollerController.alloc().initWithHTMLPath_(str(DEFAULT_DICE_ROLLER_HTML))
        APP_RETAINED_OBJECTS.append(THREE_D_DICE_ROLLER)
    THREE_D_DICE_ROLLER.showRoll_target_(str(expression), target)
    return True


SPELL_LEVEL_ORDER = (
    "Cantrip",
    "1st Level",
    "2nd Level",
    "3rd Level",
    "4th Level",
    "5th Level",
    "6th Level",
    "7th Level",
    "8th Level",
    "9th Level",
)

SPELL_SCHOOL_ORDER = (
    "Abjuration",
    "Conjuration",
    "Divination",
    "Enchantment",
    "Evocation",
    "Illusion",
    "Necromancy",
    "Transmutation",
)


def spell_level_values(spells: list[Spell]) -> list[str]:
    values = {spell.level for spell in spells if spell.level}
    return [level for level in SPELL_LEVEL_ORDER if level in values]


def spell_school_values(spells: list[Spell]) -> list[str]:
    values = {spell.school for spell in spells if spell.school}
    ordered = [school for school in SPELL_SCHOOL_ORDER if school in values]
    extras = sorted(values - set(SPELL_SCHOOL_ORDER), key=normalize)
    return [*ordered, *extras]


def search_spells(
    query: str,
    spells: list[Spell],
    limit: int | None = 8,
    level_filter: str | None = None,
    school_filter: str | None = None,
) -> list[Spell]:
    filtered_spells = [
        spell
        for spell in spells
        if (not level_filter or spell.level == level_filter)
        and (not school_filter or spell.school == school_filter)
    ]
    normalized_query = normalize_transcript_for_matching(query)
    if not normalized_query:
        results = sorted(filtered_spells, key=lambda spell: normalize(spell.name))
        return results if limit is None else results[:limit]

    ranked: list[tuple[float, int, str, Spell]] = []
    compact_query = normalized_query.replace(" ", "")
    for spell in filtered_spells:
        names = [spell.name, spell.italian_name, *spell.aliases]
        best_score = 0.0
        best_length = 9999
        for name in names:
            normalized_name = normalize(name)
            if not normalized_name:
                continue
            compact_name = normalized_name.replace(" ", "")
            if normalized_name == normalized_query:
                score = 1.0
            elif normalized_name.startswith(normalized_query):
                score = 0.94
            elif normalized_query in normalized_name:
                score = 0.86
            elif compact_query and compact_query in compact_name:
                score = 0.82
            else:
                score = SequenceMatcher(None, normalized_query, normalized_name).ratio() * 0.78
            if score > best_score or (score == best_score and len(normalized_name) < best_length):
                best_score = score
                best_length = len(normalized_name)

        if best_score >= 0.45:
            ranked.append((best_score, best_length, spell.name, spell))

    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    results = [spell for _score, _length, _name, spell in ranked]
    return results if limit is None else results[:limit]


def log(message: str, persist: bool = True):
    line = f"[Arcane Manager] {message}"
    print(line, flush=True)
    if not persist:
        return
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not LOG_FILE.exists():
            LOG_FILE.touch(mode=0o600)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        LOG_FILE.chmod(0o600)
    except OSError:
        pass


def make_label(text: str, frame: tuple[int, int, int, int], size: float, bold: bool = False):
    label = NSTextField.labelWithString_(text)
    label.setFrame_(NSMakeRect(*frame))
    label.setTextColor_(theme_color("text_strong"))
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    return label


def make_multiline(label: NSTextField):
    label.setLineBreakMode_(0)
    label.setUsesSingleLineMode_(False)
    return label


def ui_color(red: float, green: float, blue: float, alpha: float = 1.0):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(red, green, blue, alpha)


def theme_color(name: str, alpha: float = 1.0):
    red, green, blue = THEME_RGB[name]
    return ui_color(red, green, blue, alpha)


def condition_color(condition: str, alpha: float = 1.0):
    red, green, blue = CONDITION_COLOR_VALUES.get(condition, (0.86, 0.86, 0.88))
    return ui_color(red, green, blue, alpha)


def normalized_conditions(combatant: dict[str, Any]) -> list[str]:
    raw_conditions = combatant.get("conditions", [])
    if isinstance(raw_conditions, str):
        raw_conditions = [raw_conditions]
    if not isinstance(raw_conditions, list):
        return []
    cleaned = []
    for condition in raw_conditions:
        name = str(condition).strip()
        if name in CONDITION_OPTIONS and name not in cleaned:
            cleaned.append(name)
    return cleaned


def combatant_is_dead(combatant: dict[str, Any]) -> bool:
    try:
        hp = int(str(combatant.get("hp") or "").strip())
    except ValueError:
        return False
    return hp == 0


def combatant_status_label(combatant: dict[str, Any]) -> str:
    if combatant_is_dead(combatant):
        return "Dead"
    conditions = normalized_conditions(combatant)
    return ", ".join(conditions) if conditions else "Normal"


def style_layer(view, background=None, border=None, radius: float = 10.0, border_width: float = 1.0):
    view.setWantsLayer_(True)
    layer = view.layer()
    layer.setCornerRadius_(radius)
    layer.setMasksToBounds_(True)
    if background is not None:
        layer.setBackgroundColor_(background.CGColor())
    if border is not None:
        layer.setBorderColor_(border.CGColor())
        layer.setBorderWidth_(border_width)


def style_text_input(field):
    placeholder = field.placeholderString()
    cell = PaddedCenteredTextFieldCell.alloc().initTextCell_(str(field.stringValue()))
    if placeholder is not None:
        cell.setPlaceholderString_(placeholder)
    cell.setScrollable_(True)
    cell.setFont_(NSFont.systemFontOfSize_(14))
    cell.setEditable_(True)
    cell.setSelectable_(True)
    field.setBezeled_(True)
    field.setBordered_(False)
    field.setDrawsBackground_(True)
    field.setCell_(cell)
    field.setEditable_(True)
    field.setSelectable_(True)
    field.setBackgroundColor_(theme_color("surface_soft"))
    field.setFocusRingType_(1)
    field.setTextColor_(theme_color("text"))
    field.setFont_(NSFont.systemFontOfSize_(14))
    field.setUsesSingleLineMode_(True)
    field.cell().setScrollable_(True)
    style_layer(field, theme_color("surface_soft"), theme_color("border"), 8, 1)


def style_number_input(field):
    cell = CenteredTextFieldCell.alloc().initTextCell_(str(field.stringValue()))
    cell.setAlignment_(1)
    cell.setScrollable_(True)
    cell.setFont_(NSFont.systemFontOfSize_(15))
    field.setCell_(cell)
    field.setBezeled_(False)
    field.setBordered_(False)
    field.setDrawsBackground_(True)
    field.setEditable_(True)
    field.setSelectable_(True)
    field.setAlignment_(1)
    field.setBackgroundColor_(theme_color("surface"))
    field.setFocusRingType_(1)
    field.setTextColor_(theme_color("text"))
    field.setFont_(NSFont.systemFontOfSize_(15))
    field.setUsesSingleLineMode_(True)
    field.cell().setScrollable_(True)
    style_layer(field, theme_color("surface"), theme_color("border"), 8, 1)


def draw_text(text: str, x: float, y: float, size: float = 13, color=None, bold: bool = False):
    attributes = {
        NSFontAttributeName: NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size),
        NSForegroundColorAttributeName: color or theme_color("text_strong"),
    }
    NSString.stringWithString_(str(text)).drawAtPoint_withAttributes_(NSMakePoint(x, y), attributes)


def text_attributes(size: float = 13, color=None, bold: bool = False):
    return {
        NSFontAttributeName: NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size),
        NSForegroundColorAttributeName: color or theme_color("text_strong"),
    }


def text_width(text: str, attributes) -> float:
    return NSString.stringWithString_(str(text)).sizeWithAttributes_(attributes).width


def fit_text_to_width(text: str, width: float, attributes) -> str:
    text = str(text)
    if width <= 0:
        return ""
    if text_width(text, attributes) <= width:
        return text
    suffix = "..."
    if text_width(suffix, attributes) > width:
        return ""
    low = 0
    high = len(text)
    best = suffix
    while low <= high:
        mid = (low + high) // 2
        candidate = text[:mid].rstrip() + suffix
        if text_width(candidate, attributes) <= width:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best


def draw_fitted_text(text: str, rect, size: float = 13, color=None, bold: bool = False):
    attributes = text_attributes(size, color, bold)
    fitted = fit_text_to_width(text, rect.size.width, attributes)
    NSString.stringWithString_(fitted).drawInRect_withAttributes_(rect, attributes)


def draw_right_fitted_text(text: str, rect, size: float = 13, color=None, bold: bool = False):
    attributes = text_attributes(size, color, bold)
    fitted = fit_text_to_width(text, rect.size.width, attributes)
    fitted_width = min(rect.size.width, text_width(fitted, attributes))
    draw_rect = NSMakeRect(rect.origin.x + rect.size.width - fitted_width, rect.origin.y, fitted_width, rect.size.height)
    NSString.stringWithString_(fitted).drawInRect_withAttributes_(draw_rect, attributes)


def draw_right_fitted_text_centered(text: str, rect, size: float = 13, color=None, bold: bool = False):
    attributes = text_attributes(size, color, bold)
    fitted = fit_text_to_width(text, rect.size.width, attributes)
    string = NSString.stringWithString_(fitted)
    text_size = string.sizeWithAttributes_(attributes)
    fitted_width = min(rect.size.width, text_size.width)
    draw_rect = NSMakeRect(
        rect.origin.x + rect.size.width - fitted_width,
        rect.origin.y + (rect.size.height - text_size.height) / 2,
        fitted_width,
        text_size.height,
    )
    string.drawInRect_withAttributes_(draw_rect, attributes)


def draw_centered_text_in_rect(text: str, rect, size: float = 13, color=None, bold: bool = False):
    attributes = text_attributes(size, color, bold)
    string = NSString.stringWithString_(str(text))
    text_size = string.sizeWithAttributes_(attributes)
    draw_rect = NSMakeRect(
        rect.origin.x + (rect.size.width - text_size.width) / 2,
        rect.origin.y + (rect.size.height - text_size.height) / 2,
        text_size.width,
        text_size.height,
    )
    string.drawInRect_withAttributes_(draw_rect, attributes)


def draw_center_fitted_text(text: str, rect, size: float = 13, color=None, bold: bool = False):
    attributes = text_attributes(size, color, bold)
    fitted = fit_text_to_width(text, rect.size.width, attributes)
    fitted_width = min(rect.size.width, text_width(fitted, attributes))
    draw_rect = NSMakeRect(rect.origin.x + (rect.size.width - fitted_width) / 2, rect.origin.y, fitted_width, rect.size.height)
    NSString.stringWithString_(fitted).drawInRect_withAttributes_(draw_rect, attributes)


def point_in_rect(point, rect) -> bool:
    return (
        rect.origin.x <= point.x <= rect.origin.x + rect.size.width
        and rect.origin.y <= point.y <= rect.origin.y + rect.size.height
    )


def icon_image(name: str):
    filename = name
    if name in CLASS_ICON_FILES:
        filename = CLASS_ICON_FILES[name]
    elif name == "Monster":
        filename = MONSTER_ICON_FILE
    path = DEFAULT_ICON_DIR / filename
    key = str(path)
    if key not in ICON_IMAGE_CACHE:
        image = NSImage.alloc().initWithContentsOfFile_(key) if path.exists() else None
        ICON_IMAGE_CACHE[key] = image
    return ICON_IMAGE_CACHE.get(key)


def draw_icon(name: str, rect):
    image = icon_image(name)
    if image is None:
        return False
    image.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
        rect,
        NSMakeRect(0, 0, 0, 0),
        NSCompositingOperationSourceOver,
        1.0,
        True,
        None,
    )
    return True


def draw_rounded_rect(rect, fill, stroke=None, radius: float = 8, stroke_width: float = 1):
    path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius)
    fill.set()
    path.fill()
    if stroke is not None:
        stroke.set()
        path.setLineWidth_(stroke_width)
        path.stroke()


def draw_segmented_rounded_bar(rect, segments: list[tuple[float, Any]], background, radius: float = 4):
    path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius)
    NSGraphicsContext.saveGraphicsState()
    path.addClip()
    background.set()
    NSBezierPath.bezierPathWithRect_(rect).fill()
    cursor_x = rect.origin.x
    for width, color in segments:
        segment_w = max(0, min(width, rect.origin.x + rect.size.width - cursor_x))
        if segment_w <= 0:
            continue
        color.set()
        NSBezierPath.bezierPathWithRect_(NSMakeRect(cursor_x, rect.origin.y, segment_w, rect.size.height)).fill()
        cursor_x += segment_w
    NSGraphicsContext.restoreGraphicsState()


def ellipsize(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return "." * max_chars
    return text[: max_chars - 3].rstrip() + "..."


class SearchResultButton(NSButton):
    row_kind = objc.ivar()
    primary_text = objc.ivar()
    secondary_text = objc.ivar()
    hp_text = objc.ivar()
    ac_text = objc.ivar()
    cr_text = objc.ivar()
    meta_text = objc.ivar()

    def initWithFrame_(self, frame):
        self = objc.super(SearchResultButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self.row_kind = ""
        self.primary_text = ""
        self.secondary_text = ""
        self.hp_text = ""
        self.ac_text = ""
        self.cr_text = ""
        self.meta_text = ""
        self.setBordered_(False)
        self.setTitle_("")
        return self

    def configureMonsterResult_(self, creature: Creature):
        self.row_kind = "monster"
        self.primary_text = creature.name
        self.secondary_text = ""
        self.hp_text = f"HP {creature.hp}"
        self.ac_text = f"AC {display_ac(creature.ac)}"
        self.cr_text = f"CR {creature.cr}"
        self.meta_text = ""
        self.setToolTip_(creature_summary(creature))
        self.setNeedsDisplay_(True)

    def configureSpellResult_(self, spell: Spell):
        self.row_kind = "spell"
        self.primary_text = spell.name
        self.secondary_text = spell.italian_name if normalize(spell.italian_name) != normalize(spell.name) else ""
        self.hp_text = ""
        self.ac_text = ""
        self.cr_text = ""
        self.meta_text = " | ".join(part for part in (spell.level, spell.school) if part)
        tooltip_parts = [spell.name]
        if self.secondary_text:
            tooltip_parts.append(f"({self.secondary_text})")
        if self.meta_text:
            tooltip_parts.append(f"- {self.meta_text}")
        self.setToolTip_(" ".join(tooltip_parts))
        self.setNeedsDisplay_(True)

    def drawRect_(self, _rect):
        bounds = self.bounds()
        highlighted = self.isHighlighted()
        fill = theme_color("surface_hover") if highlighted else theme_color("surface_soft")
        stroke = theme_color("border") if highlighted else theme_color("border_soft")
        draw_rounded_rect(
            NSMakeRect(0.5, 0.5, max(1, bounds.size.width - 1), max(1, bounds.size.height - 1)),
            fill,
            stroke,
            7,
            1,
        )
        if self.row_kind == "monster":
            self._drawMonsterResult_(bounds)
        elif self.row_kind == "spell":
            self._drawSpellResult_(bounds)

    def mouseDown_(self, event):
        if self.row_kind == "monster":
            return
        objc.super(SearchResultButton, self).mouseDown_(event)

    def _drawMonsterResult_(self, bounds):
        width = bounds.size.width
        primary = theme_color("text_strong")
        muted = theme_color("muted")
        name_attrs = text_attributes(14, primary, True)
        meta_attrs = text_attributes(12.5, muted, True)
        hp_text = self.hp_text.replace("HP ", "HP: ")
        ac_text = self.ac_text.replace("AC ", "AC: ")
        cr_text = self.cr_text.replace("CR ", "CR: ")
        ac_width = text_width(ac_text, meta_attrs)
        hp_width = text_width(hp_text, meta_attrs)
        cr_width = text_width(cr_text, meta_attrs)
        gap = 6
        x = 14
        y = max(0, (bounds.size.height - 19) / 2 - 1)
        metadata_width = hp_width + ac_width + cr_width + gap * 3
        name_width = max(54, width - x * 2 - metadata_width)
        fitted_name = fit_text_to_width(self.primary_text, name_width, name_attrs)
        NSString.stringWithString_(fitted_name).drawInRect_withAttributes_(NSMakeRect(x, y, name_width, 20), name_attrs)
        meta_x = x + min(name_width, text_width(fitted_name, name_attrs)) + gap
        NSString.stringWithString_(hp_text).drawInRect_withAttributes_(NSMakeRect(meta_x, y + 1, hp_width, 19), meta_attrs)
        NSString.stringWithString_(ac_text).drawInRect_withAttributes_(NSMakeRect(meta_x + hp_width + gap, y + 1, ac_width, 19), meta_attrs)
        NSString.stringWithString_(cr_text).drawInRect_withAttributes_(
            NSMakeRect(meta_x + hp_width + ac_width + gap * 2, y + 1, cr_width, 19),
            meta_attrs,
        )

    def _drawSpellResult_(self, bounds):
        width = bounds.size.width
        primary = theme_color("text")
        muted = theme_color("muted")
        gold = theme_color("gold")
        draw_fitted_text(self.primary_text, NSMakeRect(14, 7, width - 28, 17), 13.5, primary, True)
        if width >= 340 and self.meta_text:
            meta_w = min(172, max(120, width * 0.40))
            secondary_w = width - meta_w - 38
            draw_fitted_text(self.secondary_text, NSMakeRect(14, 25, secondary_w, 15), 11.5, muted, False)
            draw_right_fitted_text(self.meta_text, NSMakeRect(width - meta_w - 14, 25, meta_w, 15), 11.5, gold, True)
            return
        bottom = self.meta_text
        if self.secondary_text and self.meta_text:
            bottom = f"{self.secondary_text} - {self.meta_text}"
        elif self.secondary_text:
            bottom = self.secondary_text
        draw_fitted_text(bottom, NSMakeRect(14, 25, width - 28, 15), 11.5, muted, False)


def color_from_hex(value: str, fallback=None):
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        return fallback or theme_color("text")
    try:
        red = int(text[0:2], 16) / 255.0
        green = int(text[2:4], 16) / 255.0
        blue = int(text[4:6], 16) / 255.0
    except ValueError:
        return fallback or theme_color("text")
    return ui_color(red, green, blue, 1.0)


class AdventureTreeButton(NSButton):
    display_name = objc.ivar()
    node_path = objc.ivar()
    depth = objc.ivar()
    is_dir = objc.ivar()
    is_expanded = objc.ivar()
    is_selected = objc.ivar()
    color_hex = objc.ivar()

    def initWithFrame_(self, frame):
        self = objc.super(AdventureTreeButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self.display_name = ""
        self.node_path = ""
        self.depth = 0
        self.is_dir = False
        self.is_expanded = False
        self.is_selected = False
        self.color_hex = ""
        self.setBordered_(False)
        self.setTitle_("")
        return self

    def configureName_path_depth_isDir_expanded_selected_color_(
        self,
        name,
        path,
        depth,
        is_dir,
        expanded,
        selected,
        color_hex,
    ):
        self.display_name = str(name)
        self.node_path = str(path)
        self.depth = int(depth)
        self.is_dir = bool(is_dir)
        self.is_expanded = bool(expanded)
        self.is_selected = bool(selected)
        self.color_hex = str(color_hex or "")
        self.setToolTip_(str(path))
        self.setNeedsDisplay_(True)

    def menuForEvent_(self, _event):
        target = self.target()
        if target is not None and hasattr(target, "adventureContextMenuForButton_"):
            return target.adventureContextMenuForButton_(self)
        return objc.super(AdventureTreeButton, self).menuForEvent_(_event)

    def drawRect_(self, _rect):
        bounds = self.bounds()
        highlighted = self.isHighlighted()
        if self.is_selected:
            fill = theme_color("selection")
        elif highlighted:
            fill = theme_color("surface_hover")
        else:
            fill = None
        if fill is not None:
            draw_rounded_rect(
                NSMakeRect(4, 1, max(1, bounds.size.width - 8), max(1, bounds.size.height - 2)),
                fill,
                None,
                5,
                0,
            )

        indent = 10 + int(self.depth) * 18
        text_x = indent + 20
        text_color = color_from_hex(self.color_hex, theme_color("text"))
        if self.is_selected:
            text_color = theme_color("text_strong")
        muted = theme_color("muted")

        if self.is_dir:
            arrow = "⌄" if self.is_expanded else "›"
            draw_center_fitted_text(arrow, NSMakeRect(indent, 5, 14, 16), 14, muted, True)
            draw_fitted_text(self.display_name, NSMakeRect(text_x, 5, bounds.size.width - text_x - 10, 18), 13, text_color, True)
        else:
            draw_fitted_text(self.display_name, NSMakeRect(text_x, 5, bounds.size.width - text_x - 10, 18), 13, text_color, False)


class StatBlockAbilityButton(NSButton):
    ability_name = objc.ivar()
    score_text = objc.ivar()
    bonus_text = objc.ivar()
    roll_expression = objc.ivar()
    roll_target = objc.ivar()

    def initWithFrame_(self, frame):
        self = objc.super(StatBlockAbilityButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self.ability_name = ""
        self.score_text = ""
        self.bonus_text = ""
        self.roll_expression = ""
        self.roll_target = None
        self.setBordered_(False)
        self.setTitle_("")
        return self

    def configure_stat(self, name, score, bonus, target):
        bonus_value = int(bonus)
        self.ability_name = str(name)
        self.score_text = str(score)
        self.bonus_text = f"{bonus_value:+d}"
        self.roll_expression = f"1d20+{bonus_value}" if bonus_value >= 0 else f"1d20{bonus_value}"
        self.roll_target = target
        self.setToolTip_(f"Roll {self.ability_name} {self.roll_expression}")
        self.setNeedsDisplay_(True)

    def _bonusRect(self):
        bounds = self.bounds()
        inset = 2
        return NSMakeRect(inset, bounds.size.height * 0.27, bounds.size.width - inset * 2, bounds.size.height * 0.71)

    def drawRect_(self, _rect):
        bounds = self.bounds()
        highlighted = self.isHighlighted()
        fill = theme_color("surface_soft")
        stroke = theme_color("border") if highlighted else theme_color("border_soft")
        circle_fill = theme_color("panel_alt")
        text = theme_color("text_strong")
        muted = theme_color("muted")
        green = theme_color("dice")

        rect = self._bonusRect()
        draw_rounded_rect(rect, fill, stroke, 7, 1.25)
        circle_side = min(bounds.size.width - 4, bounds.size.height * 0.43)
        circle = NSMakeRect(
            (bounds.size.width - circle_side) / 2,
            1,
            circle_side,
            circle_side,
        )
        oval = NSBezierPath.bezierPathWithOvalInRect_(circle)
        circle_fill.set()
        oval.fill()

        stroke.set()
        oval.setLineWidth_(1.25)
        oval.stroke()

        draw_center_fitted_text(self.ability_name, NSMakeRect(5, bounds.size.height - 20, bounds.size.width - 10, 14), 9.5, muted, True)
        draw_center_fitted_text(self.bonus_text, NSMakeRect(5, bounds.size.height * 0.46, bounds.size.width - 10, 22), 16, green, True)
        draw_center_fitted_text(self.score_text, NSMakeRect(5, circle.origin.y + (circle.size.height - 19) / 2, bounds.size.width - 10, 20), 14, text, True)

    def mouseDown_(self, event):
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        if self.roll_expression and self.roll_target is not None and point_in_rect(point, self._bonusRect()):
            self.roll_target.performSelectorOnMainThread_withObject_waitUntilDone_(
                "rollDice:",
                self.roll_expression,
                False,
            )
            return
        objc.super(StatBlockAbilityButton, self).mouseDown_(event)


class RowAddButton(NSButton):
    def initWithFrame_(self, frame):
        self = objc.super(RowAddButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self.setBordered_(False)
        self.setTitle_("")
        return self

    def drawRect_(self, _rect):
        bounds = self.bounds()
        highlighted = self.isHighlighted()
        icon_color = theme_color("text_strong") if highlighted else theme_color("text")
        fill = theme_color("surface_hover") if highlighted else theme_color("surface")
        stroke = theme_color("border") if highlighted else theme_color("border_soft")
        side = min(30, bounds.size.width, bounds.size.height)
        draw_rounded_rect(
            NSMakeRect((bounds.size.width - side) / 2, (bounds.size.height - side) / 2, side, side),
            fill,
            stroke,
            8,
            1,
        )
        attributes = text_attributes(16, icon_color, True)
        glyph = NSString.stringWithString_("+")
        glyph_size = glyph.sizeWithAttributes_(attributes)
        glyph.drawAtPoint_withAttributes_(
            NSMakePoint(
                (bounds.size.width - glyph_size.width) / 2,
                (bounds.size.height - glyph_size.height) / 2 - 1,
            ),
            attributes,
        )


class StyledPopUpButton(NSPopUpButton):
    def initWithFrame_(self, frame):
        self = objc.super(StyledPopUpButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self.setBordered_(False)
        return self

    def drawRect_(self, _rect):
        bounds = self.bounds()
        highlighted = self.isHighlighted()
        fill = theme_color("surface_hover") if highlighted else theme_color("surface")
        stroke = theme_color("border") if highlighted else theme_color("border_soft")
        draw_rounded_rect(
            NSMakeRect(0.5, 0.5, max(1, bounds.size.width - 1), max(1, bounds.size.height - 1)),
            fill,
            stroke,
            7,
            1,
        )
        item = self.selectedItem()
        title = str(item.title()) if item is not None else str(self.title())
        draw_fitted_text(title, NSMakeRect(12, 8, max(20, bounds.size.width - 42), 18), 13, theme_color("text"), True)
        draw_right_fitted_text("⌄", NSMakeRect(bounds.size.width - 28, 7, 16, 18), 14, theme_color("muted"), True)


MONSTER_RESULT_ROW_HEIGHT = 42
MONSTER_RESULT_ROW_STEP = 50
SPELL_RESULT_ROW_HEIGHT = 42
SPELL_RESULT_ROW_STEP = 50


class CombatTrackerView(NSView):
    combatants: list[dict[str, Any]]
    current_turn_index: int
    name_rects: list[tuple[Any, int]]
    hp_button_rects: list[tuple[Any, int]]
    status_rects: list[tuple[Any, int]]
    target: Any
    tracking_area: Any

    def initWithFrame_(self, frame):
        self = objc.super(CombatTrackerView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.combatants = []
        self.current_turn_index = 0
        self.name_rects = []
        self.hp_button_rects = []
        self.status_rects = []
        self.target = None
        self.tracking_area = None
        return self

    def isFlipped(self):
        return True

    def setTarget_(self, target):
        self.target = target

    def setPayload_(self, payload):
        self.combatants = list(payload.get("combatants", []))
        self.current_turn_index = int(payload.get("current_turn_index", 0))
        width = max(780, self.frame().size.width)
        height = max(420, 144 + len(self.combatants) * 70 + 96)
        self.setFrame_(NSMakeRect(0, 0, width, height))
        self.setNeedsDisplay_(True)

    def updateTrackingAreas(self):
        if self.tracking_area is not None:
            self.removeTrackingArea_(self.tracking_area)
        self.tracking_area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            NSTrackingMouseMoved
            | NSTrackingMouseEnteredAndExited
            | NSTrackingActiveAlways
            | NSTrackingInVisibleRect,
            self,
            None,
        )
        self.addTrackingArea_(self.tracking_area)
        objc.super(CombatTrackerView, self).updateTrackingAreas()

    def _hp_values(self, combatant: dict[str, Any]) -> tuple[int | None, int | None]:
        try:
            current = int(str(combatant.get("hp") or "").strip())
        except ValueError:
            current = None
        try:
            maximum = int(str(combatant.get("max_hp") or "").strip())
        except ValueError:
            maximum = None
        return current, maximum

    def _hit_test(self, event) -> tuple[str, int, int | None] | None:
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        for rect, index in self.status_rects:
            if point_in_rect(point, rect):
                return ("status", index, None)
        for rect, index in self.hp_button_rects:
            if point_in_rect(point, rect):
                return ("hp", index, None)
        for rect, index in self.name_rects:
            if point_in_rect(point, rect):
                return ("name", index, None)
        return None

    def mouseMoved_(self, event):
        hit = self._hit_test(event)
        if hit is not None:
            NSCursor.pointingHandCursor().set()
        else:
            NSCursor.arrowCursor().set()

    def mouseExited_(self, _event):
        NSCursor.arrowCursor().set()

    def mouseDown_(self, event):
        hit = self._hit_test(event)
        if hit is not None and hit[0] == "name":
            index = hit[1]
            if self.target is not None:
                self.target.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "openCombatantIndex:",
                    index,
                    False,
                )
            return
        if hit is not None and hit[0] == "hp":
            _kind, index, _delta = hit
            if self.target is not None:
                point = event.locationInWindow()
                self.target.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "openCombatantHpMenu:",
                    {"index": index, "x": float(point.x), "y": float(point.y)},
                    False,
                )
            return
        if hit is not None and hit[0] == "status":
            _kind, index, _delta = hit
            if self.target is not None:
                point = self.convertPoint_fromView_(event.locationInWindow(), None)
                self.target.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "openCombatantStatusMenu:",
                    {"index": index, "x": float(point.x), "y": float(point.y)},
                    False,
                )
            return
        if self.target is not None:
            self.target.performSelectorOnMainThread_withObject_waitUntilDone_(
                "closeCombatantHpMenu:",
                None,
                False,
            )
        objc.super(CombatTrackerView, self).mouseDown_(event)

    def drawRect_(self, _rect):
        bounds = self.bounds()
        theme_color("panel").set()
        NSBezierPath.bezierPathWithRect_(bounds).fill()

        muted = theme_color("muted")
        card_border = theme_color("border_soft")
        current_border = theme_color("border")
        green = theme_color("dice")
        temp_blue = theme_color("blue_temp")
        pink = theme_color("monster")
        red = theme_color("danger")
        dead_red = theme_color("danger")
        white = theme_color("text_strong")

        left = 24
        width = bounds.size.width - 48
        right = left + width
        status_w = 116 if width >= 900 else 98
        status_x = right - status_w - 18
        ac_w = 44
        ac_x = status_x - ac_w - 18
        name_x = left + 132
        max_display_name = "Adult Green Dragon"
        max_name_chars = len(max_display_name)
        name_w = max_name_chars * 8 + 8
        hp_text_x = name_x + name_w + 16
        hp_text_w = 76
        hp_action_w = 44
        hp_action_x = ac_x - hp_action_w - 18
        bar_x = hp_text_x + hp_text_w + 14
        bar_right = hp_action_x - 18
        bar_w = max(110, bar_right - bar_x)

        if not self.combatants:
            draw_text("No combatants yet.", left + 24, 36, 18, white, True)
            draw_text("Select a party, add creatures, then start the fight.", left + 24, 66, 13, muted, False)
            self.name_rects = []
            self.hp_button_rects = []
            self.status_rects = []
            return

        self.name_rects = []
        self.hp_button_rects = []
        self.status_rects = []
        draw_text("Init", left + 30, 22, 11, muted, True)
        draw_text("Type", left + 86, 22, 11, muted, True)
        draw_text("Name", name_x, 22, 11, muted, True)
        draw_right_fitted_text_centered("HP", NSMakeRect(hp_text_x, 18, hp_text_w, 20), 11, muted, True)
        draw_centered_text_in_rect("AC", NSMakeRect(ac_x, 18, ac_w, 20), 11, muted, True)
        draw_text("Status", status_x + 10, 22, 11, muted, True)

        row_y = 54
        row_h = 56
        gap = 12
        for index, combatant in enumerate(self.combatants):
            initiative = int(combatant.get("initiative") or 0)
            rect = NSMakeRect(left, row_y, width, row_h)
            is_current = index == self.current_turn_index
            is_down = self._hp_values(combatant)[0] is not None and self._hp_values(combatant)[0] <= 0
            is_dead = combatant_is_dead(combatant)
            conditions = normalized_conditions(combatant)
            row_fill = theme_color("surface_soft", 0.62 if is_down else 1.0)
            if conditions and not is_down:
                tint_source = condition_color(conditions[0], 1.0)
                row_fill = tint_source.colorWithAlphaComponent_(0.18)
            draw_rounded_rect(
                rect,
                row_fill,
                current_border if is_current else card_border,
                8,
                2.0 if is_current else 1.0,
            )
            draw_text(str(initiative), left + 36, row_y + 17, 17, white, True)
            if combatant.get("kind") == "Monster":
                icon_name = "Monster"
                fallback_icon = MONSTER_ICON
                fallback_color = pink
                subtitle = "Monstrosity" if not combatant.get("cr") else f"CR {combatant.get('cr')}"
                self.name_rects.append((NSMakeRect(name_x, row_y + 8, name_w, 36), index))
            else:
                class_name = str(combatant.get("class") or "Fighter")
                icon_name = class_name
                fallback_icon = CLASS_ICONS.get(class_name, "◆")
                fallback_color = white
                subtitle = class_name
            icon_rect = NSMakeRect(left + 84, row_y + 13, 26, 26)
            if not draw_icon(icon_name, icon_rect):
                draw_text(fallback_icon, left + 92, row_y + 15, 22, fallback_color, True)
            display_name = ellipsize(str(combatant.get("name") or "Unnamed"), max_name_chars)
            draw_text(display_name, name_x, row_y + 10, 14, white, True)
            draw_text(subtitle[:22], name_x, row_y + 30, 12, muted, False)

            is_monster = combatant.get("kind") == "Monster"
            bar_y = row_y + 24
            bar_h = 8
            if is_monster:
                hp_button_w = hp_action_w
                hp_button_h = 28
                hp_button_y = row_y + (row_h - hp_button_h) / 2
                hp_button_rect = NSMakeRect(hp_action_x, hp_button_y, hp_button_w, hp_button_h)
                self.hp_button_rects.append((hp_button_rect, index))
                draw_rounded_rect(
                    hp_button_rect,
                    theme_color("surface"),
                    theme_color("border"),
                    7,
                    1,
                )
                draw_centered_text_in_rect("+/-", hp_button_rect, 13, white, True)

                current_hp, max_hp = self._hp_values(combatant)
                bar_rect = NSMakeRect(bar_x, bar_y, bar_w, bar_h)
                if current_hp is not None and max_hp is not None and max_hp > 0:
                    try:
                        temp_hp = max(0, int(str(combatant.get("temp_hp") or "0")))
                    except ValueError:
                        temp_hp = 0
                    effective_max = max_hp + temp_hp
                    hp_ratio = max(0.0, min(1.0, current_hp / effective_max))
                    temp_ratio = max(0.0, min(1.0 - hp_ratio, temp_hp / effective_max))
                    fill_color = red if current_hp <= 0 else pink if current_hp / max_hp <= 0.35 else green
                    draw_segmented_rounded_bar(
                        bar_rect,
                        [
                            (bar_w * hp_ratio, fill_color),
                            (bar_w * temp_ratio, temp_blue),
                        ],
                        theme_color("panel_alt"),
                        4,
                    )
                    hp_text = f"{current_hp}/{max_hp}"
                else:
                    draw_segmented_rounded_bar(bar_rect, [], theme_color("panel_alt"), 4)
                    hp_text = "-"
                draw_right_fitted_text_centered(hp_text, NSMakeRect(hp_text_x, bar_y, hp_text_w, bar_h), 12, muted, False)
            else:
                pass

            draw_centered_text_in_rect(str(combatant.get("ac") or "?"), NSMakeRect(ac_x, row_y + 14, ac_w, 28), 15, white, False)

            status_label = combatant_status_label(combatant)
            status_color = dead_red if is_dead else condition_color(conditions[0]) if conditions else muted
            status_rect = NSMakeRect(status_x, row_y + 14, status_w, 28)
            self.status_rects.append((status_rect, index))
            draw_rounded_rect(
                status_rect,
                theme_color("surface", 0.88 if not is_down else 0.52),
                theme_color("border_soft"),
                7,
                1,
            )
            draw_center_fitted_text(status_label, NSMakeRect(status_x + 8, row_y + 19, status_w - 16, 18), 12, status_color, True)

            row_y += row_h + gap


class MainWindowController(NSObject):
    window: NSWindow
    content_view: NSView
    initiative_tab_button: NSButton
    spells_tab_button: NSButton
    dice_tab_button: NSButton
    adventure_tab_button: NSButton
    sidebar_panel: NSView
    sidebar_scroll: NSScrollView
    sidebar_content: NSView
    combat_panel: NSView
    spell_panel: NSView
    dice_panel: NSView
    adventure_panel: NSView
    sidebar_logo_label: NSTextField
    sidebar_footer_label: NSTextField
    creatures: list[Creature]
    spells: list[Spell]
    spell_lookup: dict[str, Spell]
    parties: list[dict[str, Any]]
    combatants: list[dict[str, Any]]
    monster_results: list[Creature]
    current_turn_index: int
    editing_party_index: int
    editing_characters: list[dict[str, str]]
    party_editor_panel: NSPanel
    hp_adjust_panel: NSPanel
    hp_adjust_index: int
    hp_adjust_amount_field: NSTextField
    hp_adjust_temp_field: NSTextField
    editor_party_name_field: NSTextField
    editor_character_name_field: NSTextField
    editor_character_class_popup: NSPopUpButton
    editor_character_ac_field: NSTextField
    editor_character_popup: NSPopUpButton
    editor_character_list: NSTextView
    monster_sheet_drawer: NSView
    monster_sheet_title: NSTextField
    monster_sheet_close_button: NSButton
    monster_sheet_scroll: NSScrollView
    monster_sheet_body: DiceTextView
    monster_sheet_hp_label: NSTextField
    monster_sheet_hp_field: NSTextField
    monster_sheet_save_button: NSButton
    monster_sheet_roll_label: NSTextField
    monster_sheet_ability_buttons: list[StatBlockAbilityButton]
    monster_sheet_combatant_index: int
    notes_title: NSTextField
    notes_hint: NSTextField
    notes_scroll: NSScrollView
    tracker_title: NSTextField
    party_label: NSTextField
    party_popup: NSPopUpButton
    new_party_button: NSButton
    edit_party_button: NSButton
    delete_party_button: NSButton
    start_fight_button: NSButton
    party_member_labels: list[NSTextField]
    party_member_icon_views: list[NSImageView]
    party_member_name_labels: list[NSTextField]
    party_member_class_labels: list[NSTextField]
    party_member_ac_labels: list[NSTextField]
    notes_view: NSTextView
    monster_label: NSTextField
    monster_search_field: NSTextField
    monster_cr_filter_popup: NSPopUpButton
    monster_search_button: NSButton
    monster_results_scroll: NSScrollView
    monster_results_content: FlippedView
    monster_result_buttons: list[NSButton]
    monster_add_buttons: list[NSButton]
    spell_search_field: NSTextField
    spell_level_filter_popup: NSPopUpButton
    spell_school_filter_popup: NSPopUpButton
    spell_results_scroll: NSScrollView
    spell_results_content: FlippedView
    spell_detail_title_label: NSTextField
    spell_detail_italian_label: NSTextField
    spell_detail_meta_label: NSTextField
    spell_components_label: NSTextField
    spell_component_material_label: NSTextField
    spell_v_label: NSTextField
    spell_s_label: NSTextField
    spell_m_label: NSTextField
    spell_v_box: CheckboxSquareView
    spell_s_box: CheckboxSquareView
    spell_m_box: CheckboxSquareView
    spell_stats_label: NSTextField
    spell_detail_header_views: list[Any]
    spell_result_buttons: list[NSButton]
    spell_detail_scroll: NSScrollView
    spell_detail_view: DiceTextView
    dice_title_label: NSTextField
    dice_hint_label: NSTextField
    dice_formula_label: NSTextField
    dice_result_label: NSTextField
    dice_history_title_label: NSTextField
    dice_history_scroll: NSScrollView
    dice_history_view: NSTextView
    dice_roll_button: NSButton
    dice_clear_button: NSButton
    dice_preset_buttons: list[NSButton]
    dice_pool: dict[int, int]
    adventure_vault_path: Path | None
    adventure_selected_note: Path | None
    adventure_root_node: AdventureNode | None
    adventure_flat_nodes: list[AdventureNode]
    adventure_expanded_paths: set[str]
    adventure_note_index: dict[str, list[Path]]
    adventure_asset_index: dict[str, list[Path]]
    adventure_file_colors: dict[str, str]
    adventure_tree_buttons: list[AdventureTreeButton]
    adventure_views: list[Any]
    adventure_tree_scroll: NSScrollView
    adventure_tree_content: FlippedView
    adventure_title_label: NSTextField
    adventure_status_label: NSTextField
    adventure_folder_button: NSButton
    adventure_toggle_button: NSButton
    adventure_save_button: NSButton
    adventure_dirty_label: NSTextField
    adventure_web_view: WKWebView
    adventure_editor_scroll: NSScrollView
    adventure_editor_view: NSTextView
    adventure_is_editing: bool
    adventure_dirty: bool
    adventure_last_saved_text: str
    displayed_spells: list[Spell]
    initiative_views: list[Any]
    spell_views: list[Any]
    dice_views: list[Any]
    current_tab: str
    previous_turn_button: NSButton
    next_turn_button: NSButton
    clear_tracker_button: NSButton
    tracker_scroll: NSScrollView
    tracker_view: CombatTrackerView
    party_status_label: NSTextField
    turn_label: NSTextField

    def initWithBestiary_spells_spellLookup_(self, creatures, spells, spell_lookup):
        self = objc.super(MainWindowController, self).init()
        if self is None:
            return None

        self.creatures = list(creatures)
        self.spells = list(spells)
        self.spell_lookup = dict(spell_lookup)
        self.parties = self.loadParties()
        self.combatants = []
        self.monster_results = []
        self.monster_result_buttons = []
        self.monster_add_buttons = []
        self.displayed_spells = []
        self.spell_result_buttons = []
        self.dice_preset_buttons = []
        self.dice_pool = {4: 0, 6: 0, 8: 0, 10: 0, 12: 0, 20: 0}
        self.adventure_vault_path = None
        self.adventure_selected_note = None
        self.adventure_root_node = None
        self.adventure_flat_nodes = []
        self.adventure_expanded_paths = set()
        self.adventure_note_index = {}
        self.adventure_asset_index = {}
        self.adventure_file_colors = {}
        self.adventure_tree_buttons = []
        self.adventure_views = []
        self.adventure_is_editing = False
        self.adventure_dirty = False
        self.adventure_last_saved_text = ""
        if self not in DICE_HISTORY_LISTENERS:
            DICE_HISTORY_LISTENERS.append(self)
        self.party_member_labels = []
        self.party_member_icon_views = []
        self.party_member_name_labels = []
        self.party_member_class_labels = []
        self.party_member_ac_labels = []
        self.initiative_views = []
        self.spell_views = []
        self.dice_views = []
        self.current_tab = "initiative"
        self.current_turn_index = 0
        self.round_number = 1
        self.editing_party_index = -1
        self.editing_characters = []
        self.hp_adjust_panel = None
        self.hp_adjust_index = -1
        self.hp_adjust_amount_field = None
        self.hp_adjust_temp_field = None
        self.monster_sheet_drawer = None
        self.monster_sheet_title = None
        self.monster_sheet_close_button = None
        self.monster_sheet_scroll = None
        self.monster_sheet_body = None
        self.monster_sheet_hp_label = None
        self.monster_sheet_hp_field = None
        self.monster_sheet_save_button = None
        self.monster_sheet_roll_label = None
        self.monster_sheet_ability_buttons = []
        self.monster_sheet_combatant_index = -1

        screen = NSScreen.mainScreen().visibleFrame()
        width = int(screen.size.width)
        height = int(screen.size.height)

        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
            | NSWindowStyleMaskResizable
        )
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(screen.origin.x, screen.origin.y, width, height),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("Arcane Manager")
        self.window.setMinSize_(NSMakeSize(1060, 660))
        self.window.setDelegate_(self)
        self.window.setBackgroundColor_(theme_color("app_bg"))

        self.content_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        style_layer(self.content_view, theme_color("app_bg"), None, 0)
        self.initiative_tab_button = self._make_button("Initiative Tracker", (20, height - 38, 150, 30), "showInitiativeTab:")
        self.spells_tab_button = self._make_button("Spells", (178, height - 38, 86, 30), "showSpellsTab:")
        self.dice_tab_button = self._make_button("Dice Roller", (272, height - 38, 112, 30), "showDiceTab:")
        self.adventure_tab_button = self._make_button("Adventure", (392, height - 38, 104, 30), "showAdventureTab:")
        self.sidebar_panel = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 340, height))
        style_layer(self.sidebar_panel, theme_color("panel_alt"), None, 0)
        self.sidebar_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 340, height))
        self.sidebar_scroll.setHasVerticalScroller_(True)
        self.sidebar_scroll.setAutohidesScrollers_(False)
        self.sidebar_scroll.setDrawsBackground_(False)
        self.sidebar_scroll.setBorderType_(0)
        self.sidebar_content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 340, height))
        self.sidebar_scroll.setDocumentView_(self.sidebar_content)
        self.combat_panel = NSView.alloc().initWithFrame_(NSMakeRect(360, 24, 896, height - 48))
        style_layer(self.combat_panel, theme_color("panel"), theme_color("border_soft"), 14, 1)
        self.spell_panel = NSView.alloc().initWithFrame_(NSMakeRect(20, 20, width - 40, height - 74))
        style_layer(self.spell_panel, theme_color("panel"), theme_color("border_soft"), 14, 1)
        self.dice_panel = NSView.alloc().initWithFrame_(NSMakeRect(20, 20, width - 40, height - 74))
        style_layer(self.dice_panel, theme_color("panel"), theme_color("border_soft"), 14, 1)
        self.adventure_panel = NSView.alloc().initWithFrame_(NSMakeRect(20, 20, width - 40, height - 74))
        style_layer(self.adventure_panel, theme_color("panel"), theme_color("border_soft"), 14, 1)

        self.monster_sheet_drawer = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 360, height - 48))
        style_layer(self.monster_sheet_drawer, theme_color("panel_alt"), theme_color("border_soft"), 12, 1)
        self.monster_sheet_drawer.setHidden_(True)
        self.monster_sheet_title = make_label("", (0, 0, 260, 36), 24, True)
        self.monster_sheet_title.setUsesSingleLineMode_(True)
        self.monster_sheet_title.setLineBreakMode_(4)
        self.monster_sheet_close_button = self._make_button("Close", (0, 0, 72, 28), "closeMonsterSheet:")
        self.monster_sheet_hp_label = make_label("Current HP", (0, 0, 90, 24), 13, True)
        self.monster_sheet_hp_field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 72, 26))
        self.monster_sheet_save_button = self._make_button("Save HP", (0, 0, 84, 26), "saveMonsterHp:")
        self.monster_sheet_roll_label = make_label("", (0, 0, 300, 22), 12, True)
        self.monster_sheet_roll_label.setTextColor_(theme_color("dice"))
        self.monster_sheet_hp_label.setHidden_(True)
        self.monster_sheet_hp_field.setHidden_(True)
        self.monster_sheet_save_button.setHidden_(True)
        self.monster_sheet_roll_label.setHidden_(True)
        self.monster_sheet_ability_buttons = []
        for _index in range(6):
            button = StatBlockAbilityButton.alloc().initWithFrame_(NSMakeRect(0, 0, 44, 72))
            self.monster_sheet_ability_buttons.append(button)
        self.monster_sheet_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 300, 400))
        self.monster_sheet_scroll.setHasVerticalScroller_(True)
        self.monster_sheet_scroll.setAutohidesScrollers_(False)
        self.monster_sheet_scroll.setDrawsBackground_(False)
        self.monster_sheet_scroll.setBorderType_(0)
        self.monster_sheet_body = DiceTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 300, 400))
        self.monster_sheet_body.setFont_(NSFont.systemFontOfSize_(13))
        self.monster_sheet_body.setTextColor_(theme_color("text"))
        self.monster_sheet_body.setRollTarget_(self)
        self.monster_sheet_body.setSpellTarget_(self)
        self.monster_sheet_scroll.setDocumentView_(self.monster_sheet_body)
        for view in (
            self.monster_sheet_title,
            self.monster_sheet_close_button,
            self.monster_sheet_scroll,
        ):
            self.monster_sheet_drawer.addSubview_(view)
        for button in self.monster_sheet_ability_buttons:
            self.monster_sheet_drawer.addSubview_(button)

        self.notes_title = make_label("Initiative Tracker", (0, 0, 220, 28), 18, True)
        self.notes_hint = make_label("Combat Round Tracker", (0, 0, 220, 20), 12)
        self.notes_hint.setTextColor_(theme_color("muted"))
        self.sidebar_logo_label = make_label("✦", (0, 0, 36, 36), 20, True)
        self.sidebar_logo_label.setAlignment_(1)
        style_layer(self.sidebar_logo_label, theme_color("selection"), theme_color("link"), 10, 1)
        self.notes_title.setHidden_(True)
        self.notes_hint.setHidden_(True)
        self.sidebar_logo_label.setHidden_(True)
        self.sidebar_footer_label = make_label("", (0, 0, 300, 24), 13)
        self.sidebar_footer_label.setTextColor_(theme_color("muted"))
        self.sidebar_footer_label.setHidden_(True)
        self.notes_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        self.notes_scroll.setHasVerticalScroller_(True)
        self.notes_scroll.setAutohidesScrollers_(False)
        self.notes_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        self.notes_view.setFont_(NSFont.systemFontOfSize_(14))
        self.notes_view.setTextColor_(theme_color("text"))
        self.notes_view.setBackgroundColor_(theme_color("surface"))
        self.notes_scroll.setDocumentView_(self.notes_view)
        self.notes_scroll.setHidden_(True)

        self.tracker_title = make_label("Round 1", (0, 0, 300, 28), 18, True)
        self.party_label = make_label("Party", (0, 0, 60, 24), 16, True)
        self.party_popup = StyledPopUpButton.alloc().initWithFrame_(NSMakeRect(0, 0, 180, 28))
        self.party_popup.setTarget_(self)
        self.party_popup.setAction_("selectParty:")
        self.new_party_button = self._make_button("+", (0, 0, 32, 28), "newParty:")
        self.edit_party_button = self._make_button("Edit", (0, 0, 64, 28), "editParty:")
        self.delete_party_button = self._make_button("Delete", (0, 0, 70, 28), "deleteParty:")
        self.start_fight_button = self._make_button("Go", (0, 0, 34, 28), "startFight:")
        self.start_fight_button.setToolTip_("Add party to initiative")

        self.party_status_label = make_multiline(make_label("", (0, 0, 300, 40), 11))
        self.party_status_label.setTextColor_(theme_color("muted"))

        for _index in range(6):
            icon_view = NSImageView.alloc().initWithFrame_(NSMakeRect(0, 0, 20, 20))
            icon_view.setHidden_(True)
            self.party_member_icon_views.append(icon_view)
            label = make_label("", (0, 0, 100, 38), 13, True)
            label.setHidden_(True)
            style_layer(label, theme_color("surface"), theme_color("border_soft"), 8, 1)
            self.party_member_labels.append(label)
            name_label = make_label("", (0, 0, 80, 20), 13, True)
            class_label = make_label("", (0, 0, 80, 20), 12, True)
            ac_label = make_label("", (0, 0, 56, 20), 12, True)
            for row_label in (name_label, class_label, ac_label):
                row_label.setUsesSingleLineMode_(True)
                row_label.setLineBreakMode_(4)
                row_label.setHidden_(True)
            self.party_member_name_labels.append(name_label)
            self.party_member_class_labels.append(class_label)
            self.party_member_ac_labels.append(ac_label)

        self.monster_label = make_label("Creatures", (0, 0, 100, 24), 16, True)
        self.monster_search_field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 260, 26))
        self.monster_search_field.setPlaceholderString_("Search SRD monster")
        self.monster_search_field.setTarget_(self)
        self.monster_search_field.setAction_("searchMonsters:")
        self.monster_search_field.setDelegate_(self)
        style_text_input(self.monster_search_field)
        self.monster_cr_filter_popup = StyledPopUpButton.alloc().initWithFrame_(NSMakeRect(0, 0, 120, 28))
        self.monster_cr_filter_popup.addItemWithTitle_("Any CR")
        for cr_value in creature_cr_values(self.creatures):
            self.monster_cr_filter_popup.addItemWithTitle_(f"CR {cr_value}")
        self.monster_cr_filter_popup.setTarget_(self)
        self.monster_cr_filter_popup.setAction_("searchMonsters:")
        self.monster_search_button = self._make_button("Search", (0, 0, 80, 26), "searchMonsters:")
        self.monster_search_button.setHidden_(True)
        self.monster_results_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        self.monster_results_scroll.setHasVerticalScroller_(True)
        self.monster_results_scroll.setAutohidesScrollers_(False)
        self.monster_results_scroll.setDrawsBackground_(False)
        self.monster_results_scroll.setBorderType_(0)
        self.monster_results_content = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        self.monster_results_scroll.setDocumentView_(self.monster_results_content)

        self.spell_search_field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 260, 28))
        self.spell_search_field.setPlaceholderString_("Search spells in English or Italian")
        self.spell_search_field.setDelegate_(self)
        style_text_input(self.spell_search_field)
        self.spell_level_filter_popup = StyledPopUpButton.alloc().initWithFrame_(NSMakeRect(0, 0, 120, 28))
        self.spell_level_filter_popup.addItemWithTitle_("Any Level")
        for level in spell_level_values(self.spells):
            self.spell_level_filter_popup.addItemWithTitle_(level)
        self.spell_level_filter_popup.setTarget_(self)
        self.spell_level_filter_popup.setAction_("refreshSpellResults:")
        self.spell_school_filter_popup = StyledPopUpButton.alloc().initWithFrame_(NSMakeRect(0, 0, 150, 28))
        self.spell_school_filter_popup.addItemWithTitle_("Any School")
        for school in spell_school_values(self.spells):
            self.spell_school_filter_popup.addItemWithTitle_(school)
        self.spell_school_filter_popup.setTarget_(self)
        self.spell_school_filter_popup.setAction_("refreshSpellResults:")
        self.spell_results_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        self.spell_results_scroll.setHasVerticalScroller_(True)
        self.spell_results_scroll.setAutohidesScrollers_(False)
        self.spell_results_scroll.setDrawsBackground_(False)
        self.spell_results_scroll.setBorderType_(0)
        self.spell_results_content = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        self.spell_results_scroll.setDocumentView_(self.spell_results_content)
        self.spell_detail_title_label = make_label("", (0, 0, 320, 34), 26, True)
        self.spell_detail_title_label.setLineBreakMode_(4)
        self.spell_detail_italian_label = make_label("", (0, 0, 320, 22), 15)
        italic_font = NSFontManager.sharedFontManager().convertFont_toHaveTrait_(
            NSFont.systemFontOfSize_(15),
            NSItalicFontMask,
        )
        self.spell_detail_italian_label.setFont_(italic_font)
        self.spell_detail_italian_label.setTextColor_(theme_color("muted"))
        self.spell_detail_italian_label.setLineBreakMode_(4)
        self.spell_detail_meta_label = make_label("", (0, 0, 320, 24), 15, True)
        self.spell_detail_meta_label.setTextColor_(theme_color("gold"))
        self.spell_detail_meta_label.setLineBreakMode_(4)
        self.spell_components_label = make_label("Components", (0, 0, 100, 22), 13, True)
        self.spell_components_label.setTextColor_(theme_color("text"))
        self.spell_v_label = make_label("V", (0, 0, 14, 20), 13, True)
        self.spell_s_label = make_label("S", (0, 0, 14, 20), 13, True)
        self.spell_m_label = make_label("M", (0, 0, 16, 20), 13, True)
        for label in (self.spell_v_label, self.spell_s_label, self.spell_m_label):
            label.setTextColor_(theme_color("gold"))
        self.spell_v_box = CheckboxSquareView.alloc().initWithFrame_(NSMakeRect(0, 0, 16, 16))
        self.spell_s_box = CheckboxSquareView.alloc().initWithFrame_(NSMakeRect(0, 0, 16, 16))
        self.spell_m_box = CheckboxSquareView.alloc().initWithFrame_(NSMakeRect(0, 0, 16, 16))
        self.spell_component_material_label = make_multiline(make_label("", (0, 0, 320, 36), 13))
        self.spell_component_material_label.setTextColor_(theme_color("text"))
        self.spell_stats_label = make_multiline(make_label("", (0, 0, 320, 42), 13))
        self.spell_stats_label.setTextColor_(theme_color("text"))
        self.spell_detail_header_views = [
            self.spell_detail_title_label,
            self.spell_detail_italian_label,
            self.spell_detail_meta_label,
            self.spell_components_label,
            self.spell_v_label,
            self.spell_v_box,
            self.spell_s_label,
            self.spell_s_box,
            self.spell_m_label,
            self.spell_m_box,
            self.spell_component_material_label,
            self.spell_stats_label,
        ]
        self.spell_detail_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        self.spell_detail_scroll.setHasVerticalScroller_(True)
        self.spell_detail_scroll.setAutohidesScrollers_(False)
        self.spell_detail_scroll.setDrawsBackground_(False)
        self.spell_detail_scroll.setBorderType_(0)
        self.spell_detail_view = DiceTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        self.spell_detail_view.setFont_(NSFont.systemFontOfSize_(13))
        self.spell_detail_view.setTextColor_(theme_color("text"))
        self.spell_detail_view.setRollTarget_(self)
        self.spell_detail_scroll.setDocumentView_(self.spell_detail_view)

        self.dice_title_label = make_label("Dice Roller", (0, 0, 240, 32), 24, True)
        self.dice_hint_label = make_label("", (0, 0, 720, 24), 13)
        self.dice_hint_label.setTextColor_(theme_color("muted"))
        self.dice_hint_label.setHidden_(True)
        self.dice_control_labels = []
        self.dice_clear_button = self._make_button("Clear", (0, 0, 100, 34), "clearDicePool:")
        self.dice_roll_button = self._make_button("Roll Dice", (0, 0, 130, 34), "rollCustomDice:")
        self.dice_formula_label = make_label("Click a die", (0, 0, 520, 42), 30, True)
        self.dice_formula_label.setAlignment_(1)
        self.dice_formula_label.setTextColor_(theme_color("dice"))
        self.dice_result_label = make_label("", (0, 0, 520, 24), 13, True)
        self.dice_result_label.setAlignment_(1)
        self.dice_result_label.setTextColor_(theme_color("muted"))
        self.dice_history_title_label = make_label("Recent Rolls", (0, 0, 220, 24), 16, True)
        self.dice_history_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 320, 260))
        self.dice_history_scroll.setHasVerticalScroller_(True)
        self.dice_history_scroll.setAutohidesScrollers_(False)
        self.dice_history_scroll.setDrawsBackground_(False)
        self.dice_history_scroll.setBorderType_(0)
        style_layer(self.dice_history_scroll, theme_color("surface_soft"), theme_color("border_soft"), 8, 1)
        self.dice_history_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 300, 260))
        self.dice_history_view.setEditable_(False)
        self.dice_history_view.setSelectable_(True)
        self.dice_history_view.setFont_(NSFont.systemFontOfSize_(12))
        self.dice_history_view.setTextColor_(theme_color("text"))
        self.dice_history_view.setBackgroundColor_(theme_color("surface_soft"))
        self.dice_history_view.setTextContainerInset_(NSMakeSize(10, 10))
        self.dice_history_scroll.setDocumentView_(self.dice_history_view)
        self.refreshDiceHistory()
        self.dice_presets = (4, 6, 8, 10, 12, 20)
        for sides in self.dice_presets:
            button = self._make_button(f"d{sides}", (0, 0, 76, 58), "addDieToPool:")
            button.setTag_(sides)
            self.dice_preset_buttons.append(button)

        self.adventure_title_label = make_label("Adventure", (0, 0, 360, 32), 24, True)
        self.adventure_status_label = make_label("Choose a folder of Markdown notes.", (0, 0, 520, 24), 13)
        self.adventure_status_label.setTextColor_(theme_color("muted"))
        self.adventure_folder_button = self._make_button("Choose Folder", (0, 0, 132, 32), "chooseAdventureFolder:")
        self.adventure_toggle_button = self._make_button("Edit", (0, 0, 86, 32), "toggleAdventureMode:")
        self.adventure_save_button = self._make_button("Save", (0, 0, 82, 32), "saveAdventureNote:")
        self.adventure_dirty_label = make_label("", (0, 0, 120, 22), 12, True)
        self.adventure_dirty_label.setTextColor_(theme_color("gold"))

        self.adventure_tree_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 260, 420))
        self.adventure_tree_scroll.setHasVerticalScroller_(True)
        self.adventure_tree_scroll.setAutohidesScrollers_(False)
        self.adventure_tree_scroll.setDrawsBackground_(False)
        self.adventure_tree_scroll.setBorderType_(0)
        style_layer(self.adventure_tree_scroll, theme_color("surface_soft"), theme_color("border_soft"), 8, 1)
        self.adventure_tree_content = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, 260, 420))
        self.adventure_tree_scroll.setDocumentView_(self.adventure_tree_content)

        adventure_user_content = WKUserContentController.alloc().init()
        adventure_user_content.addScriptMessageHandler_name_(self, "adventure")
        adventure_config = WKWebViewConfiguration.alloc().init()
        adventure_config.setUserContentController_(adventure_user_content)
        self.adventure_web_view = WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, 620, 420), adventure_config)
        self.adventure_web_view.setValue_forKey_(False, "drawsBackground")

        self.adventure_editor_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 620, 420))
        self.adventure_editor_scroll.setHasVerticalScroller_(True)
        self.adventure_editor_scroll.setHasHorizontalScroller_(False)
        self.adventure_editor_scroll.setAutohidesScrollers_(False)
        self.adventure_editor_scroll.setDrawsBackground_(False)
        self.adventure_editor_scroll.setBorderType_(0)
        style_layer(self.adventure_editor_scroll, theme_color("surface_soft"), theme_color("border_soft"), 8, 1)
        self.adventure_editor_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 620, 420))
        self.adventure_editor_view.setEditable_(True)
        self.adventure_editor_view.setSelectable_(True)
        self.adventure_editor_view.setFont_(NSFont.monospacedSystemFontOfSize_weight_(13, 0))
        self.adventure_editor_view.setTextColor_(theme_color("text"))
        self.adventure_editor_view.setBackgroundColor_(theme_color("surface_soft"))
        self.adventure_editor_view.setTextContainerInset_(NSMakeSize(14, 14))
        self.adventure_editor_view.textContainer().setLineFragmentPadding_(0)
        self.adventure_editor_view.setDelegate_(self)
        self.adventure_editor_scroll.setDocumentView_(self.adventure_editor_view)
        self.adventure_editor_scroll.setHidden_(True)

        self.previous_turn_button = self._make_button("Previous", (0, 0, 110, 34), "previousTurn:")
        self.next_turn_button = self._make_button("Next", (0, 0, 100, 34), "nextTurn:")
        self.clear_tracker_button = self._make_button("Finish Combat", (0, 0, 130, 34), "clearTracker:")
        self.turn_label = make_label("", (0, 0, 300, 24), 13, True)
        self.turn_label.setTextColor_(theme_color("gold"))
        self.turn_label.setAlignment_(2)
        self.turn_label.setHidden_(True)

        self.tracker_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        self.tracker_scroll.setHasVerticalScroller_(True)
        self.tracker_scroll.setHasHorizontalScroller_(True)
        self.tracker_scroll.setAutohidesScrollers_(False)
        self.tracker_view = CombatTrackerView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        self.tracker_view.setTarget_(self)
        self.tracker_scroll.setDocumentView_(self.tracker_view)
        self.tracker_scroll.setDrawsBackground_(False)
        self.tracker_scroll.setBorderType_(0)

        self.content_view.addSubview_(self.sidebar_panel)
        self.content_view.addSubview_(self.sidebar_scroll)
        self.content_view.addSubview_(self.combat_panel)
        self.content_view.addSubview_(self.monster_sheet_drawer)
        self.content_view.addSubview_(self.spell_panel)
        self.content_view.addSubview_(self.dice_panel)
        self.content_view.addSubview_(self.adventure_panel)
        self.content_view.addSubview_(self.initiative_tab_button)
        self.content_view.addSubview_(self.spells_tab_button)
        self.content_view.addSubview_(self.dice_tab_button)
        self.content_view.addSubview_(self.adventure_tab_button)
        for view in (
            self.notes_title,
            self.notes_hint,
            self.sidebar_logo_label,
            self.sidebar_footer_label,
            self.notes_scroll,
            self.party_label,
            self.party_popup,
            self.new_party_button,
            self.edit_party_button,
            self.delete_party_button,
            self.start_fight_button,
            self.party_status_label,
            self.monster_label,
            self.monster_search_field,
            self.monster_cr_filter_popup,
            self.monster_search_button,
            self.monster_results_scroll,
        ):
            self.sidebar_content.addSubview_(view)
        for label in self.party_member_labels:
            self.sidebar_content.addSubview_(label)
        for icon_view in self.party_member_icon_views:
            self.sidebar_content.addSubview_(icon_view)
        for labels in (
            self.party_member_name_labels,
            self.party_member_class_labels,
            self.party_member_ac_labels,
        ):
            for label in labels:
                self.sidebar_content.addSubview_(label)
        for view in (
            self.tracker_title,
            self.previous_turn_button,
            self.next_turn_button,
            self.clear_tracker_button,
            self.turn_label,
            self.tracker_scroll,
        ):
            self.content_view.addSubview_(view)
        for view in (
            self.spell_search_field,
            self.spell_level_filter_popup,
            self.spell_school_filter_popup,
            self.spell_results_scroll,
            *self.spell_detail_header_views,
            self.spell_detail_scroll,
        ):
            self.content_view.addSubview_(view)
        for view in (
            self.dice_title_label,
            self.dice_hint_label,
            self.dice_formula_label,
            self.dice_result_label,
            self.dice_history_title_label,
            self.dice_history_scroll,
            self.dice_clear_button,
            self.dice_roll_button,
        ):
            self.content_view.addSubview_(view)
        for button in self.dice_preset_buttons:
            self.content_view.addSubview_(button)
        for view in (
            self.adventure_title_label,
            self.adventure_status_label,
            self.adventure_folder_button,
            self.adventure_toggle_button,
            self.adventure_save_button,
            self.adventure_dirty_label,
            self.adventure_tree_scroll,
            self.adventure_web_view,
            self.adventure_editor_scroll,
        ):
            self.content_view.addSubview_(view)

        self.initiative_views = [
            self.sidebar_panel,
            self.sidebar_scroll,
            self.combat_panel,
            self.tracker_title,
            self.previous_turn_button,
            self.next_turn_button,
            self.clear_tracker_button,
            self.turn_label,
            self.tracker_scroll,
            self.monster_sheet_drawer,
        ]
        self.spell_views = [
            self.spell_panel,
            self.spell_search_field,
            self.spell_level_filter_popup,
            self.spell_school_filter_popup,
            self.spell_results_scroll,
            *self.spell_detail_header_views,
            self.spell_detail_scroll,
        ]
        self.dice_views = [
            self.dice_panel,
            self.dice_title_label,
            self.dice_formula_label,
            self.dice_result_label,
            self.dice_history_title_label,
            self.dice_history_scroll,
            self.dice_clear_button,
            self.dice_roll_button,
            *self.dice_preset_buttons,
        ]
        self.adventure_views = [
            self.adventure_panel,
            self.adventure_title_label,
            self.adventure_status_label,
            self.adventure_folder_button,
            self.adventure_toggle_button,
            self.adventure_save_button,
            self.adventure_dirty_label,
            self.adventure_tree_scroll,
            self.adventure_web_view,
            self.adventure_editor_scroll,
        ]

        self.window.setContentView_(self.content_view)
        self.loadAdventureVaultFromDefaults()
        self.layoutMainWindow()
        self.refreshPartyPopup()
        self.searchMonsters_(None)
        self.refreshSpellResults()
        self.refreshDiceFormula_(None)
        self.refreshTracker()
        self.applyCurrentTab()
        return self

    def _make_button(self, title: str, frame: tuple[int, int, int, int], action: str):
        button = NSButton.alloc().initWithFrame_(NSMakeRect(*frame))
        button.setTitle_(title)
        button.setTarget_(self)
        button.setAction_(action)
        button.setBordered_(False)
        style_layer(button, theme_color("surface"), theme_color("border_soft"), 8, 1)
        return button

    @objc.python_method
    def applyTheme(self):
        self.window.setBackgroundColor_(theme_color("app_bg"))
        style_layer(self.content_view, theme_color("app_bg"), None, 0)
        style_layer(self.sidebar_panel, theme_color("panel_alt"), None, 0)
        for panel in (self.combat_panel, self.spell_panel, self.dice_panel, self.adventure_panel):
            style_layer(panel, theme_color("panel"), theme_color("border_soft"), 14, 1)
        style_layer(self.monster_sheet_drawer, theme_color("panel_alt"), theme_color("border_soft"), 12, 1)
        style_layer(self.sidebar_logo_label, theme_color("selection"), theme_color("link"), 10, 1)
        for label in self.party_member_labels:
            style_layer(label, theme_color("surface"), theme_color("border_soft"), 8, 1)
        for scroll in (self.dice_history_scroll, self.adventure_tree_scroll, self.adventure_editor_scroll):
            style_layer(scroll, theme_color("surface_soft"), theme_color("border_soft"), 8, 1)

        for button in (
            self.initiative_tab_button,
            self.spells_tab_button,
            self.dice_tab_button,
            self.adventure_tab_button,
            self.new_party_button,
            self.edit_party_button,
            self.delete_party_button,
            self.start_fight_button,
            self.monster_search_button,
            self.dice_clear_button,
            self.dice_roll_button,
            self.adventure_folder_button,
            self.adventure_toggle_button,
            self.adventure_save_button,
            self.previous_turn_button,
            self.next_turn_button,
            self.clear_tracker_button,
            self.monster_sheet_close_button,
            self.monster_sheet_save_button,
            *self.dice_preset_buttons,
        ):
            if button is not None:
                style_layer(button, theme_color("surface"), theme_color("border_soft"), 8, 1)

        for field in (self.monster_search_field, self.spell_search_field):
            style_text_input(field)
        for popup in (
            self.party_popup,
            self.monster_cr_filter_popup,
            self.spell_level_filter_popup,
            self.spell_school_filter_popup,
        ):
            popup.setNeedsDisplay_(True)

        muted_labels = (
            self.notes_hint,
            self.sidebar_footer_label,
            self.party_status_label,
            self.spell_detail_italian_label,
            self.dice_hint_label,
            self.dice_result_label,
            self.adventure_status_label,
        )
        for label in muted_labels:
            label.setTextColor_(theme_color("muted"))
        for label in (self.spell_detail_meta_label, self.turn_label, self.adventure_dirty_label):
            label.setTextColor_(theme_color("gold"))
        for label in (
            self.spell_components_label,
            self.spell_component_material_label,
            self.spell_stats_label,
        ):
            label.setTextColor_(theme_color("text"))
        for label in (self.spell_v_label, self.spell_s_label, self.spell_m_label):
            label.setTextColor_(theme_color("gold"))
        self.monster_sheet_roll_label.setTextColor_(theme_color("dice"))
        self.dice_formula_label.setTextColor_(theme_color("dice"))

        self.notes_view.setTextColor_(theme_color("text"))
        self.notes_view.setBackgroundColor_(theme_color("surface"))
        self.dice_history_view.setTextColor_(theme_color("text"))
        self.dice_history_view.setBackgroundColor_(theme_color("surface_soft"))
        self.adventure_editor_view.setTextColor_(theme_color("text"))
        self.adventure_editor_view.setBackgroundColor_(theme_color("surface_soft"))
        self.spell_detail_view.setTextColor_(theme_color("text"))
        self.monster_sheet_body.setTextColor_(theme_color("text"))

        for collection in (
            self.monster_result_buttons,
            self.monster_add_buttons,
            self.spell_result_buttons,
            self.adventure_tree_buttons,
            self.monster_sheet_ability_buttons,
        ):
            for view in collection:
                view.setNeedsDisplay_(True)
        self.tracker_view.setNeedsDisplay_(True)
        self.applyCurrentTab()
        if self.adventure_is_editing:
            self.refreshAdventureControls()
        elif self.adventure_selected_note is not None:
            self.renderAdventureMarkdown_(self.adventure_last_saved_text)
        else:
            self.refreshAdventureWorkspace()

    def layoutMainWindow(self):
        bounds = self.content_view.bounds()
        width = int(bounds.size.width)
        height = int(bounds.size.height)

        def centered_control_rect(x: float, center_y: float, width: float, height: float):
            return NSMakeRect(x, center_y - height / 2, width, height)

        def centered_text_rect(label, x: float, center_y: float, width: float):
            cell_size = label.cell().cellSize()
            return centered_control_rect(x, center_y, width, max(1, cell_size.height))

        tab_y = height - 38
        self.initiative_tab_button.setFrame_(NSMakeRect(20, tab_y, 150, 30))
        self.spells_tab_button.setFrame_(NSMakeRect(178, tab_y, 86, 30))
        self.dice_tab_button.setFrame_(NSMakeRect(272, tab_y, 112, 30))
        self.adventure_tab_button.setFrame_(NSMakeRect(392, tab_y, 104, 30))
        content_height = height - 54
        sidebar_width = min(370, max(320, int(width * 0.29)))
        outer_gap = 20
        sidebar_margin = 24
        panel_x = sidebar_width + outer_gap
        panel_y = 20
        available_panel_width = max(420, width - panel_x - outer_gap)
        drawer_open = self.current_tab == "initiative" and self.monster_sheet_combatant_index >= 0
        drawer_gap = 16
        drawer_width = 0
        if drawer_open:
            preferred_drawer_width = min(420, max(320, int(width * 0.30)))
            max_drawer_width = available_panel_width - 360 - drawer_gap
            drawer_width = max(280, min(preferred_drawer_width, max_drawer_width))
            panel_width = max(340, available_panel_width - drawer_width - drawer_gap)
        else:
            panel_width = max(560, available_panel_width)
        panel_height = max(560, content_height - panel_y)
        party = self.selectedParty()
        characters = party.get("characters", [])
        if not isinstance(characters, list):
            characters = []
        visible_party_rows = min(len([character for character in characters if isinstance(character, dict)]), len(self.party_member_labels))
        sidebar_document_height = max(
            content_height,
            620 + visible_party_rows * 42,
        )

        self.sidebar_panel.setFrame_(NSMakeRect(0, 0, sidebar_width, content_height))
        self.sidebar_scroll.setFrame_(NSMakeRect(0, 0, sidebar_width, content_height))
        self.sidebar_content.setFrame_(NSMakeRect(0, 0, sidebar_width, sidebar_document_height))
        self.combat_panel.setFrame_(NSMakeRect(panel_x, panel_y, panel_width, panel_height))
        self.monster_sheet_drawer.setHidden_(not drawer_open)
        if drawer_open:
            drawer_x = panel_x + panel_width + drawer_gap
            self.monster_sheet_drawer.setFrame_(NSMakeRect(drawer_x, panel_y, drawer_width, panel_height))
            drawer_margin = 20
            drawer_inner_width = max(240, drawer_width - drawer_margin * 2)
            drawer_top = panel_height - 48
            self.monster_sheet_title.setFrame_(NSMakeRect(drawer_margin, drawer_top - 8, max(120, drawer_inner_width - 88), 40))
            self.monster_sheet_close_button.setFrame_(NSMakeRect(drawer_width - drawer_margin - 72, drawer_top, 72, 28))
            ability_y = panel_height - 156
            ability_button_width = min(44, max(34, (drawer_inner_width - 5 * 6) / 6))
            ability_gap = (drawer_inner_width - ability_button_width * 6) / 5 if len(self.monster_sheet_ability_buttons) > 1 else 0
            for index, button in enumerate(self.monster_sheet_ability_buttons):
                button.setFrame_(NSMakeRect(drawer_margin + index * (ability_button_width + ability_gap), ability_y, ability_button_width, 76))
            scroll_y = 20
            scroll_height = max(300, ability_y - 36)
            self.monster_sheet_scroll.setFrame_(NSMakeRect(drawer_margin, scroll_y, drawer_inner_width, scroll_height))
            body_width = max(220, drawer_inner_width - 24)
            self.monster_sheet_body.textContainer().setContainerSize_(NSMakeSize(body_width, 100000))
            self.monster_sheet_body.layoutManager().ensureLayoutForTextContainer_(self.monster_sheet_body.textContainer())
            body_height = max(
                scroll_height,
                self.monster_sheet_body.layoutManager().usedRectForTextContainer_(self.monster_sheet_body.textContainer()).size.height + 24,
            )
            self.monster_sheet_body.setFrame_(NSMakeRect(0, 0, body_width, body_height))
        self.spell_panel.setFrame_(NSMakeRect(20, 20, width - 40, max(520, content_height - 20)))

        y = sidebar_document_height - 52
        self.sidebar_logo_label.setFrame_(NSMakeRect(sidebar_margin, y - 2, 36, 36))
        self.notes_title.setFrame_(NSMakeRect(sidebar_margin + 50, y + 4, sidebar_width - sidebar_margin * 2 - 50, 24))
        self.notes_hint.setFrame_(NSMakeRect(sidebar_margin + 50, y - 17, sidebar_width - sidebar_margin * 2 - 50, 20))
        self.sidebar_footer_label.setFrame_(NSMakeRect(sidebar_margin, 18, sidebar_width - sidebar_margin * 2, 24))
        self.notes_scroll.setFrame_(NSMakeRect(sidebar_margin, 20, sidebar_width - sidebar_margin * 2, 120))
        self.notes_view.setFrame_(NSMakeRect(0, 0, sidebar_width - sidebar_margin * 2 - 24, 120))

        y -= 18
        self.party_popup.setFrame_(NSMakeRect(sidebar_margin, y, sidebar_width - sidebar_margin * 2, 34))
        y -= 70
        self.party_label.setFrame_(NSMakeRect(sidebar_margin, y + 4, 120, 24))
        self.new_party_button.setFrame_(NSMakeRect(sidebar_width - sidebar_margin - 34, y, 34, 28))
        self.edit_party_button.setFrame_(NSMakeRect(sidebar_width - sidebar_margin - 104, y, 62, 28))
        self.delete_party_button.setFrame_(NSMakeRect(sidebar_width - sidebar_margin - 180, y, 68, 28))
        self.start_fight_button.setFrame_(NSMakeRect(sidebar_width - sidebar_margin - 222, y, 34, 28))
        y -= 46

        card_width = sidebar_width - sidebar_margin * 2
        for index, label in enumerate(self.party_member_labels):
            label.setFrame_(NSMakeRect(sidebar_margin, y - index * 42, card_width, 36))
        for index, icon_view in enumerate(self.party_member_icon_views):
            icon_view.setFrame_(NSMakeRect(sidebar_margin + 12, y - index * 42 + 8, 20, 20))
        ac_w = 68
        class_w = min(104, max(76, int(card_width * 0.27)))
        icon_column_w = 42
        column_gap = 8
        row_name_x = sidebar_margin + icon_column_w
        row_ac_x = sidebar_margin + card_width - ac_w - 10
        row_class_x = row_ac_x - class_w - column_gap
        row_name_w = max(62, row_class_x - row_name_x - column_gap)
        for index in range(len(self.party_member_labels)):
            row_y = y - index * 42 + 9
            self.party_member_name_labels[index].setFrame_(NSMakeRect(row_name_x, row_y, row_name_w, 20))
            self.party_member_class_labels[index].setFrame_(NSMakeRect(row_class_x, row_y, class_w, 20))
            self.party_member_ac_labels[index].setFrame_(NSMakeRect(row_ac_x, row_y, ac_w, 20))
        y -= visible_party_rows * 42 + 8
        self.party_status_label.setFrame_(NSMakeRect(sidebar_margin, y, card_width, 38))

        y -= 70
        self.monster_label.setFrame_(NSMakeRect(sidebar_margin, y + 4, 140, 24))
        y -= 40
        cr_filter_w = 90
        cr_filter_gap = 10
        search_w = max(160, card_width - cr_filter_w - cr_filter_gap)
        self.monster_search_field.setFrame_(NSMakeRect(sidebar_margin, y - 3, search_w, 34))
        self.monster_cr_filter_popup.setFrame_(NSMakeRect(sidebar_margin + search_w + cr_filter_gap, y - 3, cr_filter_w, 34))
        self.monster_search_button.setFrame_(NSMakeRect(sidebar_margin + card_width - 76, y, 76, 28))
        y -= 48
        results_height = max(140, y - 18)
        self.monster_results_scroll.setFrame_(NSMakeRect(sidebar_margin, 18, card_width, results_height))
        monster_add_w = 30
        monster_result_gap = 10
        monster_result_w = max(180, card_width - monster_add_w - monster_result_gap - 18)
        results_document_height = max(results_height, len(self.monster_results) * MONSTER_RESULT_ROW_STEP)
        self.monster_results_content.setFrame_(NSMakeRect(0, 0, card_width - 18, results_document_height))
        for index, button in enumerate(self.monster_result_buttons):
            row_y = index * MONSTER_RESULT_ROW_STEP
            button.setFrame_(NSMakeRect(0, row_y, monster_result_w, MONSTER_RESULT_ROW_HEIGHT))
            if index < len(self.monster_add_buttons):
                self.monster_add_buttons[index].setFrame_(
                    NSMakeRect(monster_result_w + monster_result_gap, row_y, monster_add_w, MONSTER_RESULT_ROW_HEIGHT)
                )
        top_scroll_y = max(0, sidebar_document_height - content_height)
        self.sidebar_scroll.contentView().scrollToPoint_(NSMakePoint(0, top_scroll_y))
        self.sidebar_scroll.reflectScrolledClipView_(self.sidebar_scroll.contentView())

        header_y = panel_y + panel_height - 58
        title_width = min(220, max(140, panel_width - 64))
        self.tracker_title.setFrame_(NSMakeRect(panel_x + 32, header_y, title_width, 28))
        turn_x = panel_x + 32 + title_width + 12
        turn_width = max(0, panel_x + panel_width - 28 - turn_x)
        self.turn_label.setFrame_(NSMakeRect(turn_x, header_y + 2, turn_width, 24))

        compact_tracker_controls = panel_width < 540
        bottom_height = 102 if compact_tracker_controls else 66
        if compact_tracker_controls:
            self.clear_tracker_button.setFrame_(NSMakeRect(panel_x + 28, panel_y + 18, 132, 34))
            nav_width = 196
            nav_x = panel_x + max(28, panel_width - nav_width - 28)
            self.previous_turn_button.setFrame_(NSMakeRect(nav_x, panel_y + 58, 104, 34))
            self.next_turn_button.setFrame_(NSMakeRect(nav_x + 116, panel_y + 58, 80, 34))
        else:
            self.clear_tracker_button.setFrame_(NSMakeRect(panel_x + 28, panel_y + 18, 150, 34))
            self.previous_turn_button.setFrame_(NSMakeRect(panel_x + panel_width - 244, panel_y + 18, 104, 34))
            self.next_turn_button.setFrame_(NSMakeRect(panel_x + panel_width - 128, panel_y + 18, 100, 34))

        tracker_x = panel_x + 24
        tracker_y = panel_y + bottom_height
        tracker_width = panel_width - 48
        tracker_height = max(320, panel_height - bottom_height - 88)
        self.tracker_scroll.setFrame_(NSMakeRect(tracker_x, tracker_y, tracker_width, tracker_height))
        self.tracker_view.setFrame_(NSMakeRect(0, 0, max(780, tracker_width - 24), max(tracker_height, self.tracker_view.frame().size.height)))

        spell_margin = 44
        spell_panel_frame = self.spell_panel.frame()
        spell_x = spell_panel_frame.origin.x + spell_margin
        spell_y = spell_panel_frame.origin.y + spell_margin
        spell_width = spell_panel_frame.size.width - spell_margin * 2
        spell_height = spell_panel_frame.size.height - spell_margin * 2
        list_width = min(430, max(320, spell_width * 0.38))
        self.spell_search_field.setFrame_(NSMakeRect(spell_x, spell_y + spell_height - 42, list_width, 34))
        filter_gap = 10
        level_filter_w = min(128, max(108, list_width * 0.36))
        school_filter_w = max(140, list_width - level_filter_w - filter_gap)
        filter_y = spell_y + spell_height - 84
        self.spell_level_filter_popup.setFrame_(NSMakeRect(spell_x, filter_y, level_filter_w, 34))
        self.spell_school_filter_popup.setFrame_(NSMakeRect(spell_x + level_filter_w + filter_gap, filter_y, school_filter_w, 34))
        results_height = max(120, filter_y - spell_y - 12)
        self.spell_results_scroll.setFrame_(NSMakeRect(spell_x, spell_y, list_width, results_height))
        results_document_width = max(120, list_width - 18)
        results_document_height = max(results_height, len(self.displayed_spells) * SPELL_RESULT_ROW_STEP)
        self.spell_results_content.setFrame_(NSMakeRect(0, 0, results_document_width, results_document_height))
        for index, button in enumerate(self.spell_result_buttons):
            button.setFrame_(NSMakeRect(0, index * SPELL_RESULT_ROW_STEP, results_document_width, SPELL_RESULT_ROW_HEIGHT))
        detail_x = spell_x + list_width + 28
        detail_width = max(300, spell_width - list_width - 28)
        if self.spell_detail_title_label.isHidden():
            self.spell_detail_scroll.setFrame_(NSMakeRect(detail_x, spell_y, detail_width, spell_height))
            self.spell_detail_view.textContainer().setContainerSize_(NSMakeSize(max(120, detail_width - 24), 100000))
            self.spell_detail_view.setFrame_(
                NSMakeRect(0, 0, detail_width - 24, max(spell_height, self.spell_detail_view.frame().size.height))
            )
        else:
            detail_top = spell_y + spell_height
            self.spell_detail_title_label.setFrame_(NSMakeRect(detail_x, detail_top - 36, detail_width, 32))
            self.spell_detail_italian_label.setFrame_(NSMakeRect(detail_x, detail_top - 60, detail_width, 22))
            self.spell_detail_meta_label.setFrame_(NSMakeRect(detail_x, detail_top - 92, detail_width, 24))

            component_y = detail_top - 128
            component_row_height = 24
            component_center_y = component_y + component_row_height / 2
            component_box_size = 16
            self.spell_components_label.setFrame_(centered_text_rect(self.spell_components_label, detail_x, component_center_y, 92))
            component_x = detail_x + 104
            for label, box in (
                (self.spell_v_label, self.spell_v_box),
                (self.spell_s_label, self.spell_s_box),
                (self.spell_m_label, self.spell_m_box),
            ):
                label.setFrame_(centered_text_rect(label, component_x, component_center_y, 16))
                box.setFrame_(centered_control_rect(component_x + 20, component_center_y, component_box_size, component_box_size))
                component_x += 52
            material_x = component_x + 2
            material_width = detail_x + detail_width - material_x
            stats_y = component_y - 44
            if material_width >= 140:
                self.spell_component_material_label.setFrame_(
                    centered_text_rect(self.spell_component_material_label, material_x, component_center_y, material_width)
                )
            else:
                self.spell_component_material_label.setFrame_(NSMakeRect(detail_x, component_y - 30, detail_width, 28))
                stats_y = component_y - 66
            self.spell_stats_label.setFrame_(NSMakeRect(detail_x, stats_y, detail_width, 42))

            scroll_top = stats_y - 12
            scroll_height = max(160, scroll_top - spell_y)
            self.spell_detail_scroll.setFrame_(NSMakeRect(detail_x, spell_y, detail_width, scroll_height))
            self.spell_detail_view.textContainer().setContainerSize_(NSMakeSize(max(120, detail_width - 24), 100000))
            self.spell_detail_view.setFrame_(
                NSMakeRect(0, 0, detail_width - 24, max(scroll_height, self.spell_detail_view.frame().size.height))
            )

        dice_panel_frame = self.dice_panel.frame()
        if dice_panel_frame.size.width <= 1:
            self.dice_panel.setFrame_(NSMakeRect(20, 20, width - 40, max(520, content_height - 20)))
            dice_panel_frame = self.dice_panel.frame()
        self.dice_panel.setFrame_(NSMakeRect(20, 20, width - 40, max(520, content_height - 20)))
        dice_panel_frame = self.dice_panel.frame()
        dice_top = dice_panel_frame.origin.y + dice_panel_frame.size.height - 78
        self.dice_title_label.setFrame_(NSMakeRect(dice_panel_frame.origin.x + 44, dice_top, 320, 34))
        self.dice_hint_label.setFrame_(NSMakeRect(dice_panel_frame.origin.x + 44, dice_top - 28, min(640, dice_panel_frame.size.width - 88), 24))
        self.dice_hint_label.setHidden_(True)

        history_w = min(380, max(300, dice_panel_frame.size.width * 0.30))
        history_x = dice_panel_frame.origin.x + dice_panel_frame.size.width - history_w - 44
        history_top = dice_top
        history_h = max(250, dice_panel_frame.size.height - 150)
        self.dice_history_title_label.setFrame_(NSMakeRect(history_x, history_top + 4, history_w, 24))
        self.dice_history_scroll.setFrame_(NSMakeRect(history_x, dice_panel_frame.origin.y + 44, history_w, history_h))
        self.dice_history_view.setFrame_(NSMakeRect(0, 0, max(240, history_w - 24), max(history_h, self.dice_history_view.frame().size.height)))

        controls_right = history_x - 34
        controls_left = dice_panel_frame.origin.x + 44
        controls_width = max(420, controls_right - controls_left)
        dice_center_x = controls_left + controls_width / 2
        controls_y = dice_top - 104

        die_button_w = 82
        die_button_gap = 14
        die_total_width = len(self.dice_preset_buttons) * die_button_w + (len(self.dice_preset_buttons) - 1) * die_button_gap
        die_x = dice_center_x - die_total_width / 2
        for index, button in enumerate(self.dice_preset_buttons):
            button.setFrame_(NSMakeRect(die_x + index * (die_button_w + die_button_gap), controls_y, die_button_w, 58))

        formula_width = min(680, dice_panel_frame.size.width - 88)
        formula_width = min(formula_width, max(360, controls_width))
        self.dice_formula_label.setFrame_(NSMakeRect(dice_center_x - formula_width / 2, controls_y - 92, formula_width, 46))
        self.dice_result_label.setFrame_(NSMakeRect(dice_center_x - formula_width / 2, controls_y - 126, formula_width, 24))

        action_y = controls_y - 184
        self.dice_clear_button.setFrame_(NSMakeRect(dice_center_x - 136, action_y, 116, 34))
        self.dice_roll_button.setFrame_(NSMakeRect(dice_center_x + 20, action_y, 136, 34))

        self.adventure_panel.setFrame_(NSMakeRect(20, 20, width - 40, max(520, content_height - 20)))
        adventure_frame = self.adventure_panel.frame()
        adventure_margin = 28
        adventure_x = adventure_frame.origin.x + adventure_margin
        adventure_y = adventure_frame.origin.y + adventure_margin
        adventure_width = adventure_frame.size.width - adventure_margin * 2
        adventure_height = adventure_frame.size.height - adventure_margin * 2
        tree_width = min(390, max(270, int(adventure_width * 0.30)))
        toolbar_h = 48
        self.adventure_title_label.setFrame_(NSMakeRect(adventure_x, adventure_y + adventure_height - 34, tree_width, 30))
        self.adventure_folder_button.setFrame_(NSMakeRect(adventure_x + max(0, tree_width - 136), adventure_y + adventure_height - 36, 136, 32))
        self.adventure_tree_scroll.setFrame_(NSMakeRect(adventure_x, adventure_y, tree_width, adventure_height - toolbar_h))
        tree_document_width = max(180, tree_width - 18)
        tree_document_height = max(adventure_height - toolbar_h, len(self.adventure_flat_nodes) * 28 + 12)
        self.adventure_tree_content.setFrame_(NSMakeRect(0, 0, tree_document_width, tree_document_height))
        for index, button in enumerate(self.adventure_tree_buttons):
            button.setFrame_(NSMakeRect(4, 6 + index * 28, max(80, tree_document_width - 8), 26))

        detail_x = adventure_x + tree_width + 22
        detail_width = max(360, adventure_width - tree_width - 22)
        detail_top = adventure_y + adventure_height
        button_y = detail_top - 36
        self.adventure_toggle_button.setFrame_(NSMakeRect(detail_x + detail_width - 190, button_y, 86, 32))
        self.adventure_save_button.setFrame_(NSMakeRect(detail_x + detail_width - 96, button_y, 82, 32))
        self.adventure_dirty_label.setFrame_(NSMakeRect(detail_x + detail_width - 316, button_y + 6, 112, 22))
        self.adventure_status_label.setFrame_(NSMakeRect(detail_x, button_y + 5, max(120, detail_width - 330), 22))
        content_rect = NSMakeRect(detail_x, adventure_y, detail_width, adventure_height - toolbar_h)
        self.adventure_web_view.setFrame_(content_rect)
        self.adventure_editor_scroll.setFrame_(content_rect)
        editor_width = max(200, detail_width - 18)
        editor_height = max(content_rect.size.height, self.adventure_editor_view.frame().size.height)
        self.adventure_editor_view.textContainer().setContainerSize_(NSMakeSize(editor_width - 28, 100000))
        self.adventure_editor_view.setFrame_(NSMakeRect(0, 0, editor_width, editor_height))

    def windowDidResize_(self, _notification):
        self.layoutMainWindow()

    def show_(self, _sender):
        NSApp.activateIgnoringOtherApps_(True)
        self.layoutMainWindow()
        self.window.makeKeyAndOrderFront_(None)

    def showInitiativeTab_(self, _sender):
        self.current_tab = "initiative"
        self.applyCurrentTab()

    def showSpellsTab_(self, _sender):
        self.current_tab = "spells"
        self.applyCurrentTab()
        self.refreshSpellResults()

    def showDiceTab_(self, _sender):
        self.current_tab = "dice"
        self.applyCurrentTab()
        self.refreshDiceFormula_(None)

    def showAdventureTab_(self, _sender):
        self.current_tab = "adventure"
        self.applyCurrentTab()
        self.refreshAdventureWorkspace()

    def applyCurrentTab(self):
        show_initiative = self.current_tab == "initiative"
        show_spells = self.current_tab == "spells"
        show_dice = self.current_tab == "dice"
        show_adventure = self.current_tab == "adventure"
        for view in self.initiative_views:
            view.setHidden_(not show_initiative)
        self.monster_search_button.setHidden_(True)
        for view in self.spell_views:
            view.setHidden_(not show_spells)
        for view in self.dice_views:
            view.setHidden_(not show_dice)
        for view in self.adventure_views:
            view.setHidden_(not show_adventure)
        if show_adventure:
            self.adventure_web_view.setHidden_(self.adventure_is_editing)
            self.adventure_editor_scroll.setHidden_(not self.adventure_is_editing)
        style_layer(
            self.initiative_tab_button,
            theme_color("surface_hover") if show_initiative else theme_color("surface_soft"),
            theme_color("border"),
            8,
            1,
        )
        style_layer(
            self.spells_tab_button,
            theme_color("surface_hover") if show_spells else theme_color("surface_soft"),
            theme_color("border"),
            8,
            1,
        )
        style_layer(
            self.dice_tab_button,
            theme_color("surface_hover") if show_dice else theme_color("surface_soft"),
            theme_color("border"),
            8,
            1,
        )
        style_layer(
            self.adventure_tab_button,
            theme_color("surface_hover") if show_adventure else theme_color("surface_soft"),
            theme_color("border"),
            8,
            1,
        )
        self.layoutMainWindow()

    def controlTextDidChange_(self, notification):
        field = notification.object()
        if field == self.monster_search_field:
            self.searchMonsters_(None)
        elif field == self.spell_search_field:
            self.refreshSpellResults()

    def textDidChange_(self, notification):
        if notification.object() == self.adventure_editor_view:
            current = str(self.adventure_editor_view.string())
            self.adventure_dirty = current != self.adventure_last_saved_text
            self.refreshAdventureControls()

    @objc.python_method
    def loadAdventureVaultFromDefaults(self):
        defaults = NSUserDefaults.standardUserDefaults()
        raw_path = defaults.stringForKey_(ADVENTURE_VAULT_PREF)
        if not raw_path:
            self.refreshAdventureWorkspace()
            return
        vault_path = Path(str(raw_path)).expanduser()
        if not vault_path.is_dir():
            self.refreshAdventureWorkspace()
            return
        self.setAdventureVault_(vault_path)
        raw_note = defaults.stringForKey_(ADVENTURE_SELECTED_NOTE_PREF)
        if raw_note:
            note_path = Path(str(raw_note))
            if note_path.is_file() and safe_relative_to(note_path, vault_path):
                self.openAdventureNote_(note_path)
                return
        first_note = self.firstAdventureNote()
        if first_note is not None:
            self.openAdventureNote_(first_note)

    def chooseAdventureFolder_(self, _sender):
        if not self.confirmAdventureCanDiscardOrSave():
            return
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(False)
        panel.setCanChooseDirectories_(True)
        panel.setAllowsMultipleSelection_(False)
        panel.setCanCreateDirectories_(False)
        panel.setMessage_("Choose the folder that contains your Markdown adventure notes.")
        if self.adventure_vault_path is not None:
            panel.setDirectoryURL_(NSURL.fileURLWithPath_(str(self.adventure_vault_path)))
        NSApp.activateIgnoringOtherApps_(True)
        if int(panel.runModal()) not in (1, 1000):
            log("Adventure folder selection cancelled.")
            return
        url = panel.URL()
        if url is None:
            return
        path = Path(str(url.path()))
        if not path.is_dir():
            log(f"Adventure folder selection ignored because path is not a directory: {path}")
            return
        log(f"Adventure folder selected: {path}")
        self.current_tab = "adventure"
        self.setAdventureVault_(path)
        first_note = self.firstAdventureNote()
        if first_note is not None:
            self.openAdventureNote_(first_note)
            log(f"Adventure opened first note: {first_note}")
        else:
            self.adventure_selected_note = None
            self.showAdventureEmpty_("No Markdown notes found in this folder.")
            log(f"Adventure folder has no Markdown notes: {path}")
        self.refreshAdventureWorkspace()
        self.applyCurrentTab()
        self.window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def setAdventureVault_(self, path: Path):
        self.adventure_vault_path = path.resolve()
        defaults = NSUserDefaults.standardUserDefaults()
        defaults.setObject_forKey_(str(self.adventure_vault_path), ADVENTURE_VAULT_PREF)
        defaults.synchronize()
        self.adventure_selected_note = None
        self.adventure_is_editing = False
        self.adventure_dirty = False
        self.adventure_last_saved_text = ""
        self.loadAdventureFileColors()
        self.buildAdventureIndexes()
        self.adventure_root_node = self.buildAdventureNode(self.adventure_vault_path, 0)
        self.adventure_expanded_paths = set()
        if self.adventure_root_node is not None:
            self.collectAdventureDirectoryPaths(self.adventure_root_node, self.adventure_expanded_paths)
        self.refreshAdventureTree()
        self.refreshAdventureControls()
        log(
            "Adventure vault loaded: "
            f"{self.adventure_vault_path} "
            f"({len(self.adventure_note_index)} note keys, {len(self.adventure_flat_nodes)} visible rows)"
        )

    @objc.python_method
    def loadAdventureFileColors(self):
        self.adventure_file_colors = {}
        if self.adventure_vault_path is None:
            return
        path = self.adventure_vault_path / ".obsidian" / "plugins" / "obsidian-file-color" / "data.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return
        palette = {
            str(item.get("id")): str(item.get("value"))
            for item in data.get("palette", [])
            if isinstance(item, dict) and item.get("id") and item.get("value")
        }
        for item in data.get("fileColors", []):
            if not isinstance(item, dict):
                continue
            rel_path = str(item.get("path") or "").strip().strip("/")
            color = palette.get(str(item.get("color") or ""))
            if rel_path and color:
                self.adventure_file_colors[rel_path] = color

    @objc.python_method
    def buildAdventureIndexes(self):
        self.adventure_note_index = {}
        self.adventure_asset_index = {}
        if self.adventure_vault_path is None:
            return
        for path in sorted(self.adventure_vault_path.rglob("*"), key=lambda item: normalize(str(item.relative_to(self.adventure_vault_path)))):
            if any(part.startswith(".") for part in path.relative_to(self.adventure_vault_path).parts):
                continue
            if path.is_file() and path.suffix.lower() in (".md", ".markdown"):
                rel = path.relative_to(self.adventure_vault_path)
                keys = {
                    normalize(path.stem),
                    normalize(str(rel.with_suffix(""))),
                    normalize(str(rel)),
                }
                for key in keys:
                    if key:
                        self.adventure_note_index.setdefault(key, []).append(path)
            elif path.is_file():
                key = normalize(path.name)
                if key:
                    self.adventure_asset_index.setdefault(key, []).append(path)

    @objc.python_method
    def buildAdventureNode(self, path: Path, depth: int) -> AdventureNode | None:
        if path.is_file():
            if path.suffix.lower() not in (".md", ".markdown"):
                return None
            return AdventureNode(path=path, name=path.stem, is_dir=False, depth=depth, children=[])
        if path.name.startswith(".") and path != self.adventure_vault_path:
            return None
        children: list[AdventureNode] = []
        try:
            entries = list(path.iterdir())
        except OSError:
            entries = []
        entries.sort(key=lambda item: (not item.is_dir(), natural_sort_key(item.name)))
        for entry in entries:
            child = self.buildAdventureNode(entry, depth + 1)
            if child is not None:
                children.append(child)
        if path == self.adventure_vault_path or children:
            return AdventureNode(path=path, name=path.name, is_dir=True, depth=depth, children=children)
        return None

    @objc.python_method
    def collectAdventureDirectoryPaths(self, node: AdventureNode, result: set[str]):
        if not node.is_dir:
            return
        result.add(str(node.path))
        for child in node.children:
            self.collectAdventureDirectoryPaths(child, result)

    @objc.python_method
    def firstAdventureNote(self) -> Path | None:
        if self.adventure_root_node is None:
            return None
        stack = list(self.adventure_root_node.children)
        while stack:
            node = stack.pop(0)
            if not node.is_dir:
                return node.path
            stack = list(node.children) + stack
        return None

    @objc.python_method
    def refreshAdventureWorkspace(self):
        self.refreshAdventureTree()
        self.refreshAdventureControls()
        if self.adventure_vault_path is None:
            self.showAdventureEmpty_("Choose a local folder to browse your Markdown adventure notes.")
        elif self.adventure_selected_note is None:
            self.showAdventureEmpty_("Select a Markdown note from the left.")

    @objc.python_method
    def refreshAdventureTree(self):
        self.adventure_flat_nodes = []
        if self.adventure_root_node is not None:
            for child in self.adventure_root_node.children:
                self.flattenAdventureNode(child)
        while len(self.adventure_tree_buttons) < len(self.adventure_flat_nodes):
            button = AdventureTreeButton.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 26))
            button.setTarget_(self)
            button.setAction_("selectAdventureTreeRow:")
            button.setHidden_(True)
            self.adventure_tree_buttons.append(button)
            self.adventure_tree_content.addSubview_(button)
        for index, button in enumerate(self.adventure_tree_buttons):
            if index >= len(self.adventure_flat_nodes):
                button.setHidden_(True)
                continue
            node = self.adventure_flat_nodes[index]
            button.setTag_(index)
            button.configureName_path_depth_isDir_expanded_selected_color_(
                node.name,
                str(node.path),
                node.depth,
                node.is_dir,
                str(node.path) in self.adventure_expanded_paths,
                self.adventure_selected_note is not None and node.path.resolve() == self.adventure_selected_note.resolve(),
                self.adventureColorForPath(node.path),
            )
            button.setHidden_(False)
        self.layoutMainWindow()

    @objc.python_method
    def flattenAdventureNode(self, node: AdventureNode):
        self.adventure_flat_nodes.append(node)
        if not node.is_dir or str(node.path) not in self.adventure_expanded_paths:
            return
        for child in node.children:
            self.flattenAdventureNode(child)

    @objc.python_method
    def adventureColorForPath(self, path: Path) -> str:
        if self.adventure_vault_path is None:
            return ""
        try:
            rel = self.adventureRelativePath(path)
        except ValueError:
            return ""
        candidates = []
        current = rel
        while current:
            candidates.append(current)
            current = str(Path(current).parent).replace("\\", "/")
            if current == ".":
                break
        for candidate in candidates:
            if candidate in self.adventure_file_colors:
                return self.adventure_file_colors[candidate]
        return ""

    def selectAdventureTreeRow_(self, sender):
        index = int(sender.tag())
        if index < 0 or index >= len(self.adventure_flat_nodes):
            return
        node = self.adventure_flat_nodes[index]
        if node.is_dir:
            key = str(node.path)
            if key in self.adventure_expanded_paths:
                self.adventure_expanded_paths.remove(key)
            else:
                self.adventure_expanded_paths.add(key)
            self.refreshAdventureTree()
            return
        if not self.confirmAdventureCanDiscardOrSave():
            return
        self.openAdventureNote_(node.path)

    def adventureContextMenuForButton_(self, button):
        index = int(button.tag())
        if index < 0 or index >= len(self.adventure_flat_nodes):
            return None
        node = self.adventure_flat_nodes[index]
        menu = NSMenu.alloc().init()

        color_menu = NSMenu.alloc().init()
        none_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("None", "setAdventureTreeColor:", "")
        none_item.setTarget_(self)
        none_item.setRepresentedObject_(json.dumps({"path": str(node.path), "color": ""}))
        color_menu.addItem_(none_item)
        color_menu.addItem_(NSMenuItem.separatorItem())
        for color_name, _hex_value in ADVENTURE_COLOR_PALETTE:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(color_name, "setAdventureTreeColor:", "")
            item.setTarget_(self)
            item.setRepresentedObject_(json.dumps({"path": str(node.path), "color": color_name}))
            color_menu.addItem_(item)

        set_color_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Set color", None, "")
        set_color_item.setSubmenu_(color_menu)
        menu.addItem_(set_color_item)
        menu.addItem_(NSMenuItem.separatorItem())

        show_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Show in Finder", "showAdventureTreeItemInFinder:", "")
        show_item.setTarget_(self)
        show_item.setRepresentedObject_(str(node.path))
        menu.addItem_(show_item)
        menu.addItem_(NSMenuItem.separatorItem())

        rename_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Rename", "renameAdventureTreeItem:", "")
        rename_item.setTarget_(self)
        rename_item.setRepresentedObject_(str(node.path))
        menu.addItem_(rename_item)

        delete_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Delete", "deleteAdventureTreeItem:", "")
        delete_item.setTarget_(self)
        delete_item.setRepresentedObject_(str(node.path))
        menu.addItem_(delete_item)
        return menu

    @objc.python_method
    def adventurePathFromMenuItem(self, sender) -> Path | None:
        raw = sender.representedObject() if sender is not None else None
        if raw is None or self.adventure_vault_path is None:
            return None
        path = Path(str(raw)).resolve()
        if not safe_relative_to(path, self.adventure_vault_path):
            return None
        return path

    def showAdventureTreeItemInFinder_(self, sender):
        path = self.adventurePathFromMenuItem(sender)
        if path is None:
            return
        NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_([NSURL.fileURLWithPath_(str(path))])

    def setAdventureTreeColor_(self, sender):
        if self.adventure_vault_path is None:
            return
        raw = sender.representedObject() if sender is not None else None
        try:
            payload = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        path = Path(str(payload.get("path") or "")).resolve()
        color_name = str(payload.get("color") or "")
        if not safe_relative_to(path, self.adventure_vault_path):
            return
        self.setAdventureColorForPath_color_(path, color_name)

    @objc.python_method
    def adventureRelativePath(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.adventure_vault_path.resolve())).replace("\\", "/")

    @objc.python_method
    def setAdventureColorForPath_color_(self, path: Path, color_name: str):
        data = self.loadAdventureColorData()
        palette_ids = self.ensureAdventureColorPalette(data)
        rel_path = self.adventureRelativePath(path)
        file_colors = [item for item in data.get("fileColors", []) if isinstance(item, dict)]
        file_colors = [item for item in file_colors if str(item.get("path") or "").strip().strip("/") != rel_path]
        if color_name:
            color_id = palette_ids.get(color_name)
            if color_id:
                file_colors.append({"path": rel_path, "color": color_id})
        data["fileColors"] = file_colors
        self.saveAdventureColorData(data)
        self.loadAdventureFileColors()
        self.refreshAdventureTree()

    def renameAdventureTreeItem_(self, sender):
        path = self.adventurePathFromMenuItem(sender)
        if path is None or self.adventure_vault_path is None or not path.exists():
            return
        if not self.confirmAdventureCanDiscardOrSave():
            return

        old_name = path.name
        old_stem = path.stem
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 360, 26))
        field.setStringValue_(old_name)
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Rename")
        alert.setInformativeText_(f"Enter a new name for {old_name}.")
        alert.setAccessoryView_(field)
        alert.addButtonWithTitle_("Rename")
        alert.addButtonWithTitle_("Cancel")
        NSApp.activateIgnoringOtherApps_(True)
        if int(alert.runModal()) != 1000:
            return

        new_name = str(field.stringValue()).strip()
        if not new_name:
            self.showAdventureAlert_message_("Rename failed", "Name cannot be empty.")
            return
        if "/" in new_name or "\\" in new_name or new_name in (".", ".."):
            self.showAdventureAlert_message_("Rename failed", "Name cannot contain path separators.")
            return
        if path.is_file() and path.suffix.lower() in (".md", ".markdown") and Path(new_name).suffix == "":
            new_name = f"{new_name}{path.suffix}"
        destination = (path.parent / new_name).resolve()
        if not safe_relative_to(destination, self.adventure_vault_path):
            self.showAdventureAlert_message_("Rename failed", "Destination is outside the selected folder.")
            return
        if destination.exists():
            self.showAdventureAlert_message_("Rename failed", "A file or folder with that name already exists.")
            return
        try:
            path.rename(destination)
        except OSError as exc:
            log(f"Adventure rename failed: {exc}")
            self.showAdventureAlert_message_("Rename failed", str(exc))
            return

        self.updateAdventureColorPathsAfterRename_old_new_(path, destination)
        if path.is_file() and path.suffix.lower() in (".md", ".markdown"):
            self.updateAdventureWikiLinksForRename_oldStem_newStem_oldRel_newRel_(
                old_stem,
                destination.stem,
                str(Path(self.adventureRelativePath(path)).with_suffix("")).replace("\\", "/"),
                str(Path(self.adventureRelativePath(destination)).with_suffix("")).replace("\\", "/"),
            )
        if self.adventure_selected_note is not None and self.pathContainsPath_parent_child_(path, self.adventure_selected_note):
            if path.is_dir():
                rel = self.adventure_selected_note.resolve().relative_to(path.resolve())
                self.adventure_selected_note = (destination / rel).resolve()
            else:
                self.adventure_selected_note = destination
        self.rebuildAdventureAfterFileAction_select_(self.adventure_selected_note if self.adventure_selected_note and self.adventure_selected_note.exists() else destination)

    def deleteAdventureTreeItem_(self, sender):
        path = self.adventurePathFromMenuItem(sender)
        if path is None or self.adventure_vault_path is None or not path.exists():
            return
        if not self.confirmAdventureCanDiscardOrSave():
            return
        alert = NSAlert.alloc().init()
        alert.setMessageText_(f"Delete {path.name}?")
        alert.setInformativeText_("This moves the item to the macOS Trash.")
        alert.addButtonWithTitle_("Delete")
        alert.addButtonWithTitle_("Cancel")
        NSApp.activateIgnoringOtherApps_(True)
        if int(alert.runModal()) != 1000:
            return
        source = str(path.parent)
        recycle_result = NSWorkspace.sharedWorkspace().performFileOperation_source_destination_files_tag_(
            NSWorkspaceRecycleOperation,
            source,
            "",
            [path.name],
            None,
        )
        ok = bool(recycle_result[0]) if isinstance(recycle_result, tuple) else bool(recycle_result)
        if not ok:
            self.showAdventureAlert_message_("Delete failed", "The item could not be moved to Trash.")
            return
        self.removeAdventureColorPathsForDeletedPath_(path)
        selected_deleted = self.adventure_selected_note is not None and self.pathContainsPath_parent_child_(path, self.adventure_selected_note)
        self.adventure_selected_note = None if selected_deleted else self.adventure_selected_note
        self.rebuildAdventureAfterFileAction_select_(None if selected_deleted else self.adventure_selected_note)

    @objc.python_method
    def showAdventureAlert_message_(self, title: str, message: str):
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.addButtonWithTitle_("OK")
        NSApp.activateIgnoringOtherApps_(True)
        alert.runModal()

    @objc.python_method
    def pathContainsPath_parent_child_(self, parent: Path, child: Path) -> bool:
        parent = parent.resolve()
        child = child.resolve()
        if parent == child:
            return True
        if not parent.is_dir():
            return False
        try:
            child.relative_to(parent)
            return True
        except ValueError:
            return False

    @objc.python_method
    def rebuildAdventureAfterFileAction_select_(self, selected: Path | None):
        if self.adventure_vault_path is None:
            return
        self.loadAdventureFileColors()
        self.buildAdventureIndexes()
        self.adventure_root_node = self.buildAdventureNode(self.adventure_vault_path, 0)
        if self.adventure_root_node is not None:
            self.collectAdventureDirectoryPaths(self.adventure_root_node, self.adventure_expanded_paths)
        self.refreshAdventureTree()
        if selected is not None and selected.exists() and selected.is_file():
            self.openAdventureNote_(selected)
        elif self.adventure_selected_note is None:
            first = self.firstAdventureNote()
            if first is not None:
                self.openAdventureNote_(first)
            else:
                self.showAdventureEmpty_("Select a Markdown note from the left.")
        self.refreshAdventureControls()

    @objc.python_method
    def adventureColorDataPath(self) -> Path:
        return self.adventure_vault_path / ".obsidian" / "plugins" / "obsidian-file-color" / "data.json"

    @objc.python_method
    def loadAdventureColorData(self) -> dict[str, Any]:
        path = self.adventureColorDataPath()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.setdefault("cascadeColors", True)
                    data.setdefault("colorBackground", False)
                    data.setdefault("palette", [])
                    data.setdefault("fileColors", [])
                    return data
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        return {"cascadeColors": True, "colorBackground": False, "palette": [], "fileColors": []}

    @objc.python_method
    def saveAdventureColorData(self, data: dict[str, Any]):
        path = self.adventureColorDataPath()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @objc.python_method
    def ensureAdventureColorPalette(self, data: dict[str, Any]) -> dict[str, str]:
        palette = [item for item in data.get("palette", []) if isinstance(item, dict)]
        result: dict[str, str] = {}
        used_ids = {str(item.get("id")) for item in palette if item.get("id")}
        for color_name, hex_value in ADVENTURE_COLOR_PALETTE:
            existing = None
            for item in palette:
                if str(item.get("name") or "") == color_name or str(item.get("value") or "").lower() == hex_value.lower():
                    existing = item
                    break
            if existing is None:
                color_id = f"arcane-{normalize(color_name).replace(' ', '-') or color_name.lower()}"
                suffix = 2
                base_id = color_id
                while color_id in used_ids:
                    color_id = f"{base_id}-{suffix}"
                    suffix += 1
                existing = {"id": color_id, "name": color_name, "value": hex_value}
                palette.append(existing)
                used_ids.add(color_id)
            result[color_name] = str(existing.get("id"))
        data["palette"] = palette
        return result

    @objc.python_method
    def updateAdventureColorPathsAfterRename_old_new_(self, old_path: Path, new_path: Path):
        data = self.loadAdventureColorData()
        old_rel = self.adventureRelativePath(old_path)
        new_rel = self.adventureRelativePath(new_path)
        for item in data.get("fileColors", []):
            if not isinstance(item, dict):
                continue
            rel = str(item.get("path") or "").strip().strip("/")
            if rel == old_rel:
                item["path"] = new_rel
            elif rel.startswith(old_rel + "/"):
                item["path"] = new_rel + rel[len(old_rel) :]
        self.saveAdventureColorData(data)

    @objc.python_method
    def removeAdventureColorPathsForDeletedPath_(self, path: Path):
        data = self.loadAdventureColorData()
        rel_path = self.adventureRelativePath(path)
        data["fileColors"] = [
            item
            for item in data.get("fileColors", [])
            if isinstance(item, dict)
            and (lambda rel: rel != rel_path and not rel.startswith(rel_path + "/"))(str(item.get("path") or "").strip().strip("/"))
        ]
        self.saveAdventureColorData(data)

    @objc.python_method
    def updateAdventureWikiLinksForRename_oldStem_newStem_oldRel_newRel_(self, old_stem: str, new_stem: str, old_rel: str, new_rel: str):
        if self.adventure_vault_path is None:
            return
        pattern = re.compile(r"(?<!!)\[\[([^\]]+)\]\]")

        def replace_link(match):
            inner = match.group(1)
            target_part, alias = (inner.split("|", 1) + [""])[:2] if "|" in inner else (inner, "")
            target_base, heading = (target_part.split("#", 1) + [""])[:2] if "#" in target_part else (target_part, "")
            normalized_target = normalize(target_base.strip())
            if normalized_target == normalize(old_stem):
                replacement_target = new_stem
            elif normalized_target == normalize(old_rel):
                replacement_target = new_rel
            else:
                return match.group(0)
            if heading:
                replacement_target = f"{replacement_target}#{heading}"
            if alias:
                return f"[[{replacement_target}|{alias}]]"
            return f"[[{replacement_target}]]"

        for md_path in self.adventure_vault_path.rglob("*.md"):
            if any(part.startswith(".") for part in md_path.relative_to(self.adventure_vault_path).parts):
                continue
            try:
                original = md_path.read_text(encoding="utf-8")
            except OSError:
                continue
            updated = pattern.sub(replace_link, original)
            if updated != original:
                try:
                    md_path.write_text(updated, encoding="utf-8")
                except OSError as exc:
                    log(f"Adventure wikilink update failed for {md_path}: {exc}")

    @objc.python_method
    def openAdventureNote_(self, path: Path):
        if self.adventure_vault_path is None or not path.is_file() or not safe_relative_to(path, self.adventure_vault_path):
            return
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.showAdventureEmpty_(f"Could not read note: {exc}")
            return
        self.adventure_selected_note = path.resolve()
        defaults = NSUserDefaults.standardUserDefaults()
        defaults.setObject_forKey_(str(self.adventure_selected_note), ADVENTURE_SELECTED_NOTE_PREF)
        defaults.synchronize()
        for parent in [self.adventure_selected_note.parent, *self.adventure_selected_note.parents]:
            if self.adventure_vault_path is not None and safe_relative_to(parent, self.adventure_vault_path):
                self.adventure_expanded_paths.add(str(parent))
            if parent == self.adventure_vault_path:
                break
        self.adventure_last_saved_text = text
        self.adventure_dirty = False
        if self.adventure_is_editing:
            self.adventure_editor_view.setString_(text)
        else:
            self.renderAdventureMarkdown_(text)
        self.refreshAdventureTree()
        self.refreshAdventureControls()

    @objc.python_method
    def showAdventureEmpty_(self, message: str):
        body = f"<p class='empty'>{html.escape(message)}</p>"
        self.loadAdventureHTMLBody_(body)
        self.adventure_status_label.setStringValue_(message)

    @objc.python_method
    def refreshAdventureControls(self):
        has_vault = self.adventure_vault_path is not None
        has_note = self.adventure_selected_note is not None
        self.adventure_title_label.setStringValue_(self.adventure_vault_path.name if has_vault else "Adventure")
        self.adventure_folder_button.setTitle_("Change Folder" if has_vault else "Choose Folder")
        self.adventure_toggle_button.setEnabled_(has_note)
        self.adventure_toggle_button.setTitle_("Preview" if self.adventure_is_editing else "Edit")
        self.adventure_save_button.setEnabled_(has_note and self.adventure_is_editing and self.adventure_dirty)
        self.adventure_save_button.setHidden_(not self.adventure_is_editing)
        self.adventure_dirty_label.setStringValue_("Unsaved" if self.adventure_dirty else "")
        if has_note and self.adventure_vault_path is not None:
            try:
                rel = str(self.adventure_selected_note.relative_to(self.adventure_vault_path)).replace("/", " / ")
            except ValueError:
                rel = self.adventure_selected_note.name
            self.adventure_status_label.setStringValue_(rel)
        elif has_vault:
            self.adventure_status_label.setStringValue_("Select a Markdown note from the left.")
        else:
            self.adventure_status_label.setStringValue_("Choose a folder of Markdown notes.")
        if self.current_tab == "adventure":
            self.adventure_web_view.setHidden_(self.adventure_is_editing)
            self.adventure_editor_scroll.setHidden_(not self.adventure_is_editing)

    def toggleAdventureMode_(self, _sender):
        if self.adventure_selected_note is None:
            return
        if self.adventure_is_editing:
            text = str(self.adventure_editor_view.string())
            self.adventure_dirty = text != self.adventure_last_saved_text
            self.adventure_is_editing = False
            self.renderAdventureMarkdown_(text)
        else:
            if self.adventure_dirty:
                text = str(self.adventure_editor_view.string())
            else:
                try:
                    text = self.adventure_selected_note.read_text(encoding="utf-8")
                except OSError:
                    text = self.adventure_last_saved_text
                self.adventure_editor_view.setString_(text)
                self.adventure_last_saved_text = text
                self.adventure_dirty = False
            self.adventure_is_editing = True
        self.refreshAdventureControls()
        self.layoutMainWindow()

    def saveAdventureNote_(self, _sender):
        self.saveAdventureCurrentNote()

    @objc.python_method
    def saveAdventureCurrentNote(self) -> bool:
        if self.adventure_selected_note is None or self.adventure_vault_path is None:
            return True
        if not safe_relative_to(self.adventure_selected_note, self.adventure_vault_path):
            return False
        text = str(self.adventure_editor_view.string()) if (self.adventure_is_editing or self.adventure_dirty) else self.adventure_last_saved_text
        try:
            self.adventure_selected_note.write_text(text, encoding="utf-8")
        except OSError as exc:
            alert = NSAlert.alloc().init()
            alert.setMessageText_("Could not save Adventure note")
            alert.setInformativeText_(str(exc))
            alert.addButtonWithTitle_("OK")
            alert.runModal()
            return False
        self.adventure_last_saved_text = text
        self.adventure_dirty = False
        self.buildAdventureIndexes()
        self.refreshAdventureControls()
        return True

    @objc.python_method
    def confirmAdventureCanDiscardOrSave(self) -> bool:
        if not self.adventure_dirty:
            return True
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Save changes to this Adventure note?")
        alert.setInformativeText_("You have unsaved Markdown edits.")
        alert.addButtonWithTitle_("Save")
        alert.addButtonWithTitle_("Discard")
        alert.addButtonWithTitle_("Cancel")
        NSApp.activateIgnoringOtherApps_(True)
        result = int(alert.runModal())
        if result == 1000:
            return self.saveAdventureCurrentNote()
        if result == 1001:
            self.adventure_dirty = False
            return True
        return False

    @objc.python_method
    def renderAdventureMarkdown_(self, markdown: str):
        if MarkdownIt is None:
            self.loadAdventureHTMLBody_("<p class='missing'>Install markdown-it-py to preview Markdown.</p>")
            return
        parser = markdown_parser()
        source = self.prepareAdventureMarkdown(markdown)
        rendered = parser.render(source) if parser is not None else html.escape(source)
        rendered = self.decorateAdventureHTML(rendered)
        self.loadAdventureHTMLBody_(rendered)

    @objc.python_method
    def prepareAdventureMarkdown(self, markdown: str) -> str:
        source = separate_obsidian_callout_titles(strip_markdown_frontmatter(markdown))

        def image_replace(match):
            target = match.group(1).strip()
            parts = [part.strip() for part in target.split("|", 1)]
            image_path = self.resolveAdventureAsset(parts[0])
            if image_path is None:
                alt = html.escape(parts[-1] if len(parts) > 1 else parts[0])
                return f"<p class=\"missing\">Missing image: {alt}</p>"
            alt = html.escape(parts[-1] if len(parts) > 1 else image_path.name)
            return f'<img src="{html.escape(image_path.as_uri())}" alt="{alt}">'

        def wiki_replace(match):
            target = match.group(1).strip()
            if not target:
                return ""
            label = target
            if "|" in target:
                target, label = [part.strip() for part in target.split("|", 1)]
            elif "#" in target:
                label = target.split("#", 1)[0] or target
            return (
                f'<a href="#" data-note="{html.escape(target, quote=True)}">'
                f"{html.escape(label)}</a>"
            )

        def dice_replace(match):
            expression = re.sub(r"\s+", "", match.group(1).strip())
            if not (DICE_PATTERN.fullmatch(expression) or DICE_FORMULA_PATTERN.fullmatch(expression)):
                return match.group(0)
            return (
                f'<a href="#" class="dice-link" data-dice="{html.escape(expression, quote=True)}">'
                f"🎲 {html.escape(expression)}</a>"
            )

        source = re.sub(r"!\[\[([^\]]+)\]\]", image_replace, source)
        source = re.sub(r"(?<!!)\[\[([^\]]+)\]\]", wiki_replace, source)
        source = re.sub(r"`\s*dice:\s*([^`]+)`", dice_replace, source, flags=re.I)
        return source

    @objc.python_method
    def decorateAdventureHTML(self, rendered: str) -> str:
        if BeautifulSoup is None:
            return rendered
        soup = BeautifulSoup(rendered, "html.parser")
        for blockquote in soup.find_all("blockquote"):
            first = blockquote.find(["p", "strong"])
            if first is None:
                continue
            text = first.get_text(" ", strip=True)
            match = re.match(r"\[!(\w+)\]\s*(.*)", text)
            if not match:
                continue
            kind = normalize(match.group(1)).replace(" ", "-") or "note"
            wrapper = soup.new_tag("div")
            wrapper["class"] = f"callout callout-{kind}"
            title_tag = soup.new_tag("div")
            title_tag["class"] = "callout-title"
            for child in list(first.contents):
                if isinstance(child, str):
                    cleaned = re.sub(r"^\[!\w+\]\s*", "", str(child), count=1)
                    if cleaned:
                        title_tag.append(cleaned)
                    continue
                title_tag.append(child.extract())
            if not title_tag.get_text(strip=True):
                title_tag.string = kind.title()
            wrapper.append(title_tag)
            first.extract()
            for child in list(blockquote.contents):
                wrapper.append(child.extract())
            blockquote.replace_with(wrapper)
        return str(soup)

    @objc.python_method
    def loadAdventureHTMLBody_(self, body: str):
        script = """
        <script>
        document.addEventListener('click', function(event) {
          var note = event.target.closest('a[data-note]');
          if (note) {
            event.preventDefault();
            window.webkit.messageHandlers.adventure.postMessage({type: 'note', target: note.dataset.note || ''});
            return;
          }
          var dice = event.target.closest('a[data-dice]');
          if (dice) {
            event.preventDefault();
            window.webkit.messageHandlers.adventure.postMessage({type: 'dice', expression: dice.dataset.dice || ''});
          }
        });
        </script>
        """
        document = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<style>{adventure_markdown_css()}</style></head><body><main>{body}</main>{script}</body></html>"
        )
        base_url = NSURL.fileURLWithPath_(str(self.adventure_vault_path)) if self.adventure_vault_path is not None else None
        self.adventure_web_view.loadHTMLString_baseURL_(document, base_url)

    @objc.python_method
    def resolveAdventureAsset(self, target: str) -> Path | None:
        if self.adventure_vault_path is None:
            return None
        clean = target.split("#", 1)[0].strip()
        candidates = []
        direct = (self.adventure_vault_path / clean).resolve()
        candidates.append(direct)
        if self.adventure_selected_note is not None:
            candidates.append((self.adventure_selected_note.parent / clean).resolve())
        candidates.extend(self.adventure_asset_index.get(normalize(Path(clean).name), []))
        for candidate in candidates:
            if candidate.exists() and candidate.is_file() and safe_relative_to(candidate, self.adventure_vault_path):
                return candidate.resolve()
        return None

    @objc.python_method
    def resolveAdventureNote(self, target: str) -> Path | None:
        if self.adventure_vault_path is None:
            return None
        clean = target.split("#", 1)[0].strip()
        if not clean:
            return self.adventure_selected_note
        possibilities = []
        raw = Path(clean)
        if raw.suffix.lower() not in (".md", ".markdown"):
            raw = raw.with_suffix(".md")
        possibilities.append((self.adventure_vault_path / raw).resolve())
        if self.adventure_selected_note is not None:
            possibilities.append((self.adventure_selected_note.parent / raw).resolve())
        keys = [normalize(clean), normalize(str(Path(clean).with_suffix(""))), normalize(Path(clean).name)]
        for key in keys:
            possibilities.extend(self.adventure_note_index.get(key, []))
        for candidate in possibilities:
            if candidate.exists() and candidate.is_file() and safe_relative_to(candidate, self.adventure_vault_path):
                return candidate.resolve()
        return None

    def userContentController_didReceiveScriptMessage_(self, _user_content_controller, message):
        body = message.body()
        if hasattr(body, "items"):
            payload = dict(body)
        elif hasattr(body, "objectForKey_"):
            payload = {
                key: body.objectForKey_(key)
                for key in ("type", "target", "expression")
                if body.objectForKey_(key) is not None
            }
        else:
            payload = {}
        message_type = str(payload.get("type") or "")
        if message_type == "dice":
            self.rollDice_(str(payload.get("expression") or ""))
            return
        if message_type != "note":
            return
        if not self.confirmAdventureCanDiscardOrSave():
            return
        note = self.resolveAdventureNote(str(payload.get("target") or ""))
        if note is None:
            self.adventure_status_label.setStringValue_("Linked note not found.")
            return
        self.openAdventureNote_(note)

    def refreshDiceHistory(self):
        if self.dice_history_view is not None:
            self.dice_history_view.setString_(format_dice_roll_history())

    def currentDiceExpression(self) -> str:
        parts = []
        for sides in self.dice_presets:
            count = int(self.dice_pool.get(int(sides), 0))
            if count <= 0:
                continue
            parts.append(f"{count}d{sides}")
        return "+".join(parts)

    def refreshDiceFormula_(self, _sender):
        expression = self.currentDiceExpression()
        self.dice_formula_label.setStringValue_(expression or "Click a die")
        for button in self.dice_preset_buttons:
            sides = int(button.tag())
            count = int(self.dice_pool.get(sides, 0))
            button.setTitle_(f"d{sides} x{count}" if count else f"d{sides}")
        self.dice_roll_button.setEnabled_(bool(expression))
        self.dice_clear_button.setEnabled_(bool(expression))

    def addDieToPool_(self, sender):
        sides = int(sender.tag())
        total = sum(int(value) for value in self.dice_pool.values())
        if total >= 40:
            return
        if sides not in self.dice_pool:
            return
        self.dice_pool[sides] = int(self.dice_pool.get(sides, 0)) + 1
        self.dice_result_label.setStringValue_("")
        self.refreshDiceFormula_(None)

    def clearDicePool_(self, _sender):
        for sides in list(self.dice_pool):
            self.dice_pool[sides] = 0
        self.dice_result_label.setStringValue_("")
        self.refreshDiceFormula_(None)

    def rollCustomDice_(self, _sender):
        self.refreshDiceFormula_(None)
        expression = self.currentDiceExpression()
        if not expression:
            self.dice_result_label.setStringValue_("Choose at least one die.")
            return
        self.rollDice_(expression)

    def loadParties(self) -> list[dict[str, Any]]:
        raw = NSUserDefaults.standardUserDefaults().stringForKey_(PARTIES_PREF)
        if raw:
            try:
                parties = json.loads(str(raw))
                if isinstance(parties, list):
                    return [party for party in parties if isinstance(party, dict)]
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        return [{"name": "Default Party", "characters": []}]

    def saveParties(self):
        defaults = NSUserDefaults.standardUserDefaults()
        defaults.setObject_forKey_(json.dumps(self.parties), PARTIES_PREF)
        defaults.synchronize()

    def selectedPartyIndex(self) -> int:
        index = int(self.party_popup.indexOfSelectedItem())
        if index < 0 or index >= len(self.parties):
            return 0
        return index

    def selectedParty(self) -> dict[str, Any]:
        if not self.parties:
            self.parties.append({"name": "Default Party", "characters": []})
        return self.parties[self.selectedPartyIndex()]

    def refreshPartyPopup(self):
        self.party_popup.removeAllItems()
        for party in self.parties:
            self.party_popup.addItemWithTitle_(str(party.get("name") or "Unnamed Party"))
        self.party_popup.selectItemAtIndex_(min(self.selectedPartyIndex(), max(0, len(self.parties) - 1)))
        self.party_popup.setNeedsDisplay_(True)
        self.layoutMainWindow()
        self.syncPartyFields()

    def syncPartyFields(self):
        party = self.selectedParty()
        characters = party.get("characters", [])
        if not isinstance(characters, list):
            characters = []
            party["characters"] = characters
        visible_characters = [character for character in characters if isinstance(character, dict)]
        for index, label in enumerate(self.party_member_labels):
            icon_view = self.party_member_icon_views[index] if index < len(self.party_member_icon_views) else None
            row_labels = (
                self.party_member_name_labels[index],
                self.party_member_class_labels[index],
                self.party_member_ac_labels[index],
            )
            if index >= len(visible_characters):
                label.setHidden_(True)
                if icon_view is not None:
                    icon_view.setHidden_(True)
                for row_label in row_labels:
                    row_label.setHidden_(True)
                continue
            character = visible_characters[index]
            name = str(character.get("name") or "Unnamed")
            class_name = str(character.get("class") or "Fighter")
            ac = str(character.get("ac") or "?")
            label.setStringValue_("")
            label.setHidden_(False)
            if icon_view is not None:
                image = icon_image(class_name)
                icon_view.setImage_(image)
                icon_view.setHidden_(image is None)
            self.party_member_name_labels[index].setStringValue_(name)
            self.party_member_class_labels[index].setStringValue_(class_name)
            self.party_member_ac_labels[index].setStringValue_(f"AC: {ac[:4]}")
            for row_label in row_labels:
                row_label.setHidden_(False)
        if len(visible_characters) > len(self.party_member_labels):
            self.party_status_label.setStringValue_(f"+ {len(visible_characters) - len(self.party_member_labels)} more member(s)")
        elif visible_characters:
            self.party_status_label.setStringValue_(f"{len(visible_characters)} member(s) ready")
        else:
            self.party_status_label.setStringValue_("No characters yet. Create or edit a party.")

    def selectParty_(self, _sender):
        self.party_popup.setNeedsDisplay_(True)
        self.layoutMainWindow()
        self.syncPartyFields()

    def newParty_(self, _sender):
        self.openPartyEditorForIndex_(-1)

    def editParty_(self, _sender):
        self.openPartyEditorForIndex_(self.selectedPartyIndex())

    def deleteParty_(self, _sender):
        if not self.parties:
            return
        index = self.selectedPartyIndex()
        party_name = str(self.parties[index].get("name") or "Unnamed Party")
        alert = NSAlert.alloc().init()
        alert.setMessageText_(f"Delete {party_name}?")
        alert.setInformativeText_("This removes the party from Arcane Manager. Current combatants already in the tracker are not changed.")
        alert.addButtonWithTitle_("Delete")
        alert.addButtonWithTitle_("Cancel")
        NSApp.activateIgnoringOtherApps_(True)
        if int(alert.runModal()) != 1000:
            return
        del self.parties[index]
        if not self.parties:
            self.parties.append({"name": "Default Party", "characters": []})
        self.saveParties()
        self.refreshPartyPopup()
        self.party_popup.selectItemAtIndex_(min(index, len(self.parties) - 1))
        self.syncPartyFields()

    def openPartyEditorForIndex_(self, index: int):
        self.editing_party_index = int(index)
        if 0 <= self.editing_party_index < len(self.parties):
            party = self.parties[self.editing_party_index]
            title = "Edit Party"
        else:
            party = {"name": "New Party", "characters": []}
            title = "New Party"

        characters = party.get("characters", [])
        self.editing_characters = [
            {
                "name": str(character.get("name") or ""),
                "class": str(character.get("class") or "Fighter"),
                "ac": str(character.get("ac") or "?"),
            }
            for character in characters
            if isinstance(character, dict)
        ]

        width = 520
        height = 420
        parent_frame = self.window.frame()
        x = parent_frame.origin.x + (parent_frame.size.width - width) / 2
        y = parent_frame.origin.y + (parent_frame.size.height - height) / 2
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskUtilityWindow
        self.party_editor_panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.party_editor_panel.setTitle_(title)
        self.party_editor_panel.setFloatingPanel_(True)
        self.party_editor_panel.setHidesOnDeactivate_(False)
        self.party_editor_panel.setLevel_(24)
        self.party_editor_panel.setBackgroundColor_(theme_color("panel_alt", 0.97))

        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        title_label = make_label(title, (24, 362, 472, 28), 18, True)
        name_label = make_label("Party name", (24, 322, 100, 24), 13, True)
        self.editor_party_name_field = NSTextField.alloc().initWithFrame_(NSMakeRect(132, 322, 250, 26))
        self.editor_party_name_field.setStringValue_(str(party.get("name") or "New Party"))

        character_label = make_label("Character", (24, 278, 100, 24), 13, True)
        self.editor_character_name_field = NSTextField.alloc().initWithFrame_(NSMakeRect(132, 278, 150, 26))
        self.editor_character_name_field.setPlaceholderString_("Name")
        self.editor_character_class_popup = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(292, 278, 106, 26))
        for class_name in CLASS_OPTIONS:
            self.editor_character_class_popup.addItemWithTitle_(class_name)
        self.editor_character_class_popup.selectItemWithTitle_("Fighter")
        self.editor_character_ac_field = NSTextField.alloc().initWithFrame_(NSMakeRect(406, 278, 44, 26))
        self.editor_character_ac_field.setPlaceholderString_("AC")
        add_button = self._make_button("Add", (458, 278, 44, 26), "addEditorCharacter:")

        edit_label = make_label("Edit member", (24, 236, 100, 24), 13, True)
        self.editor_character_popup = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(132, 236, 190, 26))
        self.editor_character_popup.setTarget_(self)
        self.editor_character_popup.setAction_("selectEditorCharacter:")
        update_button = self._make_button("Update", (334, 236, 70, 26), "updateEditorCharacter:")
        remove_button = self._make_button("Remove", (414, 236, 80, 26), "removeEditorCharacter:")

        list_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(24, 70, 472, 150))
        list_scroll.setHasVerticalScroller_(True)
        list_scroll.setAutohidesScrollers_(False)
        self.editor_character_list = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 448, 150))
        self.editor_character_list.setEditable_(False)
        self.editor_character_list.setFont_(NSFont.monospacedSystemFontOfSize_weight_(12, 0))
        self.editor_character_list.setTextColor_(theme_color("text"))
        self.editor_character_list.setBackgroundColor_(theme_color("surface"))
        list_scroll.setDocumentView_(self.editor_character_list)

        save_button = self._make_button("Save Party", (284, 24, 100, 30), "saveEditorParty:")
        cancel_button = self._make_button("Cancel", (396, 24, 80, 30), "cancelEditorParty:")

        for view in (
            title_label,
            name_label,
            self.editor_party_name_field,
            character_label,
            self.editor_character_name_field,
            self.editor_character_class_popup,
            self.editor_character_ac_field,
            add_button,
            edit_label,
            self.editor_character_popup,
            update_button,
            remove_button,
            list_scroll,
            save_button,
            cancel_button,
        ):
            content.addSubview_(view)
        self.party_editor_panel.setContentView_(content)
        self.refreshEditorCharacterList()
        self.refreshEditorCharacterPopup()
        self.party_editor_panel.makeKeyAndOrderFront_(None)

    def refreshEditorCharacterPopup(self):
        if self.editor_character_popup is None:
            return
        selected = int(self.editor_character_popup.indexOfSelectedItem())
        self.editor_character_popup.removeAllItems()
        if not self.editing_characters:
            self.editor_character_popup.addItemWithTitle_("No members")
            self.editor_character_popup.setEnabled_(False)
            return
        self.editor_character_popup.setEnabled_(True)
        for character in self.editing_characters:
            self.editor_character_popup.addItemWithTitle_(str(character.get("name") or "Unnamed"))
        selected = min(max(0, selected), len(self.editing_characters) - 1)
        self.editor_character_popup.selectItemAtIndex_(selected)

    def selectedEditorCharacterIndex(self) -> int:
        if self.editor_character_popup is None or not self.editing_characters:
            return -1
        index = int(self.editor_character_popup.indexOfSelectedItem())
        if index < 0 or index >= len(self.editing_characters):
            return -1
        return index

    def selectEditorCharacter_(self, _sender):
        index = self.selectedEditorCharacterIndex()
        if index < 0:
            return
        character = self.editing_characters[index]
        self.editor_character_name_field.setStringValue_(str(character.get("name") or ""))
        self.editor_character_class_popup.selectItemWithTitle_(str(character.get("class") or "Fighter"))
        self.editor_character_ac_field.setStringValue_(str(character.get("ac") or ""))

    def refreshEditorCharacterList(self):
        if not self.editing_characters:
            self.editor_character_list.setString_("No characters yet. Add one with name and AC.")
            return
        rows = ["NAME                       CLASS       AC", "-------------------------  ----------  ----"]
        for character in self.editing_characters:
            name = str(character.get("name") or "")[:25].ljust(25)
            class_name = str(character.get("class") or "Fighter")[:10].ljust(10)
            ac = str(character.get("ac") or "?")[:4]
            rows.append(f"{name}  {class_name}  {ac}")
        self.editor_character_list.setString_("\n".join(rows))

    def addEditorCharacter_(self, _sender):
        name = str(self.editor_character_name_field.stringValue()).strip()
        class_name = str(self.editor_character_class_popup.titleOfSelectedItem() or "Fighter")
        ac = str(self.editor_character_ac_field.stringValue()).strip()
        if not name:
            return
        self.editing_characters.append({"name": name, "class": class_name, "ac": ac or "?"})
        self.editor_character_name_field.setStringValue_("")
        self.editor_character_class_popup.selectItemWithTitle_("Fighter")
        self.editor_character_ac_field.setStringValue_("")
        self.refreshEditorCharacterList()
        self.refreshEditorCharacterPopup()

    def updateEditorCharacter_(self, _sender):
        index = self.selectedEditorCharacterIndex()
        if index < 0:
            return
        name = str(self.editor_character_name_field.stringValue()).strip()
        class_name = str(self.editor_character_class_popup.titleOfSelectedItem() or "Fighter")
        ac = str(self.editor_character_ac_field.stringValue()).strip()
        if not name:
            return
        self.editing_characters[index] = {"name": name, "class": class_name, "ac": ac or "?"}
        self.refreshEditorCharacterList()
        self.refreshEditorCharacterPopup()
        self.editor_character_popup.selectItemAtIndex_(index)

    def removeEditorCharacter_(self, _sender):
        index = self.selectedEditorCharacterIndex()
        if index < 0:
            return
        del self.editing_characters[index]
        self.editor_character_name_field.setStringValue_("")
        self.editor_character_class_popup.selectItemWithTitle_("Fighter")
        self.editor_character_ac_field.setStringValue_("")
        self.refreshEditorCharacterList()
        self.refreshEditorCharacterPopup()

    def saveEditorParty_(self, _sender):
        name = str(self.editor_party_name_field.stringValue()).strip() or "Unnamed Party"
        party = {"name": name, "characters": list(self.editing_characters)}
        if 0 <= self.editing_party_index < len(self.parties):
            self.parties[self.editing_party_index] = party
            selected_index = self.editing_party_index
        else:
            self.parties.append(party)
            selected_index = len(self.parties) - 1
        self.saveParties()
        self.refreshPartyPopup()
        self.party_popup.selectItemAtIndex_(selected_index)
        self.syncPartyFields()
        self.party_editor_panel.orderOut_(None)

    def cancelEditorParty_(self, _sender):
        self.party_editor_panel.orderOut_(None)

    def promptInitiativeForCharacter_(self, character: dict[str, Any]) -> int | None:
        name = str(character.get("name") or "Character")
        alert = NSAlert.alloc().init()
        alert.setMessageText_(f"Initiative for {name}")
        alert.setInformativeText_("Enter the initiative rolled at the table.")
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 160, 26))
        field.setStringValue_("")
        alert.setAccessoryView_(field)
        alert.addButtonWithTitle_("Add")
        alert.addButtonWithTitle_("Cancel")
        NSApp.activateIgnoringOtherApps_(True)
        result = alert.runModal()
        if int(result) != 1000:
            return None
        try:
            return int(str(field.stringValue()).strip())
        except ValueError:
            return 0

    def startFight_(self, _sender):
        party = self.selectedParty()
        characters = party.get("characters", [])
        if not isinstance(characters, list):
            return
        self.combatants = [combatant for combatant in self.combatants if combatant.get("kind") != "PC"]
        for character in characters:
            if not isinstance(character, dict):
                continue
            name = str(character.get("name") or "").strip()
            if not name:
                continue
            initiative = self.promptInitiativeForCharacter_(character)
            if initiative is None:
                return
            self.combatants.append(
                {
                    "name": name,
                    "kind": "PC",
                    "class": str(character.get("class") or "Fighter"),
                    "ac": str(character.get("ac") or "?"),
                    "hp": "",
                    "initiative": initiative,
                    "conditions": [],
                }
            )
        self.sortCombatants()
        self.current_turn_index = 0
        self.round_number = 1
        self.refreshTracker()

    def selectedMonsterCrFilter(self) -> str | None:
        selected = self.monster_cr_filter_popup.selectedItem()
        title = str(selected.title()) if selected is not None else ""
        if not title or title == "Any CR":
            return None
        return title.removeprefix("CR ").strip() or None

    def ensureMonsterResultRows_(self, count: int):
        while len(self.monster_result_buttons) < count:
            index = len(self.monster_result_buttons)
            button = SearchResultButton.alloc().initWithFrame_(NSMakeRect(0, 0, 100, MONSTER_RESULT_ROW_HEIGHT))
            button.setTag_(index)
            button.setHidden_(True)
            self.monster_result_buttons.append(button)
            self.monster_results_content.addSubview_(button)

            add_button = RowAddButton.alloc().initWithFrame_(NSMakeRect(0, 0, 28, MONSTER_RESULT_ROW_HEIGHT))
            add_button.setTarget_(self)
            add_button.setAction_("addMonster:")
            add_button.setTag_(index)
            add_button.setHidden_(True)
            add_button.setToolTip_("Add creature to initiative")
            self.monster_add_buttons.append(add_button)
            self.monster_results_content.addSubview_(add_button)

    def searchMonsters_(self, _sender):
        query = str(self.monster_search_field.stringValue()).strip()
        self.monster_results = search_creatures(query, self.creatures, self.selectedMonsterCrFilter())
        self.ensureMonsterResultRows_(len(self.monster_results))
        for index, button in enumerate(self.monster_result_buttons):
            add_button = self.monster_add_buttons[index] if index < len(self.monster_add_buttons) else None
            if index >= len(self.monster_results):
                button.setHidden_(True)
                if add_button is not None:
                    add_button.setHidden_(True)
                continue
            button.configureMonsterResult_(self.monster_results[index])
            button.setHidden_(False)
            if add_button is not None:
                add_button.setHidden_(False)
        if self.monster_results_scroll is not None:
            self.layoutMainWindow()
            self.monster_results_scroll.contentView().scrollToPoint_(NSMakePoint(0, 0))
            self.monster_results_scroll.reflectScrolledClipView_(self.monster_results_scroll.contentView())

    def selectedSpellLevelFilter(self) -> str | None:
        selected = self.spell_level_filter_popup.selectedItem()
        title = str(selected.title()) if selected is not None else ""
        if not title or title == "Any Level":
            return None
        return title

    def selectedSpellSchoolFilter(self) -> str | None:
        selected = self.spell_school_filter_popup.selectedItem()
        title = str(selected.title()) if selected is not None else ""
        if not title or title == "Any School":
            return None
        return title

    def ensureSpellResultRows_(self, count: int):
        while len(self.spell_result_buttons) < count:
            index = len(self.spell_result_buttons)
            button = SearchResultButton.alloc().initWithFrame_(NSMakeRect(0, 0, 100, SPELL_RESULT_ROW_HEIGHT))
            button.setTarget_(self)
            button.setAction_("selectSpellResult:")
            button.setTag_(index)
            button.setHidden_(True)
            self.spell_result_buttons.append(button)
            self.spell_results_content.addSubview_(button)

    def refreshSpellResults_(self, _sender):
        self.refreshSpellResults()

    def setSpellDetailHeaderHidden_(self, hidden: bool):
        for view in self.spell_detail_header_views:
            view.setHidden_(hidden)

    def resizeSpellDetailBody(self):
        if self.spell_detail_scroll is None:
            return
        self.spell_detail_view.layoutManager().ensureLayoutForTextContainer_(self.spell_detail_view.textContainer())
        height = max(
            self.spell_detail_scroll.frame().size.height,
            self.spell_detail_view.layoutManager().usedRectForTextContainer_(self.spell_detail_view.textContainer()).size.height + 24,
        )
        self.spell_detail_view.setFrame_(NSMakeRect(0, 0, self.spell_detail_scroll.frame().size.width - 24, height))
        self.spell_detail_scroll.contentView().scrollToPoint_(NSMakePoint(0, 0))
        self.spell_detail_scroll.reflectScrolledClipView_(self.spell_detail_scroll.contentView())

    def refreshSpellResults(self):
        query = str(self.spell_search_field.stringValue()).strip()
        self.displayed_spells = search_spells(
            query,
            self.spells,
            None,
            self.selectedSpellLevelFilter(),
            self.selectedSpellSchoolFilter(),
        )
        self.ensureSpellResultRows_(len(self.displayed_spells))
        for index, button in enumerate(self.spell_result_buttons):
            if index >= len(self.displayed_spells):
                button.setHidden_(True)
                continue
            spell = self.displayed_spells[index]
            button.configureSpellResult_(spell)
            button.setHidden_(False)
        if self.spell_results_scroll is not None:
            self.layoutMainWindow()
            self.spell_results_scroll.contentView().scrollToPoint_(NSMakePoint(0, 0))
            self.spell_results_scroll.reflectScrolledClipView_(self.spell_results_scroll.contentView())
        if self.displayed_spells:
            self.showSpellInDetail_(self.displayed_spells[0])
        else:
            self.setSpellDetailHeaderHidden_(True)
            self.layoutMainWindow()
            self.spell_detail_view.setString_("No matching spells.")
            self.spell_detail_view.setDiceRanges_([])
            self.resizeSpellDetailBody()

    def selectSpellResult_(self, sender):
        index = int(sender.tag())
        if index < 0 or index >= len(self.displayed_spells):
            return
        self.showSpellInDetail_(self.displayed_spells[index])

    def showSpellInDetail_(self, spell):
        title, meta, body = format_spell_for_detail(spell)
        self.setSpellDetailHeaderHidden_(False)
        self.spell_detail_title_label.setStringValue_(title)
        italian_name = spell.italian_name.strip()
        if italian_name and normalize(italian_name) != normalize(spell.name):
            self.spell_detail_italian_label.setStringValue_(f"({italian_name})")
        else:
            self.spell_detail_italian_label.setStringValue_("")
        self.spell_detail_meta_label.setStringValue_(meta)

        flags = component_flags(spell.components)
        self.spell_v_box.setChecked_(flags["V"])
        self.spell_s_box.setChecked_(flags["S"])
        self.spell_m_box.setChecked_(flags["M"])
        self.spell_component_material_label.setStringValue_(component_material(spell.components))

        stats = [
            f"Range: {spell.range or '-'}",
            f"Duration: {spell.duration or '-'}",
        ]
        if spell.spell_lists:
            stats.append(f"Classes: {', '.join(spell.spell_lists)}")
        self.spell_stats_label.setStringValue_("\n".join(stats))

        attributed = attributed_spell_body(body)
        self.spell_detail_view.textStorage().setAttributedString_(attributed)
        self.spell_detail_view.setDiceRanges_(dice_ranges_for_body(body))
        self.layoutMainWindow()
        self.resizeSpellDetailBody()

    def addMonster_(self, sender):
        index = int(sender.tag())
        if index < 0 or index >= len(self.monster_results):
            return
        creature = self.monster_results[index]
        self.combatants.append(
            {
                "name": creature.name,
                "kind": "Monster",
                "ac": display_ac(creature.ac),
                "hp": str(creature.hp),
                "max_hp": str(creature.hp),
                "initiative": random.randint(1, 20) + ability_modifier(creature.stats[1]),
                "cr": creature.cr,
                "creature_name": creature.name,
                "conditions": [],
            }
        )
        self.sortCombatants()
        self.refreshTracker()

    def sortCombatants(self):
        self.combatants.sort(key=lambda item: int(item.get("initiative") or 0), reverse=True)

    def _combatant_hp_value(self, combatant: dict[str, Any]) -> int | None:
        hp = str(combatant.get("hp") or "").strip()
        if not hp:
            return None
        try:
            return int(hp)
        except ValueError:
            return None

    def _is_combatant_down(self, combatant: dict[str, Any]) -> bool:
        hp = self._combatant_hp_value(combatant)
        return hp is not None and hp <= 0

    def _normalize_current_turn(self):
        if not self.combatants:
            self.current_turn_index = 0
            return
        if self.current_turn_index >= len(self.combatants):
            self.current_turn_index = 0
        if not self._is_combatant_down(self.combatants[self.current_turn_index]):
            return
        for offset in range(1, len(self.combatants) + 1):
            candidate = (self.current_turn_index + offset) % len(self.combatants)
            if not self._is_combatant_down(self.combatants[candidate]):
                self.current_turn_index = candidate
                return

    def nextTurn_(self, _sender):
        if not self.combatants:
            return
        old_index = self.current_turn_index
        for offset in range(1, len(self.combatants) + 1):
            candidate = (self.current_turn_index + offset) % len(self.combatants)
            if not self._is_combatant_down(self.combatants[candidate]):
                self.current_turn_index = candidate
                if candidate <= old_index:
                    self.round_number += 1
                break
        self.refreshTracker()

    def previousTurn_(self, _sender):
        if not self.combatants:
            return
        for offset in range(1, len(self.combatants) + 1):
            candidate = (self.current_turn_index - offset) % len(self.combatants)
            if not self._is_combatant_down(self.combatants[candidate]):
                self.current_turn_index = candidate
                break
        self.refreshTracker()

    def clearTracker_(self, _sender):
        self.combatants = []
        self.current_turn_index = 0
        self.round_number = 1
        self.closeMonsterSheet_(None)
        self.refreshTracker()

    def refreshTracker(self):
        self.tracker_title.setStringValue_(f"Round {self.round_number}")
        if not self.combatants:
            self.turn_label.setStringValue_("")
            self.tracker_view.setPayload_({"combatants": [], "current_turn_index": 0})
            return
        self.sortCombatants()
        self._normalize_current_turn()
        current = self.combatants[self.current_turn_index]
        active_count = sum(1 for combatant in self.combatants if not self._is_combatant_down(combatant))
        self.turn_label.setStringValue_("")
        self.tracker_view.setPayload_(
            {
                "combatants": self.combatants,
                "current_turn_index": self.current_turn_index if active_count else -1,
            }
        )

    def _creature_for_combatant(self, combatant: dict[str, Any]) -> Creature | None:
        name = normalize(str(combatant.get("creature_name") or combatant.get("name") or ""))
        for creature in self.creatures:
            if normalize(creature.name) == name:
                return creature
        return None

    def _format_bonus_entries(self, entries: Any) -> str:
        if not isinstance(entries, list):
            return ""
        parts = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            for key, value in item.items():
                label = str(key).replace("_", " ").title()
                try:
                    number = int(value)
                    bonus = f"+{number}" if number >= 0 else str(number)
                except (TypeError, ValueError):
                    bonus = clean_text(value, MAX_SHORT_FIELD_CHARS)
                parts.append(f"{label} {bonus}")
        return ", ".join(parts)

    def _append_named_entries(self, lines: list[str], title: str, entries: Any):
        if not entries:
            return
        lines.extend(["", f"{title}:"])
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = clean_text(entry.get("name", ""), MAX_SHORT_FIELD_CHARS)
            desc = clean_text(entry.get("desc", ""), MAX_TEXT_FIELD_CHARS)
            damage = clean_text(entry.get("damage_dice", ""), MAX_SHORT_FIELD_CHARS)
            prefix = f"{name}. " if name else ""
            suffix = f" Damage dice: {damage}." if damage and damage not in desc else ""
            text = f"{prefix}{desc}{suffix}".strip()
            if text:
                if lines and lines[-1]:
                    lines.append("")
                lines.append(text)

    def _append_spells(self, lines: list[str], spells_payload: Any):
        if not isinstance(spells_payload, list) or not spells_payload:
            return
        lines.extend(["", "Spells:"])
        for item in spells_payload:
            if isinstance(item, str):
                text = clean_text(item, MAX_TEXT_FIELD_CHARS)
                if text:
                    if lines and lines[-1]:
                        lines.append("")
                    lines.append(text)
            elif isinstance(item, dict):
                for key, value in item.items():
                    heading = clean_text(key, MAX_SHORT_FIELD_CHARS)
                    spell_text = clean_text(value, MAX_TEXT_FIELD_CHARS)
                    if heading or spell_text:
                        if lines and lines[-1]:
                            lines.append("")
                        lines.append(f"{heading}: {spell_text}".strip(": "))

    def _monster_body_for_creature(self, creature: Creature) -> str:
        raw = creature.raw
        hit_dice = clean_text(raw.get("hit_dice", ""), MAX_SHORT_FIELD_CHARS)
        hit_points = f"Hit Points: {creature.hp}"
        if hit_dice:
            hit_points = f"{hit_points} ({hit_dice})"
        lines = [
            f"{creature.size} {creature.creature_type}, {creature.alignment}".strip(" ,"),
            f"Armor Class: {display_ac(creature.ac)}",
            hit_points,
            f"Speed: {creature.speed or '-'}",
            "",
        ]
        saves = self._format_bonus_entries(raw.get("saves"))
        skills = self._format_bonus_entries(raw.get("skillsaves"))
        optional_fields = (
            ("Saving Throws", saves),
            ("Skills", skills),
            ("Damage Vulnerabilities", clean_text(raw.get("damage_vulnerabilities", ""), MAX_TEXT_FIELD_CHARS)),
            ("Damage Resistances", clean_text(raw.get("damage_resistances", ""), MAX_TEXT_FIELD_CHARS)),
            ("Damage Immunities", clean_text(raw.get("damage_immunities", ""), MAX_TEXT_FIELD_CHARS)),
            ("Condition Immunities", clean_text(raw.get("condition_immunities", ""), MAX_TEXT_FIELD_CHARS)),
            ("Senses", clean_text(raw.get("senses", ""), MAX_TEXT_FIELD_CHARS)),
            ("Languages", clean_text(raw.get("languages", ""), MAX_TEXT_FIELD_CHARS)),
            ("Challenge", creature.cr),
        )
        for label, value in optional_fields:
            if value:
                lines.append(f"{label}: {value}")

        self._append_named_entries(lines, "Traits", creature.traits)
        self._append_spells(lines, raw.get("spells"))
        self._append_named_entries(lines, "Actions", creature.actions)
        self._append_named_entries(lines, "Legendary Actions", creature.legendary_actions)
        return "\n".join(line for line in lines if line is not None)

    def openCombatantIndex_(self, index):
        try:
            combatant_index = int(index)
        except (TypeError, ValueError):
            return
        if combatant_index < 0 or combatant_index >= len(self.combatants):
            return
        combatant = self.combatants[combatant_index]
        if combatant.get("kind") != "Monster":
            return
        self.openMonsterSheetForCombatant_(combatant_index)

    def openCombatantStatusMenu_(self, payload):
        if not isinstance(payload, dict):
            return
        try:
            index = int(payload.get("index"))
        except (TypeError, ValueError):
            return
        if index < 0 or index >= len(self.combatants):
            return

        combatant = self.combatants[index]
        selected = normalized_conditions(combatant)
        menu = NSMenu.alloc().init()
        for condition in CONDITION_OPTIONS:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(condition, "toggleCombatantCondition:", "")
            item.setTarget_(self)
            item.setRepresentedObject_({"index": index, "condition": condition})
            item.setState_(1 if condition in selected else 0)
            menu.addItem_(item)
        menu.addItem_(NSMenuItem.separatorItem())
        clear_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Clear conditions", "clearCombatantConditions:", "")
        clear_item.setTarget_(self)
        clear_item.setRepresentedObject_(index)
        clear_item.setEnabled_(bool(selected))
        menu.addItem_(clear_item)

        try:
            point = NSMakePoint(float(payload.get("x", 0)), float(payload.get("y", 0)))
        except (TypeError, ValueError):
            frame = self.tracker_view.bounds()
            point = NSMakePoint(frame.size.width - 120, 40)
        menu.popUpMenuPositioningItem_atLocation_inView_(None, point, self.tracker_view)

    def toggleCombatantCondition_(self, sender):
        payload = sender.representedObject()
        if not isinstance(payload, dict):
            return
        try:
            index = int(payload.get("index"))
        except (TypeError, ValueError):
            return
        condition = str(payload.get("condition") or "").strip()
        if index < 0 or index >= len(self.combatants) or condition not in CONDITION_OPTIONS:
            return
        combatant = self.combatants[index]
        conditions = normalized_conditions(combatant)
        if condition in conditions:
            conditions.remove(condition)
        else:
            conditions.append(condition)
        combatant["conditions"] = conditions
        self.refreshTracker()

    def clearCombatantConditions_(self, sender):
        try:
            index = int(sender.representedObject())
        except (TypeError, ValueError):
            return
        if index < 0 or index >= len(self.combatants):
            return
        self.combatants[index]["conditions"] = []
        self.refreshTracker()

    def _make_hp_adjust_panel(self):
        width = 302
        height = 142
        style = NSWindowStyleMaskBorderless
        panel = ContextInputPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, width, height),
            style,
            NSBackingStoreBuffered,
            False,
        )
        panel.setTitle_("")
        panel.setFloatingPanel_(True)
        panel.setHidesOnDeactivate_(True)
        panel.setOpaque_(False)
        panel.setHasShadow_(True)
        panel.setBackgroundColor_(theme_color("panel_alt", 0.98))

        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        style_layer(content, theme_color("panel_alt"), theme_color("border_soft"), 12, 1)
        amount_label = make_label("Amount", (18, 104, 80, 20), 12, True)
        amount_label.setTextColor_(theme_color("muted"))
        self.hp_adjust_amount_field = NSTextField.alloc().initWithFrame_(NSMakeRect(18, 72, 56, 28))
        self.hp_adjust_amount_field.setStringValue_("1")
        style_number_input(self.hp_adjust_amount_field)

        heal_button = self._make_button("Heal", (92, 72, 72, 30), "applyHpMenuAction:")
        heal_button.setTag_(1)
        damage_button = self._make_button("Damage", (178, 72, 100, 30), "applyHpMenuAction:")
        damage_button.setTag_(-1)

        temp_label = make_label("Temp", (18, 44, 80, 20), 12, True)
        temp_label.setTextColor_(theme_color("muted"))
        self.hp_adjust_temp_field = NSTextField.alloc().initWithFrame_(NSMakeRect(18, 12, 56, 28))
        self.hp_adjust_temp_field.setStringValue_("0")
        style_number_input(self.hp_adjust_temp_field)
        temp_button = self._make_button("Temp HP", (92, 12, 98, 30), "applyHpMenuAction:")
        temp_button.setTag_(2)

        for view in (
            amount_label,
            self.hp_adjust_amount_field,
            heal_button,
            damage_button,
            temp_label,
            self.hp_adjust_temp_field,
            temp_button,
        ):
            content.addSubview_(view)
        panel.setContentView_(content)
        self.hp_adjust_panel = panel

    def openCombatantHpMenu_(self, payload):
        if not isinstance(payload, dict):
            return
        try:
            index = int(payload.get("index"))
        except (TypeError, ValueError):
            return
        if index < 0 or index >= len(self.combatants):
            return
        combatant = self.combatants[index]
        if combatant.get("kind") != "Monster":
            return
        if self.hp_adjust_panel is None:
            self._make_hp_adjust_panel()
        self.hp_adjust_index = index
        self.hp_adjust_amount_field.setStringValue_("1")
        self.hp_adjust_temp_field.setStringValue_(str(combatant.get("temp_hp") or "0"))

        frame = self.hp_adjust_panel.frame()
        try:
            point = NSMakePoint(float(payload.get("x", 0)), float(payload.get("y", 0)))
            screen_point = self.window.convertPointToScreen_(point)
            x = screen_point.x - frame.size.width + 44
            y = screen_point.y - frame.size.height - 12
        except Exception:
            parent = self.window.frame()
            x = parent.origin.x + parent.size.width / 2 - frame.size.width / 2
            y = parent.origin.y + parent.size.height / 2 - frame.size.height / 2
        screen_frame = NSScreen.mainScreen().visibleFrame()
        margin = 12
        x = max(screen_frame.origin.x + margin, min(x, screen_frame.origin.x + screen_frame.size.width - frame.size.width - margin))
        y = max(screen_frame.origin.y + margin, min(y, screen_frame.origin.y + screen_frame.size.height - frame.size.height - margin))
        self.hp_adjust_panel.setFrameOrigin_(NSMakePoint(x, y))
        self.hp_adjust_panel.makeKeyAndOrderFront_(None)
        self.hp_adjust_panel.makeFirstResponder_(self.hp_adjust_amount_field)
        self.hp_adjust_amount_field.selectText_(None)

    def closeCombatantHpMenu_(self, _sender):
        if self.hp_adjust_panel is not None:
            self.hp_adjust_panel.orderOut_(None)

    def applyHpMenuAction_(self, sender):
        index = self.hp_adjust_index
        if index < 0 or index >= len(self.combatants):
            return
        combatant = self.combatants[index]
        try:
            action = int(sender.tag())
        except (TypeError, ValueError):
            return
        amount_field = self.hp_adjust_temp_field if action == 2 else self.hp_adjust_amount_field
        try:
            amount = abs(int(str(amount_field.stringValue()).strip()))
        except ValueError:
            return
        if action == 2:
            combatant["temp_hp"] = str(amount)
        else:
            current_hp = self._combatant_hp_value(combatant)
            if current_hp is None:
                try:
                    current_hp = int(str(combatant.get("max_hp") or "0"))
                except ValueError:
                    current_hp = 0
            try:
                max_hp = int(str(combatant.get("max_hp") or "0"))
            except ValueError:
                max_hp = 0
            try:
                temp_hp = max(0, int(str(combatant.get("temp_hp") or "0")))
            except ValueError:
                temp_hp = 0
            if action < 0:
                absorbed = min(temp_hp, amount)
                temp_hp -= absorbed
                amount -= absorbed
                combatant["temp_hp"] = str(temp_hp)
                next_hp = current_hp - amount
            else:
                next_hp = current_hp + amount
                if max_hp > 0:
                    next_hp = min(max_hp, next_hp)
            combatant["hp"] = str(max(0, next_hp))
        if self.hp_adjust_panel is not None:
            self.hp_adjust_panel.orderOut_(None)
        self.refreshTracker()

    def adjustCombatantHp_(self, payload):
        if not isinstance(payload, dict):
            return
        try:
            index = int(payload.get("index"))
            direction = int(payload.get("delta"))
        except (TypeError, ValueError):
            return
        if index < 0 or index >= len(self.combatants):
            return
        combatant = self.combatants[index]
        if combatant.get("kind") != "Monster":
            return

        name = str(combatant.get("name") or "Monster")
        action = "damage" if direction < 0 else "healing"
        alert = NSAlert.alloc().init()
        alert.setMessageText_(f"Apply {action} to {name}")
        alert.setInformativeText_("Enter the amount.")
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 160, 26))
        field.setStringValue_("0")
        alert.setAccessoryView_(field)
        alert.addButtonWithTitle_("Apply")
        alert.addButtonWithTitle_("Cancel")
        NSApp.activateIgnoringOtherApps_(True)
        if int(alert.runModal()) != 1000:
            return
        try:
            amount = abs(int(str(field.stringValue()).strip()))
        except ValueError:
            return
        current_hp = self._combatant_hp_value(combatant)
        if current_hp is None:
            try:
                current_hp = int(str(combatant.get("max_hp") or "0"))
            except ValueError:
                current_hp = 0
        combatant["hp"] = str(max(0, current_hp + direction * amount))
        self.refreshTracker()

    def openMonsterSheetForCombatant_(self, index: int):
        if index < 0 or index >= len(self.combatants):
            return
        combatant = self.combatants[index]
        creature = self._creature_for_combatant(combatant)
        if creature is None:
            return

        self.monster_sheet_combatant_index = index
        self.monster_sheet_title.setStringValue_(creature.name)
        self.monster_sheet_hp_field.setStringValue_(str(combatant.get("hp") or creature.hp))
        self.monster_sheet_roll_label.setStringValue_("")
        stat_names = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
        for button, name, score in zip(self.monster_sheet_ability_buttons, stat_names, creature.stats):
            button.configure_stat(name, score, ability_modifier(score), self)

        body = self._monster_body_for_creature(creature)
        dice_ranges = monster_roll_ranges_for_body(body)
        spell_ranges = spell_ranges_for_body(body, self.spells, spell_section_ranges(body))
        self.monster_sheet_body.textStorage().setAttributedString_(attributed_monster_body(body, spell_ranges, dice_ranges))
        self.monster_sheet_body.setDiceRanges_(dice_ranges)
        self.monster_sheet_body.setSpellRanges_(spell_ranges)
        self.monster_sheet_drawer.setHidden_(False)
        self.layoutMainWindow()

    def closeMonsterSheet_(self, _sender):
        self.monster_sheet_combatant_index = -1
        self.monster_sheet_title.setStringValue_("")
        self.monster_sheet_roll_label.setStringValue_("")
        self.monster_sheet_body.setString_("")
        self.monster_sheet_body.setDiceRanges_([])
        self.monster_sheet_body.setSpellRanges_([])
        self.monster_sheet_drawer.setHidden_(True)
        self.layoutMainWindow()

    def saveMonsterHp_(self, _sender):
        index = self.monster_sheet_combatant_index
        if index < 0 or index >= len(self.combatants):
            return
        hp = str(self.monster_sheet_hp_field.stringValue()).strip()
        try:
            hp_value = int(hp)
        except ValueError:
            hp_value = 0
        self.combatants[index]["hp"] = str(max(0, hp_value))
        self.refreshTracker()

    def rollDice_(self, expression):
        expression = str(expression).strip()
        if not (DICE_PATTERN.fullmatch(expression) or DICE_FORMULA_PATTERN.fullmatch(expression)):
            result = f"Invalid dice expression: {expression}"
            self.displayDiceRollResult_(result)
            return
        self.displayDiceRollResult_(f"Rolling {expression}...")
        if show_3d_dice_roll(expression, self):
            return
        try:
            result = roll_dice_formula(expression)
            if DICE_PATTERN.fullmatch(expression):
                show_dice_roll_animation(roll_dice(expression))
        except ValueError as exc:
            result = str(exc)
        self.displayDiceRollResult_(result)

    def displayDiceRollResult_(self, result):
        record_dice_roll_history(result)
        if self.dice_result_label is not None and self.current_tab == "dice":
            self.dice_result_label.setStringValue_(result)

    def openSpell_(self, spell):
        if spell is None:
            return
        self.current_tab = "spells"
        self.spell_search_field.setStringValue_(spell.name)
        self.spell_level_filter_popup.selectItemWithTitle_("Any Level")
        self.spell_school_filter_popup.selectItemWithTitle_("Any School")
        self.applyCurrentTab()
        self.refreshSpellResults()
        if spell not in self.displayed_spells:
            self.displayed_spells = [spell, *self.displayed_spells]
            self.ensureSpellResultRows_(len(self.displayed_spells))
            for index, button in enumerate(self.spell_result_buttons):
                if index >= len(self.displayed_spells):
                    button.setHidden_(True)
                    continue
                button.configureSpellResult_(self.displayed_spells[index])
                button.setHidden_(False)
            self.layoutMainWindow()
        self.showSpellInDetail_(spell)
        self.window.makeKeyAndOrderFront_(None)

    def windowShouldClose_(self, _sender):
        return self.confirmAdventureCanDiscardOrSave()

    def windowWillClose_(self, _notification):
        if self in DICE_HISTORY_LISTENERS:
            DICE_HISTORY_LISTENERS.remove(self)
        NSApp.terminate_(None)


class SettingsController(NSObject):
    panel: NSPanel
    app_delegate: Any
    color_well_keys: dict[int, tuple[str, str]]
    color_wells: list[Any]

    def initWithAppDelegate_(self, app_delegate):
        self = objc.super(SettingsController, self).init()
        if self is None:
            return None
        self.app_delegate = app_delegate
        self.color_well_keys = {}
        self.color_wells = []

        width = 520
        height = 620
        screen = NSScreen.mainScreen().visibleFrame()
        x = screen.origin.x + (screen.size.width - width) / 2
        y = screen.origin.y + (screen.size.height - height) / 2
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskUtilityWindow
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setTitle_("Arcane Manager Settings")
        self.panel.setFloatingPanel_(True)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setLevel_(24)
        self.panel.setBackgroundColor_(theme_color("panel_alt", 0.98))

        content_height = 58 + (len(THEME_COLOR_LABELS) + len(DICE_THEME_COLOR_LABELS)) * 34 + 96
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(False)
        scroll.setDrawsBackground_(False)
        scroll.setBorderType_(0)
        content = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, width, content_height))
        scroll.setDocumentView_(content)

        y_cursor = 24
        title = make_label("Theme Colors", (24, y_cursor, 260, 28), 20, True)
        content.addSubview_(title)
        reset_button = NSButton.alloc().initWithFrame_(NSMakeRect(width - 150, y_cursor, 126, 30))
        reset_button.setTitle_("Reset Theme")
        reset_button.setTarget_(self)
        reset_button.setAction_("resetTheme:")
        style_layer(reset_button, theme_color("surface"), theme_color("border_soft"), 8, 1)
        content.addSubview_(reset_button)
        y_cursor += 46

        y_cursor = self._addSection_title_rows_originY_content_("App Theme", THEME_COLOR_LABELS, y_cursor, content)
        y_cursor += 18
        self._addSection_title_rows_originY_content_("Dice Overlay", DICE_THEME_COLOR_LABELS, y_cursor, content)

        self.panel.setContentView_(scroll)
        return self

    @objc.python_method
    def _addSection_title_rows_originY_content_(self, title_text, rows, y_cursor, content):
        section_label = make_label(str(title_text), (24, y_cursor, 240, 24), 15, True)
        section_label.setTextColor_(theme_color("gold"))
        content.addSubview_(section_label)
        y_cursor += 32
        section = "app" if str(title_text) == "App Theme" else "dice"
        for key, label_text in rows:
            label = make_label(str(label_text), (40, y_cursor + 5, 260, 20), 13, True)
            label.setTextColor_(theme_color("text"))
            well = NSColorWell.alloc().initWithFrame_(NSMakeRect(330, y_cursor, 44, 24))
            well.setTarget_(self)
            well.setAction_("themeColorChanged:")
            tag = len(self.color_wells) + 1
            well.setTag_(tag)
            self.color_well_keys[tag] = (section, key)
            self.color_wells.append(well)
            content.addSubview_(label)
            content.addSubview_(well)
            y_cursor += 34
        return y_cursor

    @objc.python_method
    def syncColorWells(self):
        for well in self.color_wells:
            section, key = self.color_well_keys.get(int(well.tag()), ("", ""))
            if section == "app" and key in THEME_RGB:
                well.setColor_(theme_color(key))
            elif section == "dice" and key in DICE_THEME_RGB:
                red, green, blue = DICE_THEME_RGB[key]
                well.setColor_(ui_color(red, green, blue, 1.0))

    def show_(self, _sender):
        self.panel.setBackgroundColor_(theme_color("panel_alt", 0.98))
        self.syncColorWells()
        NSApp.activateIgnoringOtherApps_(True)
        self.panel.makeKeyAndOrderFront_(None)

    def themeColorChanged_(self, sender):
        section, key = self.color_well_keys.get(int(sender.tag()), ("", ""))
        rgb = hex_to_rgb(color_to_hex(sender.color()))
        if rgb is None:
            return
        if section == "app" and key in THEME_RGB:
            THEME_RGB[key] = rgb
        elif section == "dice" and key in DICE_THEME_RGB:
            DICE_THEME_RGB[key] = rgb
        else:
            return
        save_theme_overrides()
        self.app_delegate.applyThemeFromSettings()

    def resetTheme_(self, _sender):
        reset_theme_overrides()
        self.syncColorWells()
        self.app_delegate.applyThemeFromSettings()


class AppDelegate(NSObject):
    spells: list[Spell]
    creatures: list[Creature]
    spell_lookup: dict[str, Spell]
    status_item: Any
    main_controller: MainWindowController
    settings_controller: SettingsController

    def initWithSpells_creatures_spellLookup_(
        self,
        spells,
        creatures,
        spell_lookup,
    ):
        self = objc.super(AppDelegate, self).init()
        if self is None:
            return None
        self.spells = list(spells)
        self.creatures = list(creatures)
        self.spell_lookup = spell_lookup
        self.status_item = None
        self.main_controller = None
        self.settings_controller = None
        return self

    def applicationDidFinishLaunching_(self, _notification):
        load_theme_overrides()
        self.main_controller = MainWindowController.alloc().initWithBestiary_spells_spellLookup_(
            self.creatures,
            self.spells,
            self.spell_lookup,
        )
        APP_RETAINED_OBJECTS.append(self.main_controller)
        self.installMainMenu()
        self.installStatusMenu()
        self.main_controller.show_(None)

    def installMainMenu(self):
        main_menu = NSMenu.alloc().init()
        app_menu_item = NSMenuItem.alloc().init()
        main_menu.addItem_(app_menu_item)

        app_menu = NSMenu.alloc().init()
        about_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "About Arcane Manager",
            "showAbout:",
            "",
        )
        about_item.setTarget_(self)
        app_menu.addItem_(about_item)
        app_menu.addItem_(NSMenuItem.separatorItem())

        settings_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Settings...",
            "showSettings:",
            ",",
        )
        settings_item.setTarget_(self)
        app_menu.addItem_(settings_item)
        app_menu.addItem_(NSMenuItem.separatorItem())

        main_window_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Show Main Window",
            "showMainWindow:",
            "0",
        )
        main_window_item.setTarget_(self)
        app_menu.addItem_(main_window_item)
        app_menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit Arcane Manager", "quit:", "q")
        quit_item.setTarget_(self)
        app_menu.addItem_(quit_item)

        app_menu_item.setSubmenu_(app_menu)

        edit_menu_item = NSMenuItem.alloc().init()
        main_menu.addItem_(edit_menu_item)
        edit_menu = NSMenu.alloc().initWithTitle_("Edit")
        undo_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Undo", "undo:", "z")
        edit_menu.addItem_(undo_item)
        redo_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Redo", "redo:", "Z")
        edit_menu.addItem_(redo_item)
        edit_menu.addItem_(NSMenuItem.separatorItem())
        cut_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Cut", "cut:", "x")
        edit_menu.addItem_(cut_item)
        copy_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Copy", "copy:", "c")
        edit_menu.addItem_(copy_item)
        paste_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Paste", "paste:", "v")
        edit_menu.addItem_(paste_item)
        edit_menu.addItem_(NSMenuItem.separatorItem())
        select_all_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Select All", "selectAll:", "a")
        edit_menu.addItem_(select_all_item)
        edit_menu_item.setSubmenu_(edit_menu)
        NSApp.setMainMenu_(main_menu)

    def installStatusMenu(self):
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        button = self.status_item.button()
        if button is not None:
            button.setTitle_("AW")
            button.setToolTip_("Arcane Manager")

        menu = NSMenu.alloc().init()
        about_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "About Arcane Manager",
            "showAbout:",
            "",
        )
        about_item.setTarget_(self)
        menu.addItem_(about_item)
        menu.addItem_(NSMenuItem.separatorItem())

        settings_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Settings...",
            "showSettings:",
            "",
        )
        settings_item.setTarget_(self)
        menu.addItem_(settings_item)
        menu.addItem_(NSMenuItem.separatorItem())

        main_window_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Show Main Window",
            "showMainWindow:",
            "",
        )
        main_window_item.setTarget_(self)
        menu.addItem_(main_window_item)
        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit Arcane Manager", "quit:", "q")
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)
        self.status_item.setMenu_(menu)

    def showMainWindow_(self, _sender):
        self.main_controller.show_(None)

    def showSettings_(self, _sender):
        if self.settings_controller is None:
            self.settings_controller = SettingsController.alloc().initWithAppDelegate_(self)
            APP_RETAINED_OBJECTS.append(self.settings_controller)
        self.settings_controller.show_(None)

    @objc.python_method
    def applyThemeFromSettings(self):
        if self.main_controller is not None:
            self.main_controller.applyTheme()
        if self.settings_controller is not None:
            self.settings_controller.panel.setBackgroundColor_(theme_color("panel_alt", 0.98))
        if THREE_D_DICE_ROLLER is not None:
            THREE_D_DICE_ROLLER.applyTheme()

    def showAbout_(self, _sender):
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Arcane Manager")
        alert.setInformativeText_(
            "A Dungeons & Dragons 5e table assistant with spells, bestiary, "
            "initiative tracking, and dice rolling.\n\n"
            "Developed by Giulio Maffei and Francesco Di Castri."
        )
        alert.addButtonWithTitle_("OK")
        NSApp.activateIgnoringOtherApps_(True)
        alert.runModal()

    def applicationShouldTerminateAfterLastWindowClosed_(self, _sender):
        return False

    def quit_(self, _sender):
        if self.main_controller is not None and not self.main_controller.confirmAdventureCanDiscardOrSave():
            return
        NSApp.terminate_(None)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Arcane Manager for macOS.")
    parser.add_argument(
        "--spells",
        default=str(DEFAULT_SPELLS_FILE),
        help="Path to a JSON spell database.",
    )
    parser.add_argument(
        "--bestiary",
        default=str(DEFAULT_BESTIARY_FILE),
        help="Path to a JSON SRD bestiary database.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    spells, lookup = load_spells(Path(args.spells).expanduser())
    creatures = load_bestiary(Path(args.bestiary).expanduser())
    if not spells:
        raise SystemExit("No spells found in the spell database.")

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)

    delegate = AppDelegate.alloc().initWithSpells_creatures_spellLookup_(
        spells,
        creatures,
        lookup,
    )
    APP_RETAINED_OBJECTS.append(delegate)
    log(f"Starting app with {len(spells)} spells and {len(creatures)} creatures.")
    app.setDelegate_(delegate)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Arcane Manager for macOS.

A local Dungeons & Dragons table assistant with an initiative tracker,
spell reference, bestiary lookup, and dice roller.
"""

from __future__ import annotations

import argparse
import ctypes
import functools
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
    import objc
    warnings.filterwarnings("ignore", category=objc.ObjCPointerWarning)
    from AppKit import (
        NSApp,
        NSAlternateKeyMask,
        NSApplication,
        NSApplicationActivationPolicyRegular,
        NSAlert,
        NSBackingStoreBuffered,
        NSBezierPath,
        NSButton,
        NSColor,
        NSCommandKeyMask,
        NSControlKeyMask,
        NSCursor,
        NSEvent,
        NSEventMaskKeyDown,
        NSFont,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSGraphicsContext,
        NSImage,
        NSImageView,
        NSStringDrawingUsesFontLeading,
        NSStringDrawingUsesLineFragmentOrigin,
        NSMakeRect,
        NSMenu,
        NSMenuItem,
        NSPanel,
        NSPopUpButton,
        NSProgressIndicator,
        NSScrollView,
        NSScreen,
        NSStatusBar,
        NSShiftKeyMask,
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
        NSWindowStyleMaskResizable,
        NSWindowStyleMaskTitled,
        NSWindowStyleMaskUtilityWindow,
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
GLOBAL_HOTKEY_DELEGATE: Any = None
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


def four_char_code(value: str) -> int:
    encoded = value.encode("macroman")
    result = 0
    for byte in encoded:
        result = (result << 8) | byte
    return result


class CarbonEventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class CarbonEventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


CARBON_EVENT_HANDLER_TYPE = ctypes.CFUNCTYPE(
    ctypes.c_int32,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
)
CARBON_HOTKEY_SIGNATURE = four_char_code("AWHK")
CARBON_EVENT_CLASS_KEYBOARD = four_char_code("keyb")
CARBON_EVENT_HOTKEY_PRESSED = 5
CARBON_CMD_KEY = 1 << 8
CARBON_SHIFT_KEY = 1 << 9
CARBON_OPTION_KEY = 1 << 11
CARBON_CONTROL_KEY = 1 << 12
SEARCH_HOTKEY_PREF = "SearchHotkey"
PARTIES_PREF = "InitiativeParties"
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
DEFAULT_SEARCH_HOTKEY_KEY = " "
DEFAULT_SEARCH_HOTKEY_KEY_CODE = 49
DEFAULT_SEARCH_HOTKEY_MODIFIERS = int(NSCommandKeyMask | NSShiftKeyMask)
SUPPORTED_HOTKEY_MODIFIERS = int(NSCommandKeyMask | NSShiftKeyMask | NSAlternateKeyMask | NSControlKeyMask)
HOTKEY_KEY_CODE_BY_KEY = {
    "a": 0,
    "s": 1,
    "d": 2,
    "f": 3,
    "h": 4,
    "g": 5,
    "z": 6,
    "x": 7,
    "c": 8,
    "v": 9,
    "b": 11,
    "q": 12,
    "w": 13,
    "e": 14,
    "r": 15,
    "y": 16,
    "t": 17,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "6": 22,
    "5": 23,
    "=": 24,
    "9": 25,
    "7": 26,
    "-": 27,
    "8": 28,
    "0": 29,
    "]": 30,
    "o": 31,
    "u": 32,
    "[": 33,
    "i": 34,
    "p": 35,
    "l": 37,
    "j": 38,
    "'": 39,
    "k": 40,
    ";": 41,
    "\\": 42,
    ",": 43,
    "/": 44,
    "n": 45,
    "m": 46,
    ".": 47,
    " ": 49,
}


def carbon_modifier_flags(appkit_modifiers: int) -> int:
    flags = 0
    if appkit_modifiers & int(NSCommandKeyMask):
        flags |= CARBON_CMD_KEY
    if appkit_modifiers & int(NSShiftKeyMask):
        flags |= CARBON_SHIFT_KEY
    if appkit_modifiers & int(NSAlternateKeyMask):
        flags |= CARBON_OPTION_KEY
    if appkit_modifiers & int(NSControlKeyMask):
        flags |= CARBON_CONTROL_KEY
    return flags


def load_carbon_framework():
    carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
    carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
    carbon.InstallEventHandler.argtypes = [
        ctypes.c_void_p,
        CARBON_EVENT_HANDLER_TYPE,
        ctypes.c_uint32,
        ctypes.POINTER(CarbonEventTypeSpec),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    carbon.InstallEventHandler.restype = ctypes.c_int32
    carbon.RegisterEventHotKey.argtypes = [
        ctypes.c_uint32,
        ctypes.c_uint32,
        CarbonEventHotKeyID,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    carbon.RegisterEventHotKey.restype = ctypes.c_int32
    carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
    carbon.UnregisterEventHotKey.restype = ctypes.c_int32
    return carbon


@dataclass(frozen=True)
class Hotkey:
    modifiers: int
    key: str
    key_code: int


def default_search_hotkey() -> Hotkey:
    return Hotkey(DEFAULT_SEARCH_HOTKEY_MODIFIERS, DEFAULT_SEARCH_HOTKEY_KEY, DEFAULT_SEARCH_HOTKEY_KEY_CODE)


def hotkey_key_display(key: str) -> str:
    if key == " ":
        return "Space"
    return key.upper()


def hotkey_display(hotkey: Hotkey) -> str:
    parts = []
    for mask, name in (
        (NSCommandKeyMask, "Cmd"),
        (NSShiftKeyMask, "Shift"),
        (NSAlternateKeyMask, "Option"),
        (NSControlKeyMask, "Ctrl"),
    ):
        if hotkey.modifiers & int(mask):
            parts.append(name)
    parts.append(hotkey_key_display(hotkey.key))
    return "+".join(parts)


def normalized_hotkey_key(value: Any) -> str:
    key = str(value or "")
    if key == " ":
        return key
    return key[:1].lower()


def valid_hotkey(hotkey: Hotkey) -> bool:
    if not hotkey.key or hotkey.key_code < 0:
        return False
    needs_primary_modifier = int(NSCommandKeyMask | NSAlternateKeyMask | NSControlKeyMask)
    return bool(hotkey.modifiers & needs_primary_modifier)


def key_code_for_key(key: str) -> int:
    return HOTKEY_KEY_CODE_BY_KEY.get(key, -1)


def load_search_hotkey() -> Hotkey:
    defaults = NSUserDefaults.standardUserDefaults()
    raw = defaults.stringForKey_(SEARCH_HOTKEY_PREF)
    if raw:
        try:
            payload = json.loads(str(raw))
            key = normalized_hotkey_key(payload.get("key", DEFAULT_SEARCH_HOTKEY_KEY))
            hotkey = Hotkey(
                int(payload.get("modifiers", DEFAULT_SEARCH_HOTKEY_MODIFIERS)) & SUPPORTED_HOTKEY_MODIFIERS,
                key,
                int(payload.get("key_code", key_code_for_key(key))),
            )
            if valid_hotkey(hotkey):
                return hotkey
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return default_search_hotkey()


def save_search_hotkey(hotkey: Hotkey):
    payload = json.dumps({"modifiers": int(hotkey.modifiers), "key": hotkey.key, "key_code": int(hotkey.key_code)})
    defaults = NSUserDefaults.standardUserDefaults()
    defaults.setObject_forKey_(payload, SEARCH_HOTKEY_PREF)
    defaults.synchronize()


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


def search_creatures(query: str, creatures: list[Creature], limit: int = 8) -> list[Creature]:
    normalized_query = normalize(query)
    if not normalized_query:
        return creatures[:limit]

    ranked: list[tuple[float, str, Creature]] = []
    compact_query = normalized_query.replace(" ", "")
    for creature in creatures:
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
            ranked.append((score, creature.name, creature))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [creature for _score, _name, creature in ranked[:limit]]


def format_spell_for_overlay(spell: Spell) -> tuple[str, str, str]:
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
    dice_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.58, 0.95, 0.28, 1.0)
    component_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.82, 0.26, 1.0)
    attributes = {
        NSFontAttributeName: NSFont.systemFontOfSize_(14),
        NSForegroundColorAttributeName: NSColor.whiteColor(),
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
    dice_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.58, 0.95, 0.28, 1.0)
    spell_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.82, 0.26, 1.0)
    attributes = {
        NSFontAttributeName: NSFont.systemFontOfSize_(13),
        NSForegroundColorAttributeName: NSColor.whiteColor(),
    }
    attributed = NSMutableAttributedString.alloc().initWithString_attributes_(body, attributes)
    for line in body.splitlines():
        if line.endswith(":"):
            start = body.find(line)
            if start >= 0:
                attributed.addAttribute_value_range_(
                    NSFontAttributeName,
                    NSFont.boldSystemFontOfSize_(14),
                    NSMakeRange(start, len(line)),
                )
    for start, length, _expression in (roll_ranges if roll_ranges is not None else dice_ranges_for_body(body)):
        attributed.addAttribute_value_range_(
            NSForegroundColorAttributeName,
            dice_color,
            NSMakeRange(start, length),
        )
    add_colored_ranges(attributed, spell_ranges, spell_color)
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
        NSForegroundColorAttributeName: NSColor.whiteColor(),
    }
    attributed = NSMutableAttributedString.alloc().initWithString_attributes_(body, attributes)
    muted = ui_color(0.48, 0.48, 0.50, 1.0)
    healthy = ui_color(0.10, 0.78, 0.52, 1.0)
    danger = ui_color(1.0, 0.18, 0.39, 1.0)
    down = ui_color(0.55, 0.12, 0.18, 1.0)
    current_color = ui_color(1.0, 0.82, 0.26, 1.0)
    for start, length, ratio in bar_ranges:
        color = muted if ratio is None else down if ratio <= 0 else danger if ratio <= 0.35 else healthy
        attributed.addAttribute_value_range_(NSForegroundColorAttributeName, color, NSMakeRange(start, length))
    for start, length in current_ranges:
        attributed.addAttribute_value_range_(NSForegroundColorAttributeName, current_color, NSMakeRange(start, length))
        attributed.addAttribute_value_range_(NSFontAttributeName, NSFont.monospacedSystemFontOfSize_weight_(13, 0.35), NSMakeRange(start, length))
    return attributed


class CheckboxSquareView(NSView):
    checked: bool

    def initWithFrame_(self, frame):
        self = objc.super(CheckboxSquareView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.checked = False
        return self

    def setChecked_(self, checked):
        self.checked = bool(checked)
        self.setNeedsDisplay_(True)

    def drawRect_(self, _rect):
        bounds = self.bounds()
        box = NSMakeRect(1, 1, bounds.size.width - 2, bounds.size.height - 2)

        NSColor.whiteColor().set()
        path = NSBezierPath.bezierPathWithRect_(box)
        if self.checked:
            path.fill()
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
        ui_color(0.00, 0.00, 0.00, 0.38).set()
        shadow.fill()

        side = NSBezierPath.bezierPath()
        side.moveToPoint_(NSMakePoint(x + size, y + 8))
        side.lineToPoint_(NSMakePoint(x + size + 12, y + 18))
        side.lineToPoint_(NSMakePoint(x + size + 12, y + size - 8))
        side.lineToPoint_(NSMakePoint(x + size, y + size))
        side.closePath()
        (ui_color(0.08, 0.55, 0.43, 1.0) if active else ui_color(0.22, 0.22, 0.24, 1.0)).set()
        side.fill()

        top = NSBezierPath.bezierPath()
        top.moveToPoint_(NSMakePoint(x + 8, y + size))
        top.lineToPoint_(NSMakePoint(x + 20, y + size + 10))
        top.lineToPoint_(NSMakePoint(x + size + 12, y + size + 10))
        top.lineToPoint_(NSMakePoint(x + size, y + size))
        top.closePath()
        (ui_color(0.22, 0.95, 0.65, 1.0) if active else ui_color(0.40, 0.40, 0.43, 1.0)).set()
        top.fill()

        face = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(x, y, size, size), 10, 10)
        (ui_color(0.10, 0.80, 0.56, 1.0) if active else ui_color(0.30, 0.30, 0.33, 1.0)).set()
        face.fill()
        ui_color(0.80, 1.0, 0.88, 1.0).set()
        face.setLineWidth_(1.5)
        face.stroke()

        self._draw_text(str(value), NSMakeRect(x + 4, y + 4, size - 8, size - 8), 19, NSColor.whiteColor(), True, True)
        self._draw_text(f"d{sides}", NSMakeRect(x + 4, y + size - 16, size - 8, 12), 8, ui_color(0.85, 1.0, 0.90, 0.78), False, True)

    def drawRect_(self, _rect):
        bounds = self.bounds()
        background = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, 16, 16)
        ui_color(0.035, 0.035, 0.04, 0.96).set()
        background.fill()

        result = self.roll_result
        if result is None:
            return

        rolling = self.frame_index < 14
        title_color = ui_color(0.58, 0.95, 0.28, 1.0)
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
            self._draw_text(f"+ {result.count - dice_to_draw} more dice included in the total", NSMakeRect(24, 80, bounds.size.width - 48, 20), 12, ui_color(0.70, 0.70, 0.74, 1.0), False, True)

        if not rolling:
            dice_sum = sum(result.rolls)
            details = f"Dice: {dice_sum}"
            if result.modifier:
                sign = "+" if result.modifier > 0 else "-"
                details = f"{details} {sign} {abs(result.modifier)}"
            self._draw_text(f"Total: {result.total}", NSMakeRect(24, 32, bounds.size.width - 48, 34), 24, NSColor.whiteColor(), True, True)
            self._draw_text(details, NSMakeRect(24, 16, bounds.size.width - 48, 20), 12, ui_color(0.72, 0.72, 0.76, 1.0), False, True)


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
        self.panel.setBackgroundColor_(ui_color(0.035, 0.035, 0.04, 0.96))
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


def find_spell_in_text(text: str, lookup: dict[str, Spell]) -> Spell | None:
    exact_match = find_exact_spell_in_text(text, lookup)
    if exact_match is not None:
        return exact_match

    return find_fuzzy_spell_in_text(normalize_transcript_for_matching(text), lookup)


def find_exact_spell_in_text(text: str, lookup: dict[str, Spell]) -> Spell | None:
    normalized = f" {normalize_transcript_for_matching(text)} "
    best_match: tuple[int, int, Spell] | None = None
    for alias, spell in lookup.items():
        needle = f" {alias} "
        index = normalized.rfind(needle)
        if index < 0:
            continue
        candidate = (len(alias), index, spell)
        if best_match is None or candidate[:2] > best_match[:2]:
            best_match = candidate
    if best_match:
        return best_match[2]
    return None


def search_spells(query: str, spells: list[Spell], limit: int = 8) -> list[Spell]:
    normalized_query = normalize_transcript_for_matching(query)
    if not normalized_query:
        return spells[:limit]

    ranked: list[tuple[float, int, str, Spell]] = []
    compact_query = normalized_query.replace(" ", "")
    for spell in spells:
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
    return [spell for _score, _length, _name, spell in ranked[:limit]]


def find_fuzzy_spell_in_text(normalized_text: str, lookup: dict[str, Spell]) -> Spell | None:
    words = normalized_text.split()
    if len(words) < 2:
        return None

    best_match: tuple[float, int, Spell, str, str] | None = None
    for alias, spell in lookup.items():
        alias_words = alias.split()
        if len(alias_words) < 2:
            continue

        for size in range(max(1, len(alias_words) - 1), len(alias_words) + 2):
            if size > len(words):
                continue
            for start in range(0, len(words) - size + 1):
                candidate = " ".join(words[start : start + size])
                if alias.startswith(candidate) and len(candidate) < len(alias):
                    continue
                shared_tokens = set(alias_words) & set(candidate.split())
                if not shared_tokens:
                    continue
                score = SequenceMatcher(None, alias, candidate).ratio()
                threshold = 0.88 if len(alias) >= 9 else 0.92
                if score < threshold:
                    continue
                ranked = (score, start, spell, alias, candidate)
                if best_match is None or ranked[:2] > best_match[:2]:
                    best_match = ranked

        compact_alias = alias.replace(" ", "")
        compact_text = normalized_text.replace(" ", "")
        if len(compact_alias) >= 8 and len(words) >= 2 and compact_text:
            compact_score = SequenceMatcher(None, compact_alias, compact_text).ratio()
            if compact_score >= 0.90:
                ranked = (compact_score, len(words), spell, alias, normalized_text)
                if best_match is None or ranked[:2] > best_match[:2]:
                    best_match = ranked

    if best_match:
        score, _start, spell, alias, candidate = best_match
        log(f"Fuzzy match: {spell.name} ({candidate!r} ~= {alias!r}, {score:.2f})")
        return spell
    return None


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
    label.setTextColor_(NSColor.whiteColor())
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
    field.setBackgroundColor_(ui_color(0.075, 0.075, 0.080, 1.0))
    field.setFocusRingType_(1)
    field.setTextColor_(ui_color(0.88, 0.88, 0.90, 1.0))
    field.setFont_(NSFont.systemFontOfSize_(14))
    field.setUsesSingleLineMode_(True)
    field.cell().setScrollable_(True)
    style_layer(field, ui_color(0.075, 0.075, 0.080, 1.0), ui_color(0.25, 0.25, 0.28, 1.0), 8, 1)


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
    field.setBackgroundColor_(ui_color(0.105, 0.105, 0.112, 1.0))
    field.setFocusRingType_(1)
    field.setTextColor_(ui_color(0.90, 0.90, 0.92, 1.0))
    field.setFont_(NSFont.systemFontOfSize_(15))
    field.setUsesSingleLineMode_(True)
    field.cell().setScrollable_(True)
    style_layer(field, ui_color(0.105, 0.105, 0.112, 1.0), ui_color(0.30, 0.30, 0.33, 1.0), 8, 1)


def draw_text(text: str, x: float, y: float, size: float = 13, color=None, bold: bool = False):
    attributes = {
        NSFontAttributeName: NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size),
        NSForegroundColorAttributeName: color or NSColor.whiteColor(),
    }
    NSString.stringWithString_(str(text)).drawAtPoint_withAttributes_(NSMakePoint(x, y), attributes)


def text_attributes(size: float = 13, color=None, bold: bool = False):
    return {
        NSFontAttributeName: NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size),
        NSForegroundColorAttributeName: color or NSColor.whiteColor(),
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
        fill = ui_color(0.155, 0.155, 0.168, 1.0) if highlighted else ui_color(0.105, 0.105, 0.115, 1.0)
        stroke = ui_color(0.33, 0.33, 0.36, 1.0) if highlighted else ui_color(0.22, 0.22, 0.24, 1.0)
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
        primary = ui_color(0.94, 0.94, 0.95, 1.0)
        muted = ui_color(0.66, 0.66, 0.68, 1.0)
        name_attrs = text_attributes(14, primary, True)
        meta_attrs = text_attributes(12.5, muted, True)
        hp_text = self.hp_text.replace("HP ", "HP: ")
        ac_text = self.ac_text.replace("AC ", "AC: ")
        ac_width = text_width(ac_text, meta_attrs)
        hp_width = text_width(hp_text, meta_attrs)
        gap = 8
        x = 14
        y = max(0, (bounds.size.height - 19) / 2 - 1)
        metadata_width = hp_width + ac_width + gap * 2
        name_width = max(54, width - x * 2 - metadata_width)
        fitted_name = fit_text_to_width(self.primary_text, name_width, name_attrs)
        NSString.stringWithString_(fitted_name).drawInRect_withAttributes_(NSMakeRect(x, y, name_width, 20), name_attrs)
        meta_x = x + min(name_width, text_width(fitted_name, name_attrs)) + gap
        NSString.stringWithString_(hp_text).drawInRect_withAttributes_(NSMakeRect(meta_x, y + 1, hp_width, 19), meta_attrs)
        NSString.stringWithString_(ac_text).drawInRect_withAttributes_(NSMakeRect(meta_x + hp_width + gap, y + 1, ac_width, 19), meta_attrs)

    def _drawSpellResult_(self, bounds):
        width = bounds.size.width
        primary = ui_color(0.86, 0.86, 0.88, 1.0)
        muted = ui_color(0.66, 0.66, 0.69, 1.0)
        gold = ui_color(1.0, 0.82, 0.26, 1.0)
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
        fill = ui_color(0.070, 0.070, 0.078, 1.0)
        stroke = ui_color(0.50, 0.50, 0.54, 1.0) if highlighted else ui_color(0.36, 0.36, 0.39, 1.0)
        circle_fill = ui_color(0.090, 0.090, 0.100, 1.0)
        text = ui_color(0.94, 0.94, 0.95, 1.0)
        muted = ui_color(0.68, 0.68, 0.71, 1.0)
        green = ui_color(0.58, 0.95, 0.28, 1.0)

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
        icon_color = ui_color(0.96, 0.96, 0.97, 1.0) if highlighted else ui_color(0.78, 0.78, 0.80, 1.0)
        if highlighted:
            side = min(30, bounds.size.width, bounds.size.height)
            draw_rounded_rect(
                NSMakeRect((bounds.size.width - side) / 2, (bounds.size.height - side) / 2, side, side),
                ui_color(0.14, 0.14, 0.15, 1.0),
                ui_color(0.30, 0.30, 0.32, 1.0),
                side / 2,
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
        fill = ui_color(0.115, 0.115, 0.122, 1.0) if highlighted else ui_color(0.095, 0.095, 0.102, 1.0)
        stroke = ui_color(0.34, 0.34, 0.36, 1.0) if highlighted else ui_color(0.24, 0.24, 0.26, 1.0)
        draw_rounded_rect(
            NSMakeRect(0.5, 0.5, max(1, bounds.size.width - 1), max(1, bounds.size.height - 1)),
            fill,
            stroke,
            7,
            1,
        )
        item = self.selectedItem()
        title = str(item.title()) if item is not None else str(self.title())
        draw_fitted_text(title, NSMakeRect(12, 8, max(20, bounds.size.width - 42), 18), 13, ui_color(0.88, 0.88, 0.90, 1.0), True)
        draw_right_fitted_text("⌄", NSMakeRect(bounds.size.width - 28, 7, 16, 18), 14, ui_color(0.66, 0.66, 0.69, 1.0), True)


MONSTER_RESULT_ROW_HEIGHT = 42
MONSTER_RESULT_ROW_STEP = 50
SPELL_RESULT_ROW_HEIGHT = 42
SPELL_RESULT_ROW_STEP = 50


class CombatTrackerView(NSView):
    combatants: list[dict[str, Any]]
    current_turn_index: int
    name_rects: list[tuple[Any, int]]
    hp_button_rects: list[tuple[Any, int]]
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
        for rect, index in self.hp_button_rects:
            if (
                rect.origin.x <= point.x <= rect.origin.x + rect.size.width
                and rect.origin.y <= point.y <= rect.origin.y + rect.size.height
            ):
                return ("hp", index, None)
        for rect, index in self.name_rects:
            if (
                rect.origin.x <= point.x <= rect.origin.x + rect.size.width
                and rect.origin.y <= point.y <= rect.origin.y + rect.size.height
            ):
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
        if self.target is not None:
            self.target.performSelectorOnMainThread_withObject_waitUntilDone_(
                "closeCombatantHpMenu:",
                None,
                False,
            )
        objc.super(CombatTrackerView, self).mouseDown_(event)

    def drawRect_(self, _rect):
        bounds = self.bounds()
        ui_color(0.015, 0.015, 0.017, 1.0).set()
        NSBezierPath.bezierPathWithRect_(bounds).fill()

        muted = ui_color(0.48, 0.48, 0.50, 1.0)
        card_fill = ui_color(0.075, 0.075, 0.078, 1.0)
        card_border = ui_color(0.17, 0.17, 0.18, 1.0)
        current_border = ui_color(0.55, 0.55, 0.57, 1.0)
        green = ui_color(0.10, 0.78, 0.52, 1.0)
        temp_blue = ui_color(0.20, 0.58, 0.95, 1.0)
        pink = ui_color(1.0, 0.18, 0.39, 1.0)
        red = ui_color(0.55, 0.12, 0.18, 1.0)
        white = NSColor.whiteColor()

        left = 24
        width = bounds.size.width - 48
        right = left + width
        compact = width < 820
        badge_w = 0 if compact else 78
        badge_x = right - badge_w - 18
        ac_w = 44
        ac_x = right - badge_w - 90
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
            return

        self.name_rects = []
        self.hp_button_rects = []
        draw_text("Init", left + 30, 22, 11, muted, True)
        draw_text("Type", left + 86, 22, 11, muted, True)
        draw_text("Name", name_x, 22, 11, muted, True)
        draw_right_fitted_text_centered("HP", NSMakeRect(hp_text_x, 18, hp_text_w, 20), 11, muted, True)
        draw_centered_text_in_rect("AC", NSMakeRect(ac_x, 18, ac_w, 20), 11, muted, True)
        if not compact:
            draw_text("Status", badge_x + 10, 22, 11, muted, True)

        row_y = 54
        row_h = 56
        gap = 12
        for index, combatant in enumerate(self.combatants):
            initiative = int(combatant.get("initiative") or 0)
            rect = NSMakeRect(left, row_y, width, row_h)
            is_current = index == self.current_turn_index
            is_down = self._hp_values(combatant)[0] is not None and self._hp_values(combatant)[0] <= 0
            draw_rounded_rect(
                rect,
                ui_color(0.09, 0.09, 0.095, 0.62 if is_down else 1.0),
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
                    ui_color(0.115, 0.115, 0.122, 1.0),
                    ui_color(0.30, 0.30, 0.33, 1.0),
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
                        ui_color(0.22, 0.22, 0.23, 1.0),
                        4,
                    )
                    hp_text = f"{current_hp}/{max_hp}"
                else:
                    draw_segmented_rounded_bar(bar_rect, [], ui_color(0.22, 0.22, 0.23, 1.0), 4)
                    hp_text = "-"
                draw_right_fitted_text_centered(hp_text, NSMakeRect(hp_text_x, bar_y, hp_text_w, bar_h), 12, muted, False)
            else:
                pass

            draw_centered_text_in_rect(str(combatant.get("ac") or "?"), NSMakeRect(ac_x, row_y + 14, ac_w, 28), 15, white, False)

            if is_down and not compact:
                draw_text("Down", badge_x + 16, row_y + 19, 12, pink, True)

            row_y += row_h + gap


class MainWindowController(NSObject):
    window: NSWindow
    content_view: NSView
    initiative_tab_button: NSButton
    spells_tab_button: NSButton
    dice_tab_button: NSButton
    sidebar_panel: NSView
    sidebar_scroll: NSScrollView
    sidebar_content: NSView
    combat_panel: NSView
    spell_panel: NSView
    dice_panel: NSView
    sidebar_logo_label: NSTextField
    sidebar_footer_label: NSTextField
    creatures: list[Creature]
    spells: list[Spell]
    spell_lookup: dict[str, Spell]
    overlay: Any
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
    monster_search_button: NSButton
    monster_result_buttons: list[NSButton]
    monster_add_buttons: list[NSButton]
    spell_search_field: NSTextField
    spell_roll_label: NSTextField
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

    def initWithBestiary_spells_spellLookup_overlay_(self, creatures, spells, spell_lookup, overlay):
        self = objc.super(MainWindowController, self).init()
        if self is None:
            return None

        self.creatures = list(creatures)
        self.spells = list(spells)
        self.spell_lookup = dict(spell_lookup)
        self.overlay = overlay
        self.parties = self.loadParties()
        self.combatants = []
        self.monster_results = []
        self.monster_result_buttons = []
        self.monster_add_buttons = []
        self.displayed_spells = []
        self.spell_result_buttons = []
        self.dice_preset_buttons = []
        self.dice_pool = {4: 0, 6: 0, 8: 0, 10: 0, 12: 0, 20: 0}
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
        width = 1280
        height = 760
        x = screen.origin.x + (screen.size.width - width) / 2
        y = screen.origin.y + (screen.size.height - height) / 2

        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskResizable
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("Arcane Manager")
        self.window.setMinSize_(NSMakeSize(1060, 660))
        self.window.setDelegate_(self)
        self.window.setBackgroundColor_(ui_color(0.05, 0.05, 0.055, 1.0))

        self.content_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        style_layer(self.content_view, ui_color(0.05, 0.05, 0.055, 1.0), None, 0)
        self.initiative_tab_button = self._make_button("Initiative Tracker", (20, height - 38, 150, 30), "showInitiativeTab:")
        self.spells_tab_button = self._make_button("Spells", (178, height - 38, 86, 30), "showSpellsTab:")
        self.dice_tab_button = self._make_button("Dice Roller", (272, height - 38, 112, 30), "showDiceTab:")
        self.sidebar_panel = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 340, height))
        style_layer(self.sidebar_panel, ui_color(0.075, 0.075, 0.078, 1.0), None, 0)
        self.sidebar_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 340, height))
        self.sidebar_scroll.setHasVerticalScroller_(True)
        self.sidebar_scroll.setAutohidesScrollers_(False)
        self.sidebar_scroll.setDrawsBackground_(False)
        self.sidebar_scroll.setBorderType_(0)
        self.sidebar_content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 340, height))
        self.sidebar_scroll.setDocumentView_(self.sidebar_content)
        self.combat_panel = NSView.alloc().initWithFrame_(NSMakeRect(360, 24, 896, height - 48))
        style_layer(self.combat_panel, ui_color(0.015, 0.015, 0.017, 1.0), ui_color(0.12, 0.12, 0.13, 1.0), 14, 1)
        self.spell_panel = NSView.alloc().initWithFrame_(NSMakeRect(20, 20, width - 40, height - 74))
        style_layer(self.spell_panel, ui_color(0.015, 0.015, 0.017, 1.0), ui_color(0.12, 0.12, 0.13, 1.0), 14, 1)
        self.dice_panel = NSView.alloc().initWithFrame_(NSMakeRect(20, 20, width - 40, height - 74))
        style_layer(self.dice_panel, ui_color(0.015, 0.015, 0.017, 1.0), ui_color(0.12, 0.12, 0.13, 1.0), 14, 1)

        self.monster_sheet_drawer = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 360, height - 48))
        style_layer(self.monster_sheet_drawer, ui_color(0.055, 0.055, 0.062, 1.0), ui_color(0.18, 0.18, 0.19, 1.0), 12, 1)
        self.monster_sheet_drawer.setHidden_(True)
        self.monster_sheet_title = make_label("", (0, 0, 260, 28), 18, True)
        self.monster_sheet_title.setUsesSingleLineMode_(True)
        self.monster_sheet_title.setLineBreakMode_(4)
        self.monster_sheet_close_button = self._make_button("Close", (0, 0, 72, 28), "closeMonsterSheet:")
        self.monster_sheet_hp_label = make_label("Current HP", (0, 0, 90, 24), 13, True)
        self.monster_sheet_hp_field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 72, 26))
        self.monster_sheet_save_button = self._make_button("Save HP", (0, 0, 84, 26), "saveMonsterHp:")
        self.monster_sheet_roll_label = make_label("", (0, 0, 300, 22), 12, True)
        self.monster_sheet_roll_label.setTextColor_(ui_color(0.58, 0.95, 0.28, 1.0))
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
        self.monster_sheet_body.setTextColor_(NSColor.whiteColor())
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
        self.notes_hint.setTextColor_(ui_color(0.72, 0.72, 0.75, 1.0))
        self.sidebar_logo_label = make_label("✦", (0, 0, 36, 36), 20, True)
        self.sidebar_logo_label.setAlignment_(1)
        style_layer(self.sidebar_logo_label, ui_color(0.12, 0.39, 0.74, 1.0), ui_color(0.18, 0.46, 0.84, 1.0), 10, 1)
        self.notes_title.setHidden_(True)
        self.notes_hint.setHidden_(True)
        self.sidebar_logo_label.setHidden_(True)
        self.sidebar_footer_label = make_label("", (0, 0, 300, 24), 13)
        self.sidebar_footer_label.setTextColor_(ui_color(0.72, 0.72, 0.75, 1.0))
        self.sidebar_footer_label.setHidden_(True)
        self.notes_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        self.notes_scroll.setHasVerticalScroller_(True)
        self.notes_scroll.setAutohidesScrollers_(False)
        self.notes_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        self.notes_view.setFont_(NSFont.systemFontOfSize_(14))
        self.notes_view.setTextColor_(NSColor.whiteColor())
        self.notes_view.setBackgroundColor_(ui_color(0.11, 0.11, 0.13, 1.0))
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
        self.party_status_label.setTextColor_(ui_color(0.68, 0.68, 0.70, 1.0))

        for _index in range(6):
            icon_view = NSImageView.alloc().initWithFrame_(NSMakeRect(0, 0, 20, 20))
            icon_view.setHidden_(True)
            self.party_member_icon_views.append(icon_view)
            label = make_label("", (0, 0, 100, 38), 13, True)
            label.setHidden_(True)
            style_layer(label, ui_color(0.12, 0.12, 0.125, 1.0), ui_color(0.23, 0.23, 0.24, 1.0), 8, 1)
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
        self.monster_search_button = self._make_button("Search", (0, 0, 80, 26), "searchMonsters:")
        self.monster_search_button.setHidden_(True)

        for index in range(8):
            button = SearchResultButton.alloc().initWithFrame_(NSMakeRect(0, 0, 100, MONSTER_RESULT_ROW_HEIGHT))
            button.setTag_(index)
            button.setHidden_(True)
            self.monster_result_buttons.append(button)
            add_button = RowAddButton.alloc().initWithFrame_(NSMakeRect(0, 0, 28, MONSTER_RESULT_ROW_HEIGHT))
            add_button.setTarget_(self)
            add_button.setAction_("addMonster:")
            add_button.setTag_(index)
            add_button.setHidden_(True)
            add_button.setToolTip_("Add creature to initiative")
            self.monster_add_buttons.append(add_button)

        self.spell_search_field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 260, 28))
        self.spell_search_field.setPlaceholderString_("Search spells in English or Italian")
        self.spell_search_field.setDelegate_(self)
        style_text_input(self.spell_search_field)
        self.spell_roll_label = make_label("Click a green dice expression to roll.", (0, 0, 320, 24), 12, True)
        self.spell_roll_label.setTextColor_(ui_color(0.58, 0.95, 0.28, 1.0))
        for index in range(18):
            button = SearchResultButton.alloc().initWithFrame_(NSMakeRect(0, 0, 100, SPELL_RESULT_ROW_HEIGHT))
            button.setTarget_(self)
            button.setAction_("selectSpellResult:")
            button.setTag_(index)
            button.setHidden_(True)
            self.spell_result_buttons.append(button)
        self.spell_detail_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        self.spell_detail_scroll.setHasVerticalScroller_(True)
        self.spell_detail_scroll.setAutohidesScrollers_(False)
        self.spell_detail_scroll.setDrawsBackground_(False)
        self.spell_detail_scroll.setBorderType_(0)
        self.spell_detail_view = DiceTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        self.spell_detail_view.setFont_(NSFont.systemFontOfSize_(13))
        self.spell_detail_view.setTextColor_(NSColor.whiteColor())
        self.spell_detail_view.setRollTarget_(self)
        self.spell_detail_scroll.setDocumentView_(self.spell_detail_view)

        self.dice_title_label = make_label("Dice Roller", (0, 0, 240, 32), 24, True)
        self.dice_hint_label = make_label("", (0, 0, 720, 24), 13)
        self.dice_hint_label.setTextColor_(ui_color(0.72, 0.72, 0.75, 1.0))
        self.dice_hint_label.setHidden_(True)
        self.dice_control_labels = []
        self.dice_clear_button = self._make_button("Clear", (0, 0, 100, 34), "clearDicePool:")
        self.dice_roll_button = self._make_button("Roll Dice", (0, 0, 130, 34), "rollCustomDice:")
        self.dice_formula_label = make_label("Click a die", (0, 0, 520, 42), 30, True)
        self.dice_formula_label.setAlignment_(1)
        self.dice_formula_label.setTextColor_(ui_color(0.58, 0.95, 0.28, 1.0))
        self.dice_result_label = make_label("", (0, 0, 520, 24), 13, True)
        self.dice_result_label.setAlignment_(1)
        self.dice_result_label.setTextColor_(ui_color(0.72, 0.72, 0.75, 1.0))
        self.dice_history_title_label = make_label("Recent Rolls", (0, 0, 220, 24), 16, True)
        self.dice_history_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 320, 260))
        self.dice_history_scroll.setHasVerticalScroller_(True)
        self.dice_history_scroll.setAutohidesScrollers_(False)
        self.dice_history_scroll.setDrawsBackground_(False)
        self.dice_history_scroll.setBorderType_(0)
        style_layer(self.dice_history_scroll, ui_color(0.070, 0.070, 0.078, 1.0), ui_color(0.18, 0.18, 0.19, 1.0), 8, 1)
        self.dice_history_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 300, 260))
        self.dice_history_view.setEditable_(False)
        self.dice_history_view.setSelectable_(True)
        self.dice_history_view.setFont_(NSFont.systemFontOfSize_(12))
        self.dice_history_view.setTextColor_(ui_color(0.78, 0.78, 0.80, 1.0))
        self.dice_history_view.setBackgroundColor_(ui_color(0.070, 0.070, 0.078, 1.0))
        self.dice_history_view.setTextContainerInset_(NSMakeSize(10, 10))
        self.dice_history_scroll.setDocumentView_(self.dice_history_view)
        self.refreshDiceHistory()
        self.dice_presets = (4, 6, 8, 10, 12, 20)
        for sides in self.dice_presets:
            button = self._make_button(f"d{sides}", (0, 0, 76, 58), "addDieToPool:")
            button.setTag_(sides)
            self.dice_preset_buttons.append(button)

        self.previous_turn_button = self._make_button("Previous", (0, 0, 110, 34), "previousTurn:")
        self.next_turn_button = self._make_button("Next", (0, 0, 100, 34), "nextTurn:")
        self.clear_tracker_button = self._make_button("Finish Combat", (0, 0, 130, 34), "clearTracker:")
        self.turn_label = make_label("", (0, 0, 300, 24), 13, True)
        self.turn_label.setTextColor_(ui_color(1.0, 0.82, 0.26, 1.0))
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
        self.content_view.addSubview_(self.initiative_tab_button)
        self.content_view.addSubview_(self.spells_tab_button)
        self.content_view.addSubview_(self.dice_tab_button)
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
            self.monster_search_button,
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
        for button in self.monster_result_buttons:
            self.sidebar_content.addSubview_(button)
        for button in self.monster_add_buttons:
            self.sidebar_content.addSubview_(button)
        for view in (
            self.tracker_title,
            self.previous_turn_button,
            self.next_turn_button,
            self.clear_tracker_button,
            self.turn_label,
            self.tracker_scroll,
        ):
            self.content_view.addSubview_(view)
        for view in (self.spell_search_field, self.spell_roll_label, self.spell_detail_scroll):
            self.content_view.addSubview_(view)
        for button in self.spell_result_buttons:
            self.content_view.addSubview_(button)
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
            self.spell_roll_label,
            self.spell_detail_scroll,
            *self.spell_result_buttons,
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

        self.window.setContentView_(self.content_view)
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
        style_layer(button, ui_color(0.13, 0.13, 0.14, 1.0), ui_color(0.24, 0.24, 0.25, 1.0), 8, 1)
        return button

    def layoutMainWindow(self):
        bounds = self.content_view.bounds()
        width = int(bounds.size.width)
        height = int(bounds.size.height)
        tab_y = height - 38
        self.initiative_tab_button.setFrame_(NSMakeRect(20, tab_y, 150, 30))
        self.spells_tab_button.setFrame_(NSMakeRect(178, tab_y, 86, 30))
        self.dice_tab_button.setFrame_(NSMakeRect(272, tab_y, 112, 30))
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
            430 + visible_party_rows * 42 + len(self.monster_result_buttons) * MONSTER_RESULT_ROW_STEP,
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
            self.monster_sheet_title.setFrame_(NSMakeRect(drawer_margin, drawer_top, max(120, drawer_inner_width - 88), 28))
            self.monster_sheet_close_button.setFrame_(NSMakeRect(drawer_width - drawer_margin - 72, drawer_top, 72, 28))
            ability_y = panel_height - 132
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
        self.monster_search_field.setFrame_(NSMakeRect(sidebar_margin, y - 3, card_width, 34))
        self.monster_search_button.setFrame_(NSMakeRect(sidebar_margin + card_width - 76, y, 76, 28))
        y -= 52
        monster_add_w = 22
        monster_result_gap = 10
        monster_result_w = max(180, card_width - monster_add_w - monster_result_gap)
        for index, button in enumerate(self.monster_result_buttons):
            row_y = y - index * MONSTER_RESULT_ROW_STEP
            button.setFrame_(NSMakeRect(sidebar_margin, row_y, monster_result_w, MONSTER_RESULT_ROW_HEIGHT))
            if index < len(self.monster_add_buttons):
                self.monster_add_buttons[index].setFrame_(
                    NSMakeRect(sidebar_margin + monster_result_w + monster_result_gap, row_y, monster_add_w, MONSTER_RESULT_ROW_HEIGHT)
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
        results_top = spell_y + spell_height - 92
        for index, button in enumerate(self.spell_result_buttons):
            button.setFrame_(NSMakeRect(spell_x, results_top - index * SPELL_RESULT_ROW_STEP, list_width, SPELL_RESULT_ROW_HEIGHT))
        detail_x = spell_x + list_width + 28
        detail_width = max(300, spell_width - list_width - 28)
        self.spell_roll_label.setFrame_(NSMakeRect(detail_x, spell_y + spell_height - 26, detail_width, 22))
        self.spell_detail_scroll.setFrame_(NSMakeRect(detail_x, spell_y, detail_width, spell_height - 38))
        self.spell_detail_view.setFrame_(NSMakeRect(0, 0, detail_width - 24, max(spell_height - 38, self.spell_detail_view.frame().size.height)))

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

    def applyCurrentTab(self):
        show_initiative = self.current_tab == "initiative"
        show_spells = self.current_tab == "spells"
        show_dice = self.current_tab == "dice"
        for view in self.initiative_views:
            view.setHidden_(not show_initiative)
        self.monster_search_button.setHidden_(True)
        for view in self.spell_views:
            view.setHidden_(not show_spells)
        for view in self.dice_views:
            view.setHidden_(not show_dice)
        style_layer(
            self.initiative_tab_button,
            ui_color(0.20, 0.20, 0.22, 1.0) if show_initiative else ui_color(0.10, 0.10, 0.11, 1.0),
            ui_color(0.30, 0.30, 0.32, 1.0),
            8,
            1,
        )
        style_layer(
            self.spells_tab_button,
            ui_color(0.20, 0.20, 0.22, 1.0) if show_spells else ui_color(0.10, 0.10, 0.11, 1.0),
            ui_color(0.30, 0.30, 0.32, 1.0),
            8,
            1,
        )
        style_layer(
            self.dice_tab_button,
            ui_color(0.20, 0.20, 0.22, 1.0) if show_dice else ui_color(0.10, 0.10, 0.11, 1.0),
            ui_color(0.30, 0.30, 0.32, 1.0),
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
        self.party_editor_panel.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.08, 0.10, 0.97))

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
        self.editor_character_list.setTextColor_(NSColor.whiteColor())
        self.editor_character_list.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.12, 0.12, 0.15, 1.0))
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
                }
            )
        self.sortCombatants()
        self.current_turn_index = 0
        self.round_number = 1
        self.refreshTracker()

    def searchMonsters_(self, _sender):
        query = str(self.monster_search_field.stringValue()).strip()
        self.monster_results = search_creatures(query, self.creatures, len(self.monster_result_buttons))
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

    def refreshSpellResults(self):
        query = str(self.spell_search_field.stringValue()).strip()
        self.displayed_spells = search_spells(query, self.spells, len(self.spell_result_buttons))
        for index, button in enumerate(self.spell_result_buttons):
            if index >= len(self.displayed_spells):
                button.setHidden_(True)
                continue
            spell = self.displayed_spells[index]
            button.configureSpellResult_(spell)
            button.setHidden_(False)
        if self.displayed_spells:
            self.showSpellInDetail_(self.displayed_spells[0])
        else:
            self.spell_detail_view.setString_("No matching spells.")
            self.spell_detail_view.setDiceRanges_([])
            self.spell_roll_label.setStringValue_("")

    def selectSpellResult_(self, sender):
        index = int(sender.tag())
        if index < 0 or index >= len(self.displayed_spells):
            return
        self.showSpellInDetail_(self.displayed_spells[index])

    def showSpellInDetail_(self, spell):
        self.spell_roll_label.setStringValue_("Click a green dice expression to roll.")
        title, meta, body = format_spell_for_overlay(spell)
        italian = f"\n({spell.italian_name})" if spell.italian_name else ""
        details = [
            f"{title}{italian}",
            "",
            meta,
            "",
            body,
            "",
            f"Components: {component_badge_text(spell.components) or '-'}",
            f"Range: {spell.range or '-'}",
            f"Duration: {spell.duration or '-'}",
        ]
        if spell.spell_lists:
            details.append(f"Classes: {', '.join(spell.spell_lists)}")
        detail_body = "\n".join(details)
        attributed = attributed_spell_body(detail_body)
        self.spell_detail_view.textStorage().setAttributedString_(attributed)
        self.spell_detail_view.setDiceRanges_(dice_ranges_for_body(detail_body))
        self.spell_detail_view.layoutManager().ensureLayoutForTextContainer_(self.spell_detail_view.textContainer())
        height = max(
            self.spell_detail_scroll.frame().size.height,
            self.spell_detail_view.layoutManager().usedRectForTextContainer_(self.spell_detail_view.textContainer()).size.height + 24,
        )
        self.spell_detail_view.setFrame_(NSMakeRect(0, 0, self.spell_detail_scroll.frame().size.width - 24, height))

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
            lines.append(f"{prefix}{desc}{suffix}".strip())

    def _append_spells(self, lines: list[str], spells_payload: Any):
        if not isinstance(spells_payload, list) or not spells_payload:
            return
        lines.extend(["", "Spells:"])
        for item in spells_payload:
            if isinstance(item, str):
                text = clean_text(item, MAX_TEXT_FIELD_CHARS)
                if text:
                    lines.append(text)
            elif isinstance(item, dict):
                for key, value in item.items():
                    heading = clean_text(key, MAX_SHORT_FIELD_CHARS)
                    spell_text = clean_text(value, MAX_TEXT_FIELD_CHARS)
                    if heading or spell_text:
                        lines.append(f"{heading}: {spell_text}".strip(": "))

    def _monster_body_for_creature(self, creature: Creature) -> str:
        raw = creature.raw
        hit_dice = clean_text(raw.get("hit_dice", ""), MAX_SHORT_FIELD_CHARS)
        hit_points = f"Hit Points: {creature.hp}"
        if hit_dice:
            hit_points = f"{hit_points} ({hit_dice})"
        lines = [
            f"{creature.size} {creature.creature_type}, {creature.alignment}".strip(" ,"),
            f"Source: {creature.source or clean_text(raw.get('source', ''), MAX_SHORT_FIELD_CHARS)}",
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
        panel.setBackgroundColor_(ui_color(0.075, 0.075, 0.080, 0.98))

        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        style_layer(content, ui_color(0.075, 0.075, 0.080, 1.0), ui_color(0.22, 0.22, 0.24, 1.0), 12, 1)
        amount_label = make_label("Amount", (18, 104, 80, 20), 12, True)
        amount_label.setTextColor_(ui_color(0.68, 0.68, 0.70, 1.0))
        self.hp_adjust_amount_field = NSTextField.alloc().initWithFrame_(NSMakeRect(18, 72, 56, 28))
        self.hp_adjust_amount_field.setStringValue_("1")
        style_number_input(self.hp_adjust_amount_field)

        heal_button = self._make_button("Heal", (92, 72, 72, 30), "applyHpMenuAction:")
        heal_button.setTag_(1)
        damage_button = self._make_button("Damage", (178, 72, 100, 30), "applyHpMenuAction:")
        damage_button.setTag_(-1)

        temp_label = make_label("Temp", (18, 44, 80, 20), 12, True)
        temp_label.setTextColor_(ui_color(0.68, 0.68, 0.70, 1.0))
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
        if self.spell_roll_label is not None and not self.spell_roll_label.isHidden():
            self.spell_roll_label.setStringValue_(result)

    def openSpell_(self, spell):
        if spell is None:
            return
        self.current_tab = "spells"
        self.spell_search_field.setStringValue_(spell.name)
        self.applyCurrentTab()
        self.refreshSpellResults()
        if spell not in self.displayed_spells:
            self.displayed_spells = [spell, *self.displayed_spells[: max(0, len(self.spell_result_buttons) - 1)]]
            for index, button in enumerate(self.spell_result_buttons):
                if index >= len(self.displayed_spells):
                    button.setHidden_(True)
                    continue
                button.configureSpellResult_(self.displayed_spells[index])
                button.setHidden_(False)
        self.showSpellInDetail_(spell)
        self.window.makeKeyAndOrderFront_(None)

    def windowWillClose_(self, _notification):
        if self in DICE_HISTORY_LISTENERS:
            DICE_HISTORY_LISTENERS.remove(self)
        NSApp.terminate_(None)


class OverlayController(NSObject):
    panel: NSPanel
    title_label: NSTextField
    italian_name_label: NSTextField
    meta_label: NSTextField
    progress_bar: NSProgressIndicator
    progress_label: NSTextField
    progress_body_label: NSTextField
    dice_result_label: NSTextField
    scroll_view: NSScrollView
    scroll_content: FlippedView
    body_label: DiceTextView
    components_label: NSTextField
    component_material_label: NSTextField
    range_label: NSTextField
    duration_label: NSTextField
    classes_label: NSTextField
    v_box: CheckboxSquareView
    s_box: CheckboxSquareView
    m_box: CheckboxSquareView
    detail_views: list[Any]
    tracking_area: Any
    timer: NSTimer | None
    hide_after: float
    mouse_inside: bool
    keep_visible: bool

    def initWithHideAfter_(self, hide_after: float):
        self = objc.super(OverlayController, self).init()
        if self is None:
            return None

        self.hide_after = hide_after
        self.timer = None
        self.mouse_inside = False
        self.keep_visible = True

        screen = NSScreen.mainScreen().visibleFrame()
        width = 640
        height = 520
        x = screen.origin.x + screen.size.width - width - 28
        y = screen.origin.y + screen.size.height - height - 28

        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskUtilityWindow
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setTitle_("Arcane Manager")
        self.panel.setFloatingPanel_(True)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setBecomesKeyOnlyIfNeeded_(True)
        self.panel.setLevel_(24)
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        self.panel.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.08, 0.10, 0.94))
        self.panel.setDelegate_(self)

        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        self.tracking_area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            NSMakeRect(0, 0, width, height),
            NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways | NSTrackingInVisibleRect,
            self,
            None,
        )
        content.addTrackingArea_(self.tracking_area)

        self.title_label = make_label("Listening...", (24, 460, 592, 36), 24, True)
        self.italian_name_label = make_label("", (24, 438, 592, 20), 12)
        self.italian_name_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.78, 0.78, 0.82, 1.0))
        self.meta_label = make_multiline(make_label("Say the name of a configured spell.", (24, 392, 592, 42), 13))
        self.meta_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.82, 0.26, 1.0))

        self.progress_bar = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(24, 330, 592, 16))
        self.progress_bar.setIndeterminate_(False)
        self.progress_bar.setMinValue_(0.0)
        self.progress_bar.setMaxValue_(100.0)
        self.progress_bar.setDoubleValue_(0.0)
        self.progress_bar.setHidden_(True)
        self.progress_label = make_label("", (24, 302, 592, 20), 11)
        self.progress_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.78, 0.78, 0.82, 1.0))
        self.progress_label.setHidden_(True)
        self.progress_body_label = make_multiline(make_label("", (24, 256, 592, 40), 13))
        self.progress_body_label.setHidden_(True)

        self.dice_result_label = make_label("", (24, 364, 592, 20), 12, True)
        self.dice_result_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.58, 0.95, 0.28, 1.0))
        self.dice_result_label.setHidden_(True)

        self.scroll_view = NSScrollView.alloc().initWithFrame_(NSMakeRect(24, 24, 592, 332))
        self.scroll_view.setHasVerticalScroller_(True)
        self.scroll_view.setAutohidesScrollers_(False)
        self.scroll_view.setDrawsBackground_(False)
        self.scroll_view.setBorderType_(0)
        self.scroll_content = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, 592, 332))
        self.scroll_view.setDocumentView_(self.scroll_content)

        self.body_label = DiceTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 560, 278))
        self.body_label.setFont_(NSFont.systemFontOfSize_(14))
        self.body_label.setTextColor_(NSColor.whiteColor())
        self.body_label.setRollTarget_(self)

        self.components_label = make_label("Components:", (0, 0, 100, 24), 14)
        self.v_label = make_label("V", (112, 0, 18, 24), 14)
        self.v_box = CheckboxSquareView.alloc().initWithFrame_(NSMakeRect(134, 4, 16, 16))
        self.s_label = make_label("S", (166, 0, 18, 24), 14)
        self.s_box = CheckboxSquareView.alloc().initWithFrame_(NSMakeRect(188, 4, 16, 16))
        self.m_label = make_label("M", (220, 0, 22, 24), 14)
        self.m_box = CheckboxSquareView.alloc().initWithFrame_(NSMakeRect(246, 4, 16, 16))
        self.component_material_label = make_multiline(make_label("", (276, 0, 284, 24), 14))
        self.range_label = make_multiline(make_label("", (0, 0, 560, 24), 14))
        self.duration_label = make_multiline(make_label("", (0, 0, 560, 24), 14))
        self.classes_label = make_multiline(make_label("", (0, 0, 560, 24), 14))
        self.detail_views = [
            self.components_label,
            self.v_box,
            self.v_label,
            self.s_box,
            self.s_label,
            self.m_box,
            self.m_label,
            self.component_material_label,
            self.range_label,
            self.duration_label,
            self.classes_label,
        ]
        self._set_detail_controls_hidden(True)

        content.addSubview_(self.title_label)
        content.addSubview_(self.italian_name_label)
        content.addSubview_(self.meta_label)
        content.addSubview_(self.progress_bar)
        content.addSubview_(self.progress_label)
        content.addSubview_(self.progress_body_label)
        content.addSubview_(self.dice_result_label)
        content.addSubview_(self.scroll_view)
        self.scroll_content.addSubview_(self.body_label)
        for view in self.detail_views:
            self.scroll_content.addSubview_(view)
        self.panel.setContentView_(content)
        self.panel.orderOut_(None)
        return self

    def _cancel_hide_timer(self):
        if self.timer is not None:
            self.timer.invalidate()
            self.timer = None

    def _schedule_hide_timer(self):
        self._cancel_hide_timer()
        if self.hide_after > 0 and not self.mouse_inside:
            self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                self.hide_after,
                self,
                "hide:",
                None,
                False,
            )

    def mouseEntered_(self, _event):
        self.mouse_inside = True
        self._cancel_hide_timer()

    def mouseExited_(self, _event):
        self.mouse_inside = False
        self._cancel_hide_timer()
        if not self.keep_visible:
            self.hide_(None)

    def _set_detail_controls_hidden(self, hidden: bool):
        for view in self.detail_views:
            view.setHidden_(hidden)

    def _layout_spell_details(self, attributed_body):
        body_width = 560
        scroll_height = 332
        gap = 14
        rect = attributed_body.boundingRectWithSize_options_(
            NSMakeSize(body_width, 10000),
            NSStringDrawingUsesLineFragmentOrigin | NSStringDrawingUsesFontLeading,
        )
        body_height = max(64, int(rect.size.height) + 10)
        components_y = body_height + gap
        range_y = components_y + 30
        duration_y = range_y + 28
        classes_y = duration_y + 28
        document_height = max(scroll_height, classes_y + 34)

        self.scroll_content.setFrame_(NSMakeRect(0, 0, 592, document_height))
        self.body_label.setFrame_(NSMakeRect(0, 0, body_width, body_height))
        self.components_label.setFrame_(NSMakeRect(0, components_y, 100, 24))
        self.v_label.setFrame_(NSMakeRect(112, components_y, 18, 24))
        self.v_box.setFrame_(NSMakeRect(134, components_y + 4, 16, 16))
        self.s_label.setFrame_(NSMakeRect(166, components_y, 18, 24))
        self.s_box.setFrame_(NSMakeRect(188, components_y + 4, 16, 16))
        self.m_label.setFrame_(NSMakeRect(220, components_y, 22, 24))
        self.m_box.setFrame_(NSMakeRect(246, components_y + 4, 16, 16))
        self.component_material_label.setFrame_(NSMakeRect(276, components_y, 284, 24))
        self.range_label.setFrame_(NSMakeRect(0, range_y, body_width, 24))
        self.duration_label.setFrame_(NSMakeRect(0, duration_y, body_width, 24))
        self.classes_label.setFrame_(NSMakeRect(0, classes_y, body_width, 24))
        self.scroll_view.contentView().scrollToPoint_(NSMakePoint(0, 0))
        self.scroll_view.reflectScrolledClipView_(self.scroll_view.contentView())

    def showMessage_meta_body_(self, title: str, meta: str, body: str):
        self.keep_visible = True
        self._cancel_hide_timer()
        self.title_label.setStringValue_(title)
        self.italian_name_label.setStringValue_("")
        self.dice_result_label.setStringValue_("")
        self.dice_result_label.setHidden_(True)
        self.progress_bar.setHidden_(True)
        self.progress_label.setHidden_(True)
        self.progress_body_label.setHidden_(True)
        self.meta_label.setStringValue_(meta)
        self.scroll_view.setHidden_(False)
        self.body_label.setString_(body)
        self.body_label.setDiceRanges_([])
        self.scroll_content.setFrame_(NSMakeRect(0, 0, 592, 332))
        self.body_label.setFrame_(NSMakeRect(0, 0, 560, 332))
        self._set_detail_controls_hidden(True)
        self.panel.orderFrontRegardless()

    def showStatus_(self, payload: dict[str, str]):
        self.showMessage_meta_body_(
            payload.get("title", ""),
            payload.get("meta", ""),
            payload.get("body", ""),
        )

    def showProgress_(self, payload: dict[str, Any]):
        self.keep_visible = True
        self._cancel_hide_timer()
        percent = float(payload.get("percent", 0.0))
        self.title_label.setStringValue_(str(payload.get("title", "")))
        self.italian_name_label.setStringValue_("")
        self.meta_label.setStringValue_(str(payload.get("meta", "")))
        self.dice_result_label.setStringValue_("")
        self.dice_result_label.setHidden_(True)
        self.progress_bar.setHidden_(False)
        self.progress_bar.setDoubleValue_(max(0.0, min(100.0, percent)))
        self.progress_label.setHidden_(False)
        self.progress_label.setStringValue_(str(payload.get("detail", "")))
        self.progress_body_label.setHidden_(False)
        self.progress_body_label.setStringValue_(str(payload.get("body", "")))
        self.scroll_view.setHidden_(True)
        self.body_label.setString_("")
        self.body_label.setDiceRanges_([])
        self.scroll_content.setFrame_(NSMakeRect(0, 0, 592, 280))
        self.body_label.setFrame_(NSMakeRect(0, 0, 560, 280))
        self._set_detail_controls_hidden(True)
        self.panel.orderFrontRegardless()

    def showSpell_(self, spell: Spell):
        self.keep_visible = False
        title, meta, body = format_spell_for_overlay(spell)
        flags = component_flags(spell.components)
        attributed_body = attributed_spell_body(body)
        dice_ranges = dice_ranges_for_body(body)

        self.title_label.setStringValue_(title)
        self.dice_result_label.setStringValue_("")
        self.dice_result_label.setHidden_(True)
        self.progress_bar.setHidden_(True)
        self.progress_label.setHidden_(True)
        self.progress_body_label.setHidden_(True)
        self.scroll_view.setHidden_(False)
        italian_name = spell.italian_name.strip()
        if italian_name and normalize(italian_name) != normalize(spell.name):
            self.italian_name_label.setStringValue_(f"({italian_name})")
        else:
            self.italian_name_label.setStringValue_("")
        self.meta_label.setStringValue_(meta)
        self.body_label.textStorage().setAttributedString_(attributed_body)
        self.body_label.setDiceRanges_(dice_ranges)
        self._layout_spell_details(attributed_body)
        self.v_box.setChecked_(flags["V"])
        self.s_box.setChecked_(flags["S"])
        self.m_box.setChecked_(flags["M"])
        self.component_material_label.setStringValue_(component_material(spell.components))
        self.range_label.setStringValue_(f"Range: {spell.range}" if spell.range.strip() else "")
        self.duration_label.setStringValue_(f"Duration: {spell.duration}" if spell.duration.strip() else "")
        classes = ", ".join(spell.spell_lists)
        self.classes_label.setStringValue_(f"Classes: {classes}" if classes else "")
        self._set_detail_controls_hidden(False)
        self.panel.orderFrontRegardless()
        self._schedule_hide_timer()

    def rollDice_(self, expression: str):
        expression = str(expression).strip()
        if not (DICE_PATTERN.fullmatch(expression) or DICE_FORMULA_PATTERN.fullmatch(expression)):
            self.displayDiceRollResult_(f"Invalid dice expression: {expression}")
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
        self.dice_result_label.setStringValue_(result)
        self.dice_result_label.setHidden_(False)
        self.panel.orderFrontRegardless()

    def hide_(self, _timer):
        self.timer = None
        if self.keep_visible:
            return
        if self.mouse_inside:
            return
        self.panel.orderOut_(None)

    def windowWillClose_(self, _notification):
        NSApp.terminate_(None)


class SpellSearchController(NSObject):
    panel: NSPanel
    search_field: NSTextField
    hint_label: NSTextField
    result_buttons: list[NSButton]
    displayed_spells: list[Spell]
    spells: list[Spell]
    overlay: OverlayController

    def initWithSpells_overlay_(self, spells, overlay):
        self = objc.super(SpellSearchController, self).init()
        if self is None:
            return None

        self.spells = list(spells)
        self.overlay = overlay
        self.displayed_spells = []
        self.result_buttons = []

        screen = NSScreen.mainScreen().visibleFrame()
        width = 520
        height = 370
        x = screen.origin.x + (screen.size.width - width) / 2
        y = screen.origin.y + (screen.size.height - height) / 2

        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskUtilityWindow
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setTitle_("Search Spell")
        self.panel.setFloatingPanel_(True)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setLevel_(24)
        self.panel.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.08, 0.10, 0.97))

        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        title_label = make_label("Search spell", (24, 316, 472, 30), 20, True)
        self.search_field = NSTextField.alloc().initWithFrame_(NSMakeRect(24, 276, 472, 30))
        self.search_field.setFont_(NSFont.systemFontOfSize_(15))
        self.search_field.setTarget_(self)
        self.search_field.setAction_("submitSearch:")
        self.search_field.setDelegate_(self)

        self.hint_label = make_label("Type an English or Italian spell name, then press Enter.", (24, 246, 472, 20), 11)
        self.hint_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.78, 0.78, 0.82, 1.0))

        content.addSubview_(title_label)
        content.addSubview_(self.search_field)
        content.addSubview_(self.hint_label)

        for index in range(8):
            button = NSButton.alloc().initWithFrame_(NSMakeRect(24, 212 - index * 27, 472, 24))
            button.setBordered_(False)
            button.setAlignment_(0)
            button.setFont_(NSFont.systemFontOfSize_(13))
            button.setTarget_(self)
            button.setAction_("selectResult:")
            button.setTag_(index)
            button.setHidden_(True)
            self.result_buttons.append(button)
            content.addSubview_(button)

        self.panel.setContentView_(content)
        self.updateResultsForQuery_("")
        return self

    def show_(self, _sender):
        self.search_field.setStringValue_("")
        self.updateResultsForQuery_("")
        NSApp.activateIgnoringOtherApps_(True)
        self.panel.makeKeyAndOrderFront_(None)
        self.panel.makeFirstResponder_(self.search_field)

    def showWithQuery_(self, payload: dict[str, str]):
        query = str(payload.get("query", ""))
        heard = str(payload.get("heard", query))
        self.search_field.setStringValue_(query)
        self.updateResultsForQuery_(query)
        if self.displayed_spells:
            self.hint_label.setStringValue_(f'I heard "{heard}". Choose the intended spell.')
        else:
            self.hint_label.setStringValue_(f'I heard "{heard}", but found no likely spell.')
        NSApp.activateIgnoringOtherApps_(True)
        self.panel.makeKeyAndOrderFront_(None)
        self.panel.makeFirstResponder_(self.search_field)

    def controlTextDidChange_(self, notification):
        field = notification.object()
        self.updateResultsForQuery_(str(field.stringValue()))

    def updateResultsForQuery_(self, query: str):
        self.displayed_spells = search_spells(query, self.spells, len(self.result_buttons))
        for index, button in enumerate(self.result_buttons):
            if index >= len(self.displayed_spells):
                button.setHidden_(True)
                continue

            spell = self.displayed_spells[index]
            secondary = spell.italian_name.strip()
            title = spell.name
            if secondary and normalize(secondary) != normalize(spell.name):
                title = f"{spell.name} ({secondary})"
            button.setTitle_(title)
            button.setHidden_(False)

        if self.displayed_spells:
            self.hint_label.setStringValue_("Press Enter to open the first result, or click a spell below.")
        else:
            self.hint_label.setStringValue_("No matching spells found.")

    def submitSearch_(self, _sender):
        if self.displayed_spells:
            self.openSpell_(self.displayed_spells[0])

    def selectResult_(self, sender):
        index = int(sender.tag())
        if 0 <= index < len(self.displayed_spells):
            self.openSpell_(self.displayed_spells[index])

    def openSpell_(self, spell: Spell):
        self.panel.orderOut_(None)
        self.overlay.showSpell_(spell)


class PreferencesController(NSObject):
    panel: NSPanel
    app_delegate: Any
    shortcut_label: NSTextField
    hint_label: NSTextField
    record_button: NSButton
    reset_button: NSButton
    recording: bool

    def initWithAppDelegate_(self, app_delegate):
        self = objc.super(PreferencesController, self).init()
        if self is None:
            return None

        self.app_delegate = app_delegate
        self.recording = False

        screen = NSScreen.mainScreen().visibleFrame()
        width = 420
        height = 268
        x = screen.origin.x + (screen.size.width - width) / 2
        y = screen.origin.y + (screen.size.height - height) / 2

        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskUtilityWindow
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setTitle_("Arcane Manager Preferences")
        self.panel.setFloatingPanel_(True)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setLevel_(24)
        self.panel.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.08, 0.10, 0.97))

        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        title_label = make_label("Preferences", (24, 212, 372, 28), 18, True)
        search_label = make_label("Search hotkey", (24, 172, 120, 24), 13, True)
        self.shortcut_label = make_label("", (154, 172, 242, 24), 13)
        self.shortcut_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.82, 0.26, 1.0))

        self.hint_label = make_multiline(make_label("", (24, 102, 372, 44), 11))
        self.hint_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.78, 0.78, 0.82, 1.0))

        self.record_button = NSButton.alloc().initWithFrame_(NSMakeRect(24, 28, 170, 30))
        self.record_button.setTitle_("Record Shortcut")
        self.record_button.setTarget_(self)
        self.record_button.setAction_("beginRecording:")

        self.reset_button = NSButton.alloc().initWithFrame_(NSMakeRect(206, 28, 110, 30))
        self.reset_button.setTitle_("Reset")
        self.reset_button.setTarget_(self)
        self.reset_button.setAction_("resetShortcut:")

        close_button = NSButton.alloc().initWithFrame_(NSMakeRect(326, 28, 70, 30))
        close_button.setTitle_("Close")
        close_button.setTarget_(self)
        close_button.setAction_("close:")

        for view in (
            title_label,
            search_label,
            self.shortcut_label,
            self.hint_label,
            self.record_button,
            self.reset_button,
            close_button,
        ):
            content.addSubview_(view)

        self.panel.setContentView_(content)
        self.updateDisplay()
        return self

    def show_(self, _sender):
        self.recording = False
        self.updateDisplay()
        NSApp.activateIgnoringOtherApps_(True)
        self.panel.makeKeyAndOrderFront_(None)

    def beginRecording_(self, _sender):
        self.recording = True
        self.record_button.setTitle_("Recording...")
        self.hint_label.setStringValue_("Press the new shortcut. Use Cmd, Option, or Ctrl plus a key.")

    def resetShortcut_(self, _sender):
        self.recording = False
        self.app_delegate.setSearchHotkey_(default_search_hotkey())
        self.updateDisplay()

    def close_(self, _sender):
        self.recording = False
        self.panel.orderOut_(None)

    def updateDisplay(self):
        hotkey = self.app_delegate.search_hotkey
        self.shortcut_label.setStringValue_(hotkey_display(hotkey))
        self.record_button.setTitle_("Record Shortcut")
        self.hint_label.setStringValue_("Default shortcut: Cmd+Shift+Space.")

    def captureHotkeyEvent_(self, event) -> bool:
        if not self.recording or not self.panel.isVisible():
            return False

        key = normalized_hotkey_key(event.charactersIgnoringModifiers() or "")
        if key == "\x1b":
            self.recording = False
            self.updateDisplay()
            return True

        modifiers = int(event.modifierFlags()) & SUPPORTED_HOTKEY_MODIFIERS
        hotkey = Hotkey(modifiers, key, int(event.keyCode()))
        if not valid_hotkey(hotkey):
            self.hint_label.setStringValue_("Shortcut not saved. Use Cmd, Option, or Ctrl plus a key.")
            return True

        self.recording = False
        self.app_delegate.setSearchHotkey_(hotkey)
        self.updateDisplay()
        return True


def carbon_hotkey_event_callback(_next_handler, _event, _user_data):
    delegate = GLOBAL_HOTKEY_DELEGATE
    if delegate is not None:
        delegate.performSelectorOnMainThread_withObject_waitUntilDone_("showSearch:", None, False)
    return 0


CARBON_HOTKEY_CALLBACK = CARBON_EVENT_HANDLER_TYPE(carbon_hotkey_event_callback)


class AppDelegate(NSObject):
    overlay: OverlayController
    spells: list[Spell]
    creatures: list[Creature]
    spell_lookup: dict[str, Spell]
    status_item: Any
    main_controller: MainWindowController
    search_menu_item: NSMenuItem
    status_search_item: NSMenuItem
    search_controller: SpellSearchController
    preferences_controller: PreferencesController
    search_hotkey: Hotkey
    carbon: Any
    carbon_hotkey_ref: Any
    carbon_event_handler_ref: Any
    local_hotkey_monitor: Any
    local_hotkey_handler: Any
    simulate_command: str | None

    def initWithSpells_creatures_spellLookup_overlay_simulate_(
        self,
        spells,
        creatures,
        spell_lookup,
        overlay,
        simulate_command,
    ):
        self = objc.super(AppDelegate, self).init()
        if self is None:
            return None
        self.spells = list(spells)
        self.creatures = list(creatures)
        self.spell_lookup = spell_lookup
        self.overlay = overlay
        self.simulate_command = simulate_command
        self.status_item = None
        self.main_controller = None
        self.search_menu_item = None
        self.status_search_item = None
        self.search_controller = None
        self.preferences_controller = None
        self.search_hotkey = load_search_hotkey()
        self.carbon = None
        self.carbon_hotkey_ref = None
        self.carbon_event_handler_ref = None
        self.local_hotkey_monitor = None
        self.local_hotkey_handler = None
        return self

    def applicationDidFinishLaunching_(self, _notification):
        global GLOBAL_HOTKEY_DELEGATE
        GLOBAL_HOTKEY_DELEGATE = self
        self.main_controller = MainWindowController.alloc().initWithBestiary_spells_spellLookup_overlay_(
            self.creatures,
            self.spells,
            self.spell_lookup,
            self.overlay,
        )
        self.search_controller = SpellSearchController.alloc().initWithSpells_overlay_(self.spells, self.overlay)
        self.preferences_controller = PreferencesController.alloc().initWithAppDelegate_(self)
        APP_RETAINED_OBJECTS.extend([self.main_controller, self.search_controller, self.preferences_controller])
        self.installMainMenu()
        self.installStatusMenu()
        self.installHotkeyMonitor()
        self.main_controller.show_(None)

        if self.simulate_command:
            self.handleCommand_(self.simulate_command)
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                3.0,
                self,
                "quit:",
                None,
                False,
            )
            return

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

        main_window_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Show Main Window",
            "showMainWindow:",
            "0",
        )
        main_window_item.setTarget_(self)
        app_menu.addItem_(main_window_item)
        app_menu.addItem_(NSMenuItem.separatorItem())

        search_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Search Spell...",
            "showSearch:",
            self.search_hotkey.key,
        )
        search_item.setTarget_(self)
        search_item.setKeyEquivalentModifierMask_(self.search_hotkey.modifiers)
        self.search_menu_item = search_item
        app_menu.addItem_(search_item)
        app_menu.addItem_(NSMenuItem.separatorItem())

        preferences_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Preferences...",
            "showPreferences:",
            ",",
        )
        preferences_item.setTarget_(self)
        app_menu.addItem_(preferences_item)
        app_menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit Arcane Manager", "quit:", "q")
        quit_item.setTarget_(self)
        app_menu.addItem_(quit_item)

        app_menu_item.setSubmenu_(app_menu)
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

        main_window_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Show Main Window",
            "showMainWindow:",
            "",
        )
        main_window_item.setTarget_(self)
        menu.addItem_(main_window_item)
        menu.addItem_(NSMenuItem.separatorItem())

        search_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"Search Spell... ({hotkey_display(self.search_hotkey)})",
            "showSearch:",
            "",
        )
        search_item.setTarget_(self)
        self.status_search_item = search_item
        menu.addItem_(search_item)
        menu.addItem_(NSMenuItem.separatorItem())

        preferences_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Preferences...",
            "showPreferences:",
            "",
        )
        preferences_item.setTarget_(self)
        menu.addItem_(preferences_item)
        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit Arcane Manager", "quit:", "q")
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)
        self.status_item.setMenu_(menu)

    def installHotkeyMonitor(self):
        self.local_hotkey_handler = lambda event: None if self.handleHotkeyEvent_(event) else event
        self.local_hotkey_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown,
            self.local_hotkey_handler,
        )
        APP_RETAINED_OBJECTS.extend([self.local_hotkey_handler, self.local_hotkey_monitor])
        self.installCarbonHotkey()

    def installCarbonHotkey(self):
        try:
            self.carbon = load_carbon_framework()
            event_type = CarbonEventTypeSpec(CARBON_EVENT_CLASS_KEYBOARD, CARBON_EVENT_HOTKEY_PRESSED)
            handler_ref = ctypes.c_void_p()
            status = self.carbon.InstallEventHandler(
                self.carbon.GetApplicationEventTarget(),
                CARBON_HOTKEY_CALLBACK,
                1,
                ctypes.byref(event_type),
                None,
                ctypes.byref(handler_ref),
            )
            if status != 0:
                log(f"Global hotkey handler installation failed with status {status}.")
                return
            self.carbon_event_handler_ref = handler_ref
            APP_RETAINED_OBJECTS.extend([self.carbon, self.carbon_event_handler_ref, CARBON_HOTKEY_CALLBACK])
            self.registerCarbonHotkey()
        except Exception as exc:
            log(f"Global hotkey setup failed: {exc}")

    def registerCarbonHotkey(self):
        if self.carbon is None:
            return
        self.unregisterCarbonHotkey()
        hotkey_ref = ctypes.c_void_p()
        status = self.carbon.RegisterEventHotKey(
            ctypes.c_uint32(self.search_hotkey.key_code),
            ctypes.c_uint32(carbon_modifier_flags(self.search_hotkey.modifiers)),
            CarbonEventHotKeyID(CARBON_HOTKEY_SIGNATURE, 1),
            self.carbon.GetApplicationEventTarget(),
            0,
            ctypes.byref(hotkey_ref),
        )
        if status != 0:
            log(f"Global search hotkey registration failed for {hotkey_display(self.search_hotkey)} with status {status}.")
            return
        self.carbon_hotkey_ref = hotkey_ref
        APP_RETAINED_OBJECTS.append(self.carbon_hotkey_ref)
        log(f"Global search hotkey enabled: {hotkey_display(self.search_hotkey)}.")

    def unregisterCarbonHotkey(self):
        if self.carbon is None or self.carbon_hotkey_ref is None:
            return
        try:
            self.carbon.UnregisterEventHotKey(self.carbon_hotkey_ref)
        except Exception as exc:
            log(f"Global hotkey unregister error: {exc}")
        self.carbon_hotkey_ref = None

    def handleHotkeyEvent_(self, event) -> bool:
        if self.preferences_controller is not None and self.preferences_controller.captureHotkeyEvent_(event):
            return True

        modifiers = int(event.modifierFlags()) & SUPPORTED_HOTKEY_MODIFIERS
        key = str(event.charactersIgnoringModifiers() or "").lower()
        if modifiers == self.search_hotkey.modifiers and int(event.keyCode()) == self.search_hotkey.key_code:
            self.showSearch_(None)
            return True
        return False

    def showMainWindow_(self, _sender):
        self.main_controller.show_(None)

    def showSearch_(self, _sender):
        self.search_controller.show_(None)

    def showPreferences_(self, _sender):
        self.preferences_controller.show_(None)

    def setSearchHotkey_(self, hotkey: Hotkey):
        self.search_hotkey = hotkey
        save_search_hotkey(hotkey)
        self.registerCarbonHotkey()
        if self.search_menu_item is not None:
            self.search_menu_item.setKeyEquivalent_(hotkey.key)
            self.search_menu_item.setKeyEquivalentModifierMask_(hotkey.modifiers)
        if self.status_search_item is not None:
            self.status_search_item.setTitle_(f"Search Spell... ({hotkey_display(hotkey)})")
        log(f"Search hotkey set to {hotkey_display(hotkey)}.")

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

    def handleCommand_(self, command: str):
        spell = find_spell_in_text(command, self.spell_lookup)
        if spell is not None:
            self.overlay.showSpell_(spell)

    def applicationWillTerminate_(self, _notification):
        self.unregisterCarbonHotkey()

    def applicationShouldTerminateAfterLastWindowClosed_(self, _sender):
        return False

    def quit_(self, _sender):
        self.unregisterCarbonHotkey()
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
    parser.add_argument(
        "--hide-after",
        type=float,
        default=5.0,
        help="Seconds before hiding the overlay. Use 0 to keep it open.",
    )
    parser.add_argument(
        "--simulate",
        help="Show a spell by alias, then exit.",
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

    overlay = OverlayController.alloc().initWithHideAfter_(args.hide_after)
    delegate = AppDelegate.alloc().initWithSpells_creatures_spellLookup_overlay_simulate_(
        spells,
        creatures,
        lookup,
        overlay,
        args.simulate,
    )
    APP_RETAINED_OBJECTS.extend([overlay, delegate])
    log(f"Starting app with {len(spells)} spells and {len(creatures)} creatures.")
    app.setDelegate_(delegate)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

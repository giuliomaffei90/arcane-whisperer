#!/usr/bin/env python3
"""
macOS Arcane Whisperer spell listener.

Listens for configured spell names with macOS' native speech framework
and shows an always-on-top overlay with the spell details.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import queue
import re
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

try:
    import objc
    from AppKit import (
        NSApp,
        NSApplication,
        NSApplicationActivationPolicyRegular,
        NSAlert,
        NSBackingStoreBuffered,
        NSBezierPath,
        NSColor,
        NSFont,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSStringDrawingUsesFontLeading,
        NSStringDrawingUsesLineFragmentOrigin,
        NSMakeRect,
        NSMenu,
        NSMenuItem,
        NSPanel,
        NSScrollView,
        NSScreen,
        NSSpeechRecognizer,
        NSStatusBar,
        NSTrackingActiveAlways,
        NSTrackingArea,
        NSTrackingInVisibleRect,
        NSTrackingMouseEnteredAndExited,
        NSVariableStatusItemLength,
        NSView,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskTitled,
        NSWindowStyleMaskUtilityWindow,
        NSTextField,
    )
    from AVFoundation import AVAudioEngine
    from Foundation import (
        NSMutableAttributedString,
        NSBundle,
        NSMakePoint,
        NSMakeRange,
        NSMakeSize,
        NSObject,
        NSLocale,
        NSTimer,
    )
    from Speech import (
        SFSpeechAudioBufferRecognitionRequest,
        SFSpeechRecognizer,
        SFSpeechRecognizerAuthorizationStatusAuthorized,
        SFSpeechRecognizerAuthorizationStatusDenied,
        SFSpeechRecognizerAuthorizationStatusRestricted,
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
LOG_FILE = Path.home() / "Library" / "Logs" / "Arcane Whisperer" / "arcane_whisperer.log"
APP_RETAINED_OBJECTS: list[Any] = []


def normalize(text: str) -> str:
    """Normalize spoken commands and aliases for reliable lookup."""
    folded = unicodedata.normalize("NFKD", text.lower())
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    cleaned = []
    for char in ascii_text:
        cleaned.append(char if char.isalnum() else " ")
    return " ".join("".join(cleaned).split())


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
        names = raw.get("names", {})
        aliases = list(raw.get("aliases", []))
        for value in (raw.get("name"), names.get("en"), names.get("it")):
            if value:
                aliases.append(str(value))

        visible_name = raw.get("name") or names.get("it") or names.get("en")
        if not visible_name:
            raise ValueError(f"Spell entry without a name: {raw!r}")

        return cls(
            id=str(raw.get("id") or normalize(visible_name).replace(" ", "-")),
            name=str(visible_name),
            italian_name=str(names.get("it", "")),
            aliases=tuple(dict.fromkeys(a.strip() for a in aliases if a.strip())),
            level=str(raw.get("level", "")),
            school=str(raw.get("school", "")),
            casting_time=str(raw.get("casting_time", "")),
            range=str(raw.get("range", "")),
            components=str(raw.get("components", "")),
            duration=str(raw.get("duration", "")),
            description=str(raw.get("description", "")),
            higher_levels=str(raw.get("higher_levels", "")),
            spell_lists=tuple(str(item) for item in raw.get("spell_lists", []) if str(item).strip()),
            source=str(raw.get("source", "")),
        )


def load_spells(path: Path) -> tuple[list[Spell], dict[str, Spell]]:
    if not path.exists():
        raise FileNotFoundError(f"Spell file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    raw_spells = payload.get("spells", payload)
    if not isinstance(raw_spells, list):
        raise ValueError("Spell file must contain a list or an object with a 'spells' list.")

    spells = [Spell.from_dict(item) for item in raw_spells]
    lookup: dict[str, Spell] = {}
    for spell in spells:
        for alias in spell.aliases:
            key = normalize(alias)
            if key:
                lookup[key] = spell
    return spells, lookup


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


def attributed_spell_body(body: str):
    dice_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.58, 0.95, 0.28, 1.0)
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

    for match in re.finditer(r"\b\d+d\d+\b", body, flags=re.I):
        attributed.addAttribute_value_range_(
            NSForegroundColorAttributeName,
            dice_color,
            NSMakeRange(match.start(), match.end() - match.start()),
        )
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


def contextual_strings_for_spells(spells: list[Spell]) -> list[str]:
    strings: list[str] = []
    for spell in spells:
        strings.extend(spell.aliases)
        strings.append(spell.name)
    return list(dict.fromkeys(item for item in strings if item))


def find_spell_in_text(text: str, lookup: dict[str, Spell]) -> Spell | None:
    normalized = f" {normalize(text)} "
    best_match: tuple[int, int, Spell] | None = None
    for alias, spell in lookup.items():
        needle = f" {alias} "
        index = normalized.rfind(needle)
        if index < 0:
            continue
        candidate = (index, len(alias), spell)
        if best_match is None or candidate[:2] > best_match[:2]:
            best_match = candidate
    if best_match:
        return best_match[2]

    return find_fuzzy_spell_in_text(normalized.strip(), lookup)


def find_fuzzy_spell_in_text(normalized_text: str, lookup: dict[str, Spell]) -> Spell | None:
    words = normalized_text.split()
    if not words:
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
                score = SequenceMatcher(None, alias, candidate).ratio()
                threshold = 0.80 if len(alias) >= 9 else 0.86
                if score < threshold:
                    continue
                ranked = (score, start, spell, alias, candidate)
                if best_match is None or ranked[:2] > best_match[:2]:
                    best_match = ranked

        compact_alias = alias.replace(" ", "")
        compact_text = normalized_text.replace(" ", "")
        if len(compact_alias) >= 8 and compact_text:
            compact_score = SequenceMatcher(None, compact_alias, compact_text).ratio()
            if compact_score >= 0.80:
                ranked = (compact_score, len(words), spell, alias, normalized_text)
                if best_match is None or ranked[:2] > best_match[:2]:
                    best_match = ranked

    if best_match:
        score, _start, spell, alias, candidate = best_match
        log(f"Fuzzy match: {spell.name} ({candidate!r} ~= {alias!r}, {score:.2f})")
        return spell
    return None


def whisper_prompt_for_spells(spell_names: list[str]) -> str:
    names = ", ".join(spell_names[:120])
    return (
        "This audio may contain Dungeons and Dragons spell names in Italian or English. "
        f"Possible spell names include: {names}."
    )


def log(message: str):
    line = f"[Arcane Whisperer] {message}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def parse_locales(locales: str) -> list[str]:
    parsed = [part.strip() for part in locales.split(",") if part.strip()]
    return list(dict.fromkeys(parsed)) or ["it-IT", "en-US"]


def make_label(text: str, frame: tuple[int, int, int, int], size: float, bold: bool = False):
    label = NSTextField.labelWithString_(text)
    label.setFrame_(NSMakeRect(*frame))
    label.setTextColor_(NSColor.whiteColor())
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(True)
    label.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    return label


def make_multiline(label: NSTextField):
    label.setLineBreakMode_(0)
    label.setUsesSingleLineMode_(False)
    return label


class OverlayController(NSObject):
    panel: NSPanel
    title_label: NSTextField
    italian_name_label: NSTextField
    meta_label: NSTextField
    scroll_view: NSScrollView
    scroll_content: FlippedView
    body_label: NSTextField
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

    def initWithHideAfter_(self, hide_after: float):
        self = objc.super(OverlayController, self).init()
        if self is None:
            return None

        self.hide_after = hide_after
        self.timer = None
        self.mouse_inside = False

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
        self.panel.setTitle_("Arcane Whisperer")
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

        self.scroll_view = NSScrollView.alloc().initWithFrame_(NSMakeRect(24, 24, 592, 356))
        self.scroll_view.setHasVerticalScroller_(True)
        self.scroll_view.setAutohidesScrollers_(False)
        self.scroll_view.setDrawsBackground_(False)
        self.scroll_view.setBorderType_(0)
        self.scroll_content = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, 592, 356))
        self.scroll_view.setDocumentView_(self.scroll_content)

        self.body_label = make_multiline(make_label("", (0, 0, 560, 278), 14))

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
        self.hide_(None)

    def _set_detail_controls_hidden(self, hidden: bool):
        for view in self.detail_views:
            view.setHidden_(hidden)

    def _layout_spell_details(self, attributed_body):
        body_width = 560
        scroll_height = 356
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
        self.title_label.setStringValue_(title)
        self.italian_name_label.setStringValue_("")
        self.meta_label.setStringValue_(meta)
        self.body_label.setStringValue_(body)
        self.scroll_content.setFrame_(NSMakeRect(0, 0, 592, 356))
        self.body_label.setFrame_(NSMakeRect(0, 0, 560, 356))
        self._set_detail_controls_hidden(True)
        self.panel.orderFrontRegardless()

    def showStatus_(self, payload: dict[str, str]):
        self.showMessage_meta_body_(
            payload.get("title", ""),
            payload.get("meta", ""),
            payload.get("body", ""),
        )

    def showSpell_(self, spell: Spell):
        title, meta, body = format_spell_for_overlay(spell)
        flags = component_flags(spell.components)
        attributed_body = attributed_spell_body(body)

        self.title_label.setStringValue_(title)
        italian_name = spell.italian_name.strip()
        if italian_name and normalize(italian_name) != normalize(spell.name):
            self.italian_name_label.setStringValue_(f"({italian_name})")
        else:
            self.italian_name_label.setStringValue_("")
        self.meta_label.setStringValue_(meta)
        self.body_label.setAttributedStringValue_(attributed_body)
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

    def hide_(self, _timer):
        self.timer = None
        if self.mouse_inside:
            return
        self.panel.orderOut_(None)

    def windowWillClose_(self, _notification):
        NSApp.terminate_(None)


class CommandSpellListener(NSObject):
    recognizer: NSSpeechRecognizer
    spell_lookup: dict[str, Spell]
    overlay: OverlayController

    def initWithSpellLookup_overlay_(self, spell_lookup, overlay):
        self = objc.super(CommandSpellListener, self).init()
        if self is None:
            return None
        self.spell_lookup = spell_lookup
        self.overlay = overlay
        return self

    def start(self):
        commands = sorted({alias for spell in self.spell_lookup.values() for alias in spell.aliases})
        self.recognizer = NSSpeechRecognizer.alloc().init()
        self.recognizer.setCommands_(commands)
        self.recognizer.setListensInForegroundOnly_(False)
        self.recognizer.setBlocksOtherRecognizers_(False)
        self.recognizer.setDelegate_(self)
        self.recognizer.startListening()
        log(f"Command backend started with {len(commands)} aliases.")
        self.overlay.showMessage_meta_body_(
            "Listening...",
            "macOS command backend",
            "Say one of the aliases configured in spells.json.",
        )

    def speechRecognizer_didRecognizeCommand_(self, _recognizer, command):
        log(f"Recognized command: {command}")
        spell = self.spell_lookup.get(normalize(str(command)))
        if spell is not None:
            self.overlay.showSpell_(spell)


class WhisperSpellListener:
    def __init__(
        self,
        spell_lookup: dict[str, Spell],
        overlay: OverlayController,
        model_name: str,
        prompt: str,
        debug: bool,
        sample_rate: int = 16000,
        window_seconds: float = 3.5,
        step_seconds: float = 1.2,
    ):
        self.spell_lookup = spell_lookup
        self.overlay = overlay
        self.model_name = model_name
        self.prompt = prompt
        self.debug = debug
        self.sample_rate = sample_rate
        self.window_seconds = window_seconds
        self.step_seconds = step_seconds
        self.audio_queue: queue.Queue[Any] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.stream: Any = None
        self.model: Any = None
        self.last_spell_id: str | None = None
        self.last_spell_at = 0.0

    def start(self):
        self.overlay.showMessage_meta_body_(
            "Loading Whisper...",
            "Local multilingual backend",
            "You can say spell names in Italian or English.",
        )
        self.worker = threading.Thread(target=self.run, name="WhisperSpellListener", daemon=True)
        self.worker.start()

    def run(self):
        try:
            import numpy as np
            import sounddevice as sd
            from faster_whisper import WhisperModel
        except ImportError as exc:
            log(f"Missing Whisper dependency: {exc}")
            self.showStatus_("Missing dependencies", "Whisper", "Run .venv/bin/python -m pip install -r requirements.txt")
            return

        try:
            model_source = BASE_DIR / "whisper_models" / self.model_name
            if not model_source.exists():
                model_source = Path(self.model_name)
            log(f"Loading Whisper model: {model_source}")
            self.model = WhisperModel(str(model_source), device="cpu", compute_type="int8")
            self.showStatus_(
                "Listening...",
                f"Local Whisper: {self.model_name}",
                "You can say spell names in Italian or English. Examples: palla di fuoco, fireball, cure wounds.",
            )

            def audio_callback(indata, _frames, _time_info, status):
                if status:
                    log(f"Audio input status: {status}")
                mono = indata[:, 0].copy()
                self.audio_queue.put(mono)

            with sd.InputStream(
                channels=1,
                samplerate=self.sample_rate,
                dtype="float32",
                blocksize=int(self.sample_rate * 0.25),
                callback=audio_callback,
            ) as stream:
                self.stream = stream
                log(
                    f"Whisper backend started: model={self.model_name}, "
                    f"sample_rate={self.sample_rate}, window={self.window_seconds}s."
                )
                rolling = np.zeros(0, dtype=np.float32)
                last_transcribe_at = 0.0
                max_samples = int(self.sample_rate * self.window_seconds)

                while not self.stop_event.is_set():
                    try:
                        chunk = self.audio_queue.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    rolling = np.concatenate((rolling, chunk))
                    if rolling.size > max_samples:
                        rolling = rolling[-max_samples:]

                    now = time.monotonic()
                    if rolling.size < int(self.sample_rate * 1.0):
                        continue
                    if now - last_transcribe_at < self.step_seconds:
                        continue

                    last_transcribe_at = now
                    audio = rolling.copy()
                    if float(np.max(np.abs(audio))) < 0.01:
                        continue

                    self.transcribeAudio_(audio)
        except Exception as exc:
            log(f"Whisper backend error: {exc}")
            self.showStatus_("Whisper error", "Multilingual backend", str(exc))

    def transcribeAudio_(self, audio):
        segments, info = self.model.transcribe(
            audio,
            language=None,
            initial_prompt=self.prompt,
            beam_size=1,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 450},
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        if not text:
            return

        language = getattr(info, "language", "?")
        probability = getattr(info, "language_probability", 0.0)
        if self.debug:
            log(f"TRANSCRIBED [{language} {probability:.2f}]: {text}")

        spell = find_spell_in_text(text, self.spell_lookup)
        if spell is None:
            return

        now = time.monotonic()
        if spell.id == self.last_spell_id and now - self.last_spell_at < 2.5:
            return

        self.last_spell_id = spell.id
        self.last_spell_at = now
        log(f"Spell found: {spell.name} from Whisper {language!r}: {text!r}")
        self.overlay.performSelectorOnMainThread_withObject_waitUntilDone_("showSpell:", spell, False)

    def showStatus_(self, title: str, meta: str, body: str):
        self.overlay.performSelectorOnMainThread_withObject_waitUntilDone_(
            "showStatus:",
            {"title": title, "meta": meta, "body": body},
            False,
        )

    def stopRecognition(self):
        self.stop_event.set()
        if self.stream is not None:
            try:
                self.stream.abort()
            except Exception:
                pass


class SpeechSpellListener(NSObject):
    audio_engine: AVAudioEngine | None
    recognition_requests: dict[str, SFSpeechAudioBufferRecognitionRequest]
    recognition_tasks: dict[str, Any]
    recognizers: dict[str, SFSpeechRecognizer]
    overlay: OverlayController
    spell_lookup: dict[str, Spell]
    contextual_strings: list[str]
    locale_identifiers: list[str]
    last_spell_id: str | None
    last_spell_at: float
    last_callback_at: float
    restart_timer: NSTimer | None
    refresh_timer: NSTimer | None
    watchdog_timer: NSTimer | None
    locale_restart_timers: dict[str, NSTimer]
    task_serial: int
    task_serials: dict[str, int]
    is_stopping: bool
    tap_installed: bool
    debug: bool

    def initWithSpellLookup_overlay_contextualStrings_locales_debug_(
        self,
        spell_lookup,
        overlay,
        contextual_strings,
        locale_identifiers,
        debug,
    ):
        self = objc.super(SpeechSpellListener, self).init()
        if self is None:
            return None
        self.spell_lookup = spell_lookup
        self.overlay = overlay
        self.contextual_strings = list(contextual_strings)
        self.locale_identifiers = list(locale_identifiers)
        self.last_spell_id = None
        self.last_spell_at = 0.0
        self.last_callback_at = 0.0
        self.audio_engine = None
        self.recognition_requests = {}
        self.recognition_tasks = {}
        self.recognizers = {}
        self.restart_timer = None
        self.refresh_timer = None
        self.watchdog_timer = None
        self.locale_restart_timers = {}
        self.task_serial = 0
        self.task_serials = {}
        self.is_stopping = False
        self.tap_installed = False
        self.debug = debug
        return self

    def start(self):
        if not NSBundle.mainBundle().objectForInfoDictionaryKey_("NSSpeechRecognitionUsageDescription"):
            message = (
                "The Speech backend must be launched from Arcane Whisperer.app, not directly "
                "from the Python binary. macOS requires the NSSpeechRecognitionUsageDescription key."
            )
            log(message)
            self.overlay.showMessage_meta_body_(
                "App launch required",
                "Speech Recognition permission",
                "Close this window and open Arcane Whisperer.app or use ArcaneWhisperer.command, "
                "which launches the correct app bundle.",
            )
            return

        log("Requesting Speech Recognition permission.")
        self.overlay.showMessage_meta_body_(
            "Requesting permissions...",
            "Microphone and speech recognition",
            "If macOS shows a speech recognition prompt, allow access. "
            "Microphone permission alone is not enough for this backend.",
        )
        SFSpeechRecognizer.requestAuthorization_(self.authorizationHandler_)

    def authorizationHandler_(self, status):
        if status == SFSpeechRecognizerAuthorizationStatusAuthorized:
            self.performSelectorOnMainThread_withObject_waitUntilDone_("startAudio:", None, False)
            return

        if status == SFSpeechRecognizerAuthorizationStatusDenied:
            reason = "Speech Recognition permission denied."
        elif status == SFSpeechRecognizerAuthorizationStatusRestricted:
            reason = "Speech Recognition is unavailable on this Mac or account."
        else:
            reason = "Speech Recognition permission was not granted."

        log(reason)
        self.performSelectorOnMainThread_withObject_waitUntilDone_("showPermissionError:", reason, False)

    def showPermissionError_(self, reason: str):
        self.overlay.showMessage_meta_body_(
            "Cannot listen",
            reason,
            "Open System Settings > Privacy & Security > Speech Recognition "
            "and enable permission for Python/Terminal. Check Microphone too.",
        )

    def startAudio_(self, _sender):
        unavailable_locales = []
        for locale_identifier in self.locale_identifiers:
            locale = NSLocale.localeWithLocaleIdentifier_(locale_identifier)
            recognizer = SFSpeechRecognizer.alloc().initWithLocale_(locale)
            if recognizer is None or not recognizer.isAvailable():
                unavailable_locales.append(locale_identifier)
                continue
            self.recognizers[locale_identifier] = recognizer

        if not self.recognizers:
            self.overlay.showMessage_meta_body_(
                "Recognizer unavailable",
                f"Requested locales: {', '.join(self.locale_identifiers)}",
                "Check that Dictation/Siri are available in macOS settings.",
            )
            return
        if unavailable_locales:
            log(f"Unavailable Speech locales: {', '.join(unavailable_locales)}")

        try:
            self.beginRecognition()
        except Exception as exc:
            log(f"Speech backend startup error: {exc}")
            self.overlay.showMessage_meta_body_(
                "Listening startup error",
                "Speech backend",
                str(exc),
            )

    def beginRecognition(self):
        self.is_stopping = False
        self.startAudioEngine()
        self.startRecognitionTask_("start")
        self.startWatchdog()

        log(f"Speech backend started with locales {', '.join(self.recognizers)}.")
        self.overlay.showMessage_meta_body_(
            "Listening...",
            f"Speech backend, locales {', '.join(self.recognizers)}",
            "Say the name of a spell, even inside a sentence. "
            "Examples: 'lancio palla di fuoco' or 'I cast fireball'.",
        )

    def startAudioEngine(self):
        if self.audio_engine is None:
            self.audio_engine = AVAudioEngine.alloc().init()

        input_node = self.audio_engine.inputNode()
        audio_format = input_node.outputFormatForBus_(0)

        if not self.tap_installed:
            def tap_block(buffer, _when):
                for request in list(self.recognition_requests.values()):
                    request.appendAudioPCMBuffer_(buffer)

            input_node.installTapOnBus_bufferSize_format_block_(0, 1024, audio_format, tap_block)
            self.tap_installed = True

        if not self.audio_engine.isRunning():
            self.audio_engine.prepare()
            ok, error = self.audio_engine.startAndReturnError_(None)
            if not ok:
                raise RuntimeError(error or "AVAudioEngine did not start.")

    def startRecognitionTask_(self, reason: str):
        self.startRecognitionTasksForLocales_reason_(list(self.recognizers), reason)

    def startRecognitionTasksForLocales_reason_(self, locale_identifiers, reason: str):
        for locale_identifier in locale_identifiers:
            self.cancelRecognitionTaskForLocale_(locale_identifier)

        opened_locales = []
        for locale_identifier in locale_identifiers:
            recognizer = self.recognizers.get(locale_identifier)
            if recognizer is None:
                continue

            serial = self.task_serials.get(locale_identifier, 0) + 1
            self.task_serials[locale_identifier] = serial

            recognition_request = SFSpeechAudioBufferRecognitionRequest.alloc().init()
            recognition_request.setShouldReportPartialResults_(True)
            recognition_request.setContextualStrings_(self.contextual_strings)

            if recognizer.supportsOnDeviceRecognition():
                recognition_request.setRequiresOnDeviceRecognition_(False)

            def result_handler(result, error, locale_identifier=locale_identifier):
                if serial != self.task_serials.get(locale_identifier) or self.is_stopping:
                    return

                self.last_callback_at = time.monotonic()

                if result is not None:
                    text = str(result.bestTranscription().formattedString())
                    if self.debug:
                        log(f"Transcribed [{locale_identifier}]: {text}")
                    self.handleTranscript_(text)

                if error is not None:
                    log(f"Speech task ended [{locale_identifier}] ({reason}): {error}")
                    self.performSelectorOnMainThread_withObject_waitUntilDone_(
                        "scheduleLocaleRestart:",
                        locale_identifier,
                        False,
                    )

            self.recognition_requests[locale_identifier] = recognition_request
            self.recognition_tasks[locale_identifier] = recognizer.recognitionTaskWithRequest_resultHandler_(
                recognition_request,
                result_handler,
            )
            opened_locales.append(locale_identifier)

        if opened_locales:
            log(f"Opened Speech tasks: {reason} ({', '.join(sorted(opened_locales))}).")
        else:
            log(f"No Speech tasks opened for: {reason}.")
            self.overlay.showMessage_meta_body_(
                "No active recognizer",
                "Speech backend",
                "Could not open Speech tasks for the configured locales.",
            )
            return

        if self.refresh_timer is not None:
            self.refresh_timer.invalidate()
        self.refresh_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            50.0,
            self,
            "refreshRecognitionTask:",
            None,
            False,
        )

    def cancelRecognitionTask(self):
        if getattr(self, "restart_timer", None) is not None:
            self.restart_timer.invalidate()
            self.restart_timer = None
        if getattr(self, "refresh_timer", None) is not None:
            self.refresh_timer.invalidate()
            self.refresh_timer = None
        for timer in list(self.locale_restart_timers.values()):
            timer.invalidate()
        self.locale_restart_timers = {}

        for locale_identifier in list(self.recognition_requests):
            self.cancelRecognitionTaskForLocale_(locale_identifier)

    def cancelRecognitionTaskForLocale_(self, locale_identifier: str):
        timer = self.locale_restart_timers.pop(locale_identifier, None)
        if timer is not None:
            timer.invalidate()

        self.task_serials[locale_identifier] = self.task_serials.get(locale_identifier, 0) + 1

        request = self.recognition_requests.pop(locale_identifier, None)
        if request is not None:
            request.endAudio()
        task = self.recognition_tasks.pop(locale_identifier, None)
        if task is not None:
            task.cancel()

    def stopRecognition(self):
        self.is_stopping = True
        self.cancelRecognitionTask()
        if getattr(self, "watchdog_timer", None) is not None:
            self.watchdog_timer.invalidate()
            self.watchdog_timer = None

        if self.audio_engine is not None:
            if self.tap_installed:
                try:
                    self.audio_engine.inputNode().removeTapOnBus_(0)
                except Exception as exc:
                    log(f"Audio tap removal error: {exc}")
                self.tap_installed = False
            if self.audio_engine.isRunning():
                self.audio_engine.stop()
            self.audio_engine = None

    def scheduleRecognitionRestart_(self, _sender):
        if self.is_stopping:
            return
        if self.restart_timer is not None:
            return
        self.restart_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.5,
            self,
            "restartRecognition:",
            None,
            False,
        )

    def scheduleLocaleRestart_(self, locale_identifier: str):
        if self.is_stopping:
            return
        if locale_identifier in self.locale_restart_timers:
            return
        timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            8.0,
            self,
            "restartLocale:",
            locale_identifier,
            False,
        )
        self.locale_restart_timers[locale_identifier] = timer

    def restartLocale_(self, timer):
        locale_identifier = str(timer.userInfo())
        self.locale_restart_timers.pop(locale_identifier, None)
        if self.is_stopping:
            return
        log(f"Restarting Speech task for locale {locale_identifier} without touching the others.")
        try:
            self.startRecognitionTasksForLocales_reason_([locale_identifier], "locale-restart")
        except Exception as exc:
            log(f"Locale restart error for {locale_identifier}: {exc}")

    def restartRecognition_(self, _sender):
        self.restart_timer = None
        if self.is_stopping:
            return
        log("Restarting Speech tasks without restarting the microphone.")
        try:
            self.startAudioEngine()
            self.startRecognitionTask_("restart")
        except Exception as exc:
            log(f"Speech backend restart error: {exc}")

    def refreshRecognitionTask_(self, _sender):
        self.refresh_timer = None
        if self.is_stopping:
            return
        log("Periodic Speech task refresh without restarting the microphone.")
        try:
            self.startRecognitionTask_("refresh")
        except Exception as exc:
            log(f"Speech backend refresh error: {exc}")

    def startWatchdog(self):
        self.last_callback_at = time.monotonic()
        if self.watchdog_timer is not None:
            self.watchdog_timer.invalidate()
        self.watchdog_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            10.0,
            self,
            "watchdogTick:",
            None,
            True,
        )

    def watchdogTick_(self, _sender):
        if self.is_stopping:
            return
        if self.audio_engine is None or not self.audio_engine.isRunning():
            log("Watchdog: audio engine stopped; fully restarting listening.")
            try:
                self.startAudioEngine()
                self.startRecognitionTask_("watchdog-audio")
            except Exception as exc:
                log(f"Audio watchdog error: {exc}")
            return

        idle_seconds = time.monotonic() - self.last_callback_at
        if idle_seconds > 25:
            log(f"Watchdog: no Speech callback for {idle_seconds:.0f}s; refreshing tasks.")
            try:
                self.startRecognitionTask_("watchdog-stale")
            except Exception as exc:
                log(f"Speech watchdog error: {exc}")

    def handleTranscript_(self, transcript: str):
        spell = find_spell_in_text(transcript, self.spell_lookup)
        if spell is None:
            return

        now = time.monotonic()
        if spell.id == self.last_spell_id and now - self.last_spell_at < 3.0:
            return

        self.last_spell_id = spell.id
        self.last_spell_at = now
        log(f"Spell found: {spell.name} from transcript {transcript!r}")
        self.performSelectorOnMainThread_withObject_waitUntilDone_("showSpell:", spell, False)
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "resetAfterSpell:",
            None,
            False,
        )

    def showSpell_(self, spell: Spell):
        self.overlay.showSpell_(spell)

    def resetAfterSpell_(self, _sender):
        if self.is_stopping:
            return
        try:
            self.startRecognitionTask_("spell-match")
        except Exception as exc:
            log(f"Post-spell reset error: {exc}")


class AppDelegate(NSObject):
    overlay: OverlayController
    spell_lookup: dict[str, Spell]
    contextual_strings: list[str]
    status_item: Any
    simulate_command: str | None
    backend: str
    locale_identifiers: list[str]
    whisper_model: str
    debug: bool
    listener: Any

    def initWithSpellLookup_overlay_contextualStrings_simulate_backend_locales_whisperModel_debug_(
        self,
        spell_lookup,
        overlay,
        contextual_strings,
        simulate_command,
        backend,
        locale_identifiers,
        whisper_model,
        debug,
    ):
        self = objc.super(AppDelegate, self).init()
        if self is None:
            return None
        self.spell_lookup = spell_lookup
        self.overlay = overlay
        self.contextual_strings = list(contextual_strings)
        self.simulate_command = simulate_command
        self.backend = backend
        self.locale_identifiers = list(locale_identifiers)
        self.whisper_model = whisper_model
        self.debug = debug
        self.listener = None
        self.status_item = None
        return self

    def applicationDidFinishLaunching_(self, _notification):
        self.installMainMenu()
        self.installStatusMenu()

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

        if self.backend == "whisper":
            self.listener = WhisperSpellListener(
                self.spell_lookup,
                self.overlay,
                self.whisper_model,
                whisper_prompt_for_spells(self.contextual_strings),
                self.debug,
            )
        elif self.backend == "command":
            self.listener = CommandSpellListener.alloc().initWithSpellLookup_overlay_(
                self.spell_lookup,
                self.overlay,
            )
        else:
            self.listener = SpeechSpellListener.alloc().initWithSpellLookup_overlay_contextualStrings_locales_debug_(
                self.spell_lookup,
                self.overlay,
                self.contextual_strings,
                self.locale_identifiers,
                self.debug,
            )
        self.listener.start()

    def installMainMenu(self):
        main_menu = NSMenu.alloc().init()
        app_menu_item = NSMenuItem.alloc().init()
        main_menu.addItem_(app_menu_item)

        app_menu = NSMenu.alloc().init()
        about_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "About Arcane Whisperer",
            "showAbout:",
            "",
        )
        about_item.setTarget_(self)
        app_menu.addItem_(about_item)
        app_menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit Arcane Whisperer", "quit:", "q")
        quit_item.setTarget_(self)
        app_menu.addItem_(quit_item)

        app_menu_item.setSubmenu_(app_menu)
        NSApp.setMainMenu_(main_menu)

    def installStatusMenu(self):
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        button = self.status_item.button()
        if button is not None:
            button.setTitle_("AW")
            button.setToolTip_("Arcane Whisperer")

        menu = NSMenu.alloc().init()
        about_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "About Arcane Whisperer",
            "showAbout:",
            "",
        )
        about_item.setTarget_(self)
        menu.addItem_(about_item)
        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit Arcane Whisperer", "quit:", "q")
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)
        self.status_item.setMenu_(menu)

    def showAbout_(self, _sender):
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Arcane Whisperer")
        alert.setInformativeText_(
            "A voice-powered spell overlay for Dungeons & Dragons 5e.\n\n"
            "Say a spell name in English or Italian and Arcane Whisperer shows "
            "its casting details without interrupting your game.\n\n"
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
        if self.listener is not None and hasattr(self.listener, "stopRecognition"):
            self.listener.stopRecognition()

    def quit_(self, _sender):
        if self.listener is not None and hasattr(self.listener, "stopRecognition"):
            self.listener.stopRecognition()
        NSApp.terminate_(None)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Arcane Whisperer spell listener for macOS.")
    parser.add_argument(
        "--spells",
        default=str(DEFAULT_SPELLS_FILE),
        help="Path to a JSON spell database.",
    )
    parser.add_argument(
        "--hide-after",
        type=float,
        default=5.0,
        help="Seconds before hiding the overlay. Use 0 to keep it open.",
    )
    parser.add_argument(
        "--simulate",
        help="Show a spell by alias without using the microphone, then exit.",
    )
    parser.add_argument(
        "--backend",
        choices=("whisper", "speech", "command"),
        default="whisper",
        help="whisper is multilingual local transcription; speech uses macOS Speech; command uses older macOS command recognition.",
    )
    parser.add_argument(
        "--whisper-model",
        default="base",
        help="faster-whisper model name. Use tiny for speed, base for balance, small for better accuracy.",
    )
    parser.add_argument(
        "--locale",
        help="Single speech recognition locale, for example it-IT or en-US. Overrides --locales.",
    )
    parser.add_argument(
        "--locales",
        default="it-IT,en-US",
        help="Comma-separated speech recognition locales. Default: it-IT,en-US.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print live transcriptions to the terminal.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    locale_identifiers = [args.locale] if args.locale else parse_locales(args.locales)
    spells, lookup = load_spells(Path(args.spells).expanduser())
    contextual_strings = contextual_strings_for_spells(spells)
    if not spells:
        raise SystemExit("No spells found in the spell database.")

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)

    overlay = OverlayController.alloc().initWithHideAfter_(args.hide_after)
    delegate = AppDelegate.alloc().initWithSpellLookup_overlay_contextualStrings_simulate_backend_locales_whisperModel_debug_(
        lookup,
        overlay,
        contextual_strings,
        args.simulate,
        args.backend,
        locale_identifiers,
        args.whisper_model,
        args.debug,
    )
    APP_RETAINED_OBJECTS.extend([overlay, delegate])
    log(
        f"Starting app with {len(spells)} spells, {len(lookup)} aliases, "
        f"{len(contextual_strings)} configured names, "
        f"backend={args.backend}, whisper_model={args.whisper_model}, "
        f"locales={','.join(locale_identifiers)}."
    )
    app.setDelegate_(delegate)
    app.run()
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())

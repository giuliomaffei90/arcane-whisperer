from __future__ import annotations

from .platform import Any, NSMutableAttributedString, NSMutableParagraphStyle, NSFont, NSFontAttributeName, NSFontManager, NSForegroundColorAttributeName, NSItalicFontMask, NSMakeRange, NSParagraphStyleAttributeName
from .content_links import COMPONENT_BADGE_PATTERN, dice_ranges_for_body
from .data import Spell
from .spell_format import component_flags, component_material
from .ui.core import theme_color

MONSTER_SECTION_HEADINGS = {"traits", "spells", "actions", "legendary actions"}

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

    for start, length, _expression in dice_ranges_for_body(body):
        attributed.addAttribute_value_range_(
            NSForegroundColorAttributeName,
            dice_color,
            NSMakeRange(start, length),
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
        if line.rstrip(":").lower() in MONSTER_SECTION_HEADINGS:
            attributed.addAttribute_value_range_(
                NSFontAttributeName,
                NSFont.boldSystemFontOfSize_(18),
                NSMakeRange(start, len(line)),
            )
            continue
        if line.endswith(":") and len(line) <= 80 and "." not in line:
            attributed.addAttribute_value_range_(
                NSFontAttributeName,
                NSFont.boldSystemFontOfSize_(15),
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
        if "spellcasting ability" in lower_line or "spell casting ability" in lower_line:
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

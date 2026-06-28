from __future__ import annotations

from .platform import Any, dataclass, random, re

DICE_PATTERN = re.compile(r"\b(\d+)d(\d+)(?:\s*([+-])\s*(\d+))?\b", flags=re.I)
DICE_INLINE_PATTERN = re.compile(r"\b\d+d\d+(?:\s*\+\s*\d+d\d+)*(?:\s*[+-]\s*\d+)?\b", flags=re.I)
DICE_FORMULA_PATTERN = re.compile(r"^\s*\d+d\d+(?:\s*\+\s*\d+d\d+)*(?:\s*[+-]\s*\d+)?\s*$", flags=re.I)


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

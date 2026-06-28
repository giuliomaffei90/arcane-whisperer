from __future__ import annotations

from ._shared import *
from .main_window import MainWindowController as _MainWindowController


class MainWindowController(objc.Category(_MainWindowController)):
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

    @objc.python_method
    def _combatant_hp_value(self, combatant: dict[str, Any]) -> int | None:
        hp = str(combatant.get("hp") or "").strip()
        if not hp:
            return None
        try:
            return int(hp)
        except ValueError:
            return None

    @objc.python_method
    def _is_combatant_down(self, combatant: dict[str, Any]) -> bool:
        hp = self._combatant_hp_value(combatant)
        return hp is not None and hp <= 0

    @objc.python_method
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

    @objc.python_method
    def _creature_for_combatant(self, combatant: dict[str, Any]) -> Creature | None:
        name = normalize(str(combatant.get("creature_name") or combatant.get("name") or ""))
        for creature in self.creatures:
            if normalize(creature.name) == name:
                return creature
        return None

    @objc.python_method
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

    @objc.python_method
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
            if name and desc.endswith(":") and not suffix:
                if lines and lines[-1]:
                    lines.append("")
                lines.append(f"{name}:")
                lines.append(desc)
                continue
            if text:
                if lines and lines[-1]:
                    lines.append("")
                lines.append(text)

    @objc.python_method
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

    @objc.python_method
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

    @objc.python_method
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
        spell_ranges = sorted(
            spell_ranges_for_body(body, self.spells, spell_section_ranges(body))
            + explicit_spell_ranges_for_entries(
                body,
                [creature.traits, creature.actions, creature.legendary_actions],
                self.spells,
                self.spell_lookup,
            ),
            key=lambda item: item[0],
        )
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

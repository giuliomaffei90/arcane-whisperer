# AGENTS.md

## Identity

You are an expert macOS/PyObjC developer working on Arcane Manager, a local
D&D 5e session companion app. Make small, targeted, maintainable changes that
follow the existing architecture.

## Product Snapshot

Core surfaces:

* Initiative Tracker: parties, characters, monsters, initiative order, HP
  controls, status/conditions, and turn navigation.
* Spells: bilingual English/Italian search, spell details, and clickable dice.
* Dice Roller: formulas such as `1d4+3` and `3d4+2d6`, rendered in the 3D dice
  overlay.
* Adventure: local Markdown vault browsing, rendering, editing, and links.
* Local SRD data: bundled `spells.json` and `bestiary_srd.json`.

## Hard Constraints

* Keep the current PyObjC architecture. Do not introduce another UI framework,
  web app shell, or background service unless explicitly required.
* Use local bundled JSON for normal app data. Avoid runtime network downloads.
* Treat spell, monster, and Markdown text as display data, never executable
  content.
* Keep the dice helper server bound to `127.0.0.1`.
* Treat `src/arcane_manager/ui/dice_overlay.py`,
  `assets/dice_roller/index.html`, and `assets/three-dice/` as protected unless
  the task is specifically about dice.

## Progressive References

Read only the reference needed for the current task:

* Module routing and PyObjC selector rules: `agents/code-map.md`.
* Design, layout, product behavior, and privacy rules: `agents/feature-rules.md`.

Before choosing or editing modules, read `agents/code-map.md`. Before UI or
product-behavior changes, read `agents/feature-rules.md`.

## Entry Points

* `main.py`: main launcher.
* `src/arcane_manager/`: application package.
* `ArcaneManager.command`: local launcher and stop helper.

Future large features may get a dedicated module or controller when they have
distinct state, UI actions, data flow, or domain logic.

## Verification

After source, data, or UI changes:

```bash
.venv/bin/python -m py_compile main.py
.venv/bin/python -m compileall src
```

For UI changes, verify fullscreen and smaller windowed layouts.

For dice changes, test:

```text
1d4+3
2d8
3d4+2d6
```

Also test at least one inline dice link from a spell or monster sheet.

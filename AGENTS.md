# AGENTS.md

Essential guide for agents editing Arcane Manager.

## Product

Arcane Manager is a local macOS companion app for D&D 5e sessions. It is no
longer a voice-recognition app.

Core surfaces:

* Initiative Tracker: parties, characters, monsters, initiative order, monster
  HP controls, and turn navigation.
* Spells: bilingual English and Italian search, spell details, and clickable
  dice expressions.
* Dice Roller: mixed dice formulas such as `3d4+2d6`, rendered with the 3D dice
  overlay.
* Local SRD data: bundled spell and monster JSON files.

Do not add microphone access, speech recognition, audio capture, wake words, or
global voice behavior unless the product direction explicitly changes.

## Architecture

* `SpellAudio.py` is the main app entry point. The name is legacy because the
  build script and launcher depend on it.
* `scripts/build_app.zsh` builds the standalone macOS app and release zip.
* `spells.json` and `bestiary_srd.json` are the primary bundled data sources.
* `assets/icons/` contains UI icons.
* `assets/dice_roller/index.html` and `assets/three-dice/` power the 3D dice
  overlay inside a local `WKWebView`.
* `ArcaneManager.command` is the local launcher and stop helper.

Keep the current PyObjC architecture. Do not introduce a second UI framework, a
web app shell, or background services unless the task explicitly requires it.
Prefer small targeted changes over broad rewrites.

## Design Direction

The app should feel like a polished dark macOS tabletop tool: compact, tactile,
legible, and calm.

Use:

* Dark matte background.
* Charcoal panels.
* Subtle borders.
* Restrained rounded rectangles.
* Dense but breathable layouts.
* Green for dice and HP emphasis.
* Yellow for spell metadata and spell links.
* Red or pink for monsters and danger states.
* White for class and player icons.

Avoid:

* Decorative gradients.
* Glowing blobs.
* Purple or beige theme pivots.
* Marketing-style hero sections.
* Purely ornamental controls.
* Oversized empty areas.

Every visible control should have a clear function.

## Layout Rules

The app must work in fullscreen and smaller windowed mode.

* Prevent overlap, clipping, and horizontal spill.
* Test by resizing the window.
* Let flexible elements absorb extra space, especially HP bars.
* Keep fixed labels and numeric columns stable.
* Truncate long monster names with an ellipsis.
* Do not leave empty placeholder rows.
* Search lists should filter while typing, without a separate Search button.

## Initiative Tracker

* The left panel is the library and setup area. It should scroll when needed.
* Party editing must support adding, editing, and removing characters.
* Characters need at least name, class, and armor class.
* Include Artificer in the class list.
* Player rows show class icons and armor class, not monster-style HP bars.
* Monster rows support HP tracking, damage, healing, and down/skipped states.
* `+` and `-` HP controls should ask for an amount.
* Turn advancement should skip combatants at 0 HP.
* Monster details open from the monster name or a deliberate details control.
* The details panel slides in from the right, claims layout space, and has an
  obvious close control.

## Spells

* Spell search must work in English and Italian.
* Spell rows should be compact text-list rows, not heavy gray buttons.
* Spell details should show English and Italian names when available.
* Dice expressions such as `8d6`, `1d20`, and `1d4+3` should be green and
  clickable.
* Clicking a dice expression should roll the exact formula, including modifiers.

## Dice Roller

Treat the 3D dice roller as a protected subsystem.

* Do not remove or rewrite `Dice3DRollerController`,
  `assets/dice_roller/index.html`, or `assets/three-dice/` unless the task is
  specifically about dice.
* Keep the local HTTP server and `WKWebView` asset loading path intact.
* Mixed pools must work, for example `3d4+2d6`.
* Modifiers must be included correctly, for example `1d4+3`.
* The displayed total must match visible dice and modifiers.
* Clicking outside the dice overlay should dismiss it.
* Test both inline dice links and the Dice Roller tab when touching dice logic.

## Data And Privacy

* Use local bundled JSON for app data.
* Validate and sanitize loaded JSON fields before display.
* Treat spell and monster text as display data, never executable content.
* Avoid runtime network downloads for normal app behavior.
* Do not include secrets, API keys, analytics tokens, credentials, or remote
  account data.
* Keep the dice helper server bound to `127.0.0.1`.

## Verification

After source, data, or UI changes:

```bash
.venv/bin/python -m py_compile SpellAudio.py
./scripts/build_app.zsh
```

For UI changes, verify fullscreen and smaller windowed layouts.

For dice changes, test:

```text
1d4+3
2d8
3d4+2d6
```

Also test at least one inline dice link from a spell or monster sheet.

Before release, confirm that the packaged app opens, the 3D dice roller works,
and the app does not request microphone or speech recognition permissions.
::: 

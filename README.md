# Arcane Whisperer

Python macOS app that listens to the microphone and shows an always-on-top spell overlay when it recognizes a configured spell name.

## Installation

To use the app, copy `Arcane Whisperer.app` to a Mac and open it.
The bundle already includes Python, native libraries, `spells.json`, and the Whisper `base` model.

Note: this build is arm64, so it is intended for Apple Silicon Macs.

## Build

The repository tracks source files and assets, not the compiled `.app` bundle or `.zip` package.

Build the standalone app locally with:

```bash
./scripts/build_app.zsh
```

The script keeps `.venv` for future development, bundles the Whisper `base` model from the local Hugging Face cache, signs the app ad-hoc, and creates:

```text
Arcane Whisperer.app
Arcane Whisperer.zip
```

For GitHub distribution, attach `Arcane Whisperer.zip` to a GitHub Release instead of committing it to the repository.

Security hardening notes live in [SECURITY.md](SECURITY.md). The build uses `requirements.lock.txt` when present so packaged releases are not rebuilt against surprise dependency versions.

## Launch

Recommended:

```bash
open -n "Arcane Whisperer.app"
```

You can also double-click `ArcaneWhisperer.command` or `Arcane Whisperer.app`.

The main voice backend uses local Whisper, which recognizes Italian and English in the same stream. The `base` model is bundled, so the first launch does not need to download it.

To choose a different model during development:

```bash
open -n "Arcane Whisperer.app" --args --backend whisper --whisper-model tiny
open -n "Arcane Whisperer.app" --args --backend whisper --whisper-model small
```

`tiny` is faster but less accurate; `small` is more accurate but heavier.

The Apple Speech backend is still available as a fallback. It must be launched from the app bundle: if you run `SpellAudio.py` directly, macOS does not provide the privacy description required for Speech Recognition permission.

Bilingual Apple Speech fallback:

```bash
open -n "Arcane Whisperer.app" --args --backend speech --locales it-IT,en-US
```

Force a single language:

```bash
open -n "Arcane Whisperer.app" --args --backend speech --locale en-US
open -n "Arcane Whisperer.app" --args --backend speech --locale it-IT
```

Direct development fallback:

```bash
.venv/bin/python SpellAudio.py --backend command
```

On first launch, macOS may ask for two permissions: `Microphone` and `Speech Recognition`. The app stays visible in the Dock and menu bar; use `Quit Arcane Whisperer` to close it.

If the app gets stuck or cannot be closed from the menu:

```bash
./ArcaneWhisperer.command stop
```

## Test Without Microphone

```bash
"Arcane Whisperer.app/Contents/MacOS/Arcane Whisperer" --simulate "fireball"
"Arcane Whisperer.app/Contents/MacOS/Arcane Whisperer" --simulate "palla di fuoco"
```

To see live transcriptions while testing, start the app from the terminal with debug mode:

```bash
./ArcaneWhisperer.command debug
```

With Whisper, the terminal prints lines like `TRANSCRIBED [it 0.92]: palla di fuoco` or `TRANSCRIBED [en 0.95]: fireball`.

## Add Spells

Edit `spells.json`. Each spell can have Italian names, English names, and aliases:

```json
{
  "id": "example",
  "name": "Visible Name",
  "names": { "it": "Nome Italiano", "en": "English Name" },
  "aliases": ["alternate name", "alternate pronunciation"],
  "level": "1st Level",
  "school": "Abjuration",
  "casting_time": "1 action",
  "range": "60 feet",
  "components": "V, S",
  "duration": "1 minute",
  "source": "Your source",
  "description": "Text shown in the overlay."
}
```

Only put content in the JSON that you can use and redistribute.

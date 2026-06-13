#!/bin/zsh
cd "$(dirname "$0")"

if [ "$1" = "stop" ] || [ "$1" = "kill" ]; then
  pkill -f "Arcane Whisperer.app/Contents/MacOS/Arcane Whisperer" 2>/dev/null || true
  pkill -f "Arcane Whisperer.app/Contents/MacOS/ArcaneWhisperer" 2>/dev/null || true
  pkill -f "SpellAudio.py" 2>/dev/null || true
  exit 0
fi

if [ "$1" = "debug" ] || [ "$1" = "transcript" ]; then
  shift
  echo "Arcane Whisperer debug mode. Press Ctrl+C to quit."
  echo "Printing every phrase transcribed by Whisper."
  exec "Arcane Whisperer.app/Contents/MacOS/Arcane Whisperer" --backend whisper --debug "$@"
fi

open -n "Arcane Whisperer.app"

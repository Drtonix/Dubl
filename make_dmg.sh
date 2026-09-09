#!/bin/zsh
# Образ для установки: приложение и ярлык «Программы». После build_app.sh.
set -e
cd "${0:A:h}"
OUT="$PWD/build"
DMG="$OUT/Dubl.dmg"

[ -d "$OUT/Dubl.app" ] || { echo "Сначала ./build_app.sh"; exit 1; }

say() { print -P "%F{green}==>%f $*"; }

say "сборка образа"
rm -f "$DMG"
PY=./.venv/bin/python
[ -x "$PY" ] || PY=python3
"$PY" -m dmgbuild -s dmg_settings.py Dubl "$DMG"

say "проверка образа"
# ditto молча обрывает копирование, когда том мал: сверяем, что внутри лежит
# столько же, сколько собрано.
hdiutil attach -nobrowse -quiet "$DMG"
HAVE=$(du -sk "$OUT/Dubl.app" | cut -f1)
GOT=$(du -sk "/Volumes/Dubl/Dubl.app" | cut -f1)
hdiutil detach /Volumes/Dubl -quiet
if [ "$GOT" -lt $(( HAVE * 99 / 100 )) ]; then
    echo "в образ попало $GOT КБ из $HAVE КБ — увеличьте size в dmg_settings.py"
    exit 1
fi

say "готово: $(du -sh "$DMG" | cut -f1)  ->  $DMG"

#!/bin/sh
# usage: install.sh <editable-flag or ""> <extras> <spacy-model or "">
set -eu
EDITABLE="$1"; EXTRAS="$2"; SPACY_MODEL="$3"
case ",$EXTRAS," in
  *,model,*) uv pip install torch --extra-index-url https://download.pytorch.org/whl/cpu ;;
esac
if [ -n "$EXTRAS" ]; then uv pip install $EDITABLE ".[$EXTRAS]"; else uv pip install $EDITABLE .; fi
if [ -n "$SPACY_MODEL" ]; then
  uv pip install pip
  python -m spacy download "$SPACY_MODEL"
fi

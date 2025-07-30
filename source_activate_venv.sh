#!/bin/bash

# AlERT: source this script, don't run it directly.
# source activate_venv.sh

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "This script must be sourced, not run directly."
  echo "source activate_venv.sh"
  exit 1
fi

# rest of your script here
echo "Script is being sourced. Continuing..."
source ./.venv/bin/activate

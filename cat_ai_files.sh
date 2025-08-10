#!/bin/bash

# Get sub-directory name from command-line argument
sub_dir="$1"

# Check if the directory is provided
if [ -z "$sub_dir" ]; then
    echo "Error: No sub-directory provided. Usage: $0 <sub-directory>"
    exit 1
fi

# Check if the directory exists
if [ ! -d "$sub_dir" ]; then
    echo "Error: Directory '$sub_dir' not found."
    exit 1
fi

# Recursively iterate through the sub-directory
find "$sub_dir" -type d | while read dir; do
    # Skip if any component in the full path is exactly "node_modules", "documents", or "uploads"
    if [[ "$dir" =~ (^|/)(node_modules|.npm|.venv|dist|lib64|var|__pycache__)($|/) ]]; then
        continue
    fi

    # Skip any sub-directory inside a backend/python or dist/assets directory.
    # This will skip directories whose path contains "/backend/python/"

    if [[ "$dir" =~ (^|/)intelaide-backend/python/.+ ]]; then
        continue
    fi

    # If the directory is exactly a backend/python directory, include .py files.
    # (This regex matches directories ending with "backend/python" exactly.)
    if [[ "$dir" =~ (^|/)intelaide-backend/python$ ]]; then
        files=$(find "$dir" -maxdepth 1 -type f \( -name "*.jsx" -o -name "*.css" -o -name "*.js" -o -name "*.json" -o -name "*.py" \) ! -name "package-lock.json")
    else
        files=$(find "$dir" -maxdepth 1 -type f \( -name "*.py" -o -name "*.conf" -o -name "*.csv" -o -name "*.sh" -o -name "*.css" -o -name "*.service" -o -name "*.json" \) ! -name "package-lock.json" ! -name "cat_ai_files.sh")
    fi

    # If no files are found, skip to the next directory
    if [ -z "$files" ]; then
        continue
    fi

    # Print directory and file listing
    echo "====================================="
    echo "Directory: $dir"
    echo ""
    echo "Files found:"
    echo "$files" | awk -F'/' '{print $NF}'
    echo "====================================="

    # Iterate through each file and print its content
    for file in $files; do
        echo ""
        echo "-------------------------------------"
        echo "File: $(basename "$file")"
        echo "-------------------------------------"
        cat "$file"
        echo ""
    done
done

#!/bin/bash
set -e

# Setup dummy repo
TEST_DIR="test_repo"
rm -rf "$TEST_DIR"
mkdir "$TEST_DIR"
cd "$TEST_DIR"
git init
git config user.email "you@example.com"
git config user.name "Your Name"

# Commit 1
mkdir src doc
touch src/main.py doc/readme.md
git add .
git commit -m "Initial commit"
BASE_SHA=$(git rev-parse HEAD)

# Commit 2
touch src/utils.py
echo "change" > src/main.py
git add .
git commit -m "Add utils and modify main"
REF_SHA=$(git rev-parse HEAD)

# Run main.py
echo "Running main.py..."
export INPUT_FILTERS='{"src": ["src/**"], "doc": ["doc/**"]}'
export INPUT_BASE="$BASE_SHA"
export INPUT_REF="$REF_SHA"
export INPUT_LIST_FILES="csv"
export GITHUB_OUTPUT="output.txt"

# Copy main.py to test dir or run from parent
python3 ../main.py

echo "Checking output..."
cat output.txt

# Assertions
grep "src=true" output.txt || (echo "FAILED: src should be true" && exit 1)
grep "doc=false" output.txt || (echo "FAILED: doc should be false" && exit 1)
grep "src_files=src/main.py,src/utils.py" output.txt || (echo "FAILED: src_files incorrect" && exit 1)

echo "VERIFICATION PASSED"
cd ..
rm -rf "$TEST_DIR"

#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

if [ -z "$1" ]; then
  echo "Error: VERSION argument is required."
  echo "Usage: $0 VERSION  (e.g. $0 0.1.0)"
  exit 1
fi
VERSION="$1"
TAG="v${VERSION}"

BRANCH="$(git branch --show-current)"
if [ "$BRANCH" != "main" ]; then
  echo "Error: Must be on main branch to publish. Current branch: $BRANCH"
  exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "Error: Working tree has uncommitted changes. Commit or stash them before publishing."
  exit 1
fi

if git rev-parse "$TAG" &>/dev/null; then
  echo "Error: Tag $TAG already exists. Choose a different version or delete the tag:"
  echo "  Local:  git tag -d $TAG"
  echo "  Remote: git push origin --delete $TAG"
  exit 1
fi

echo "Creating tag $TAG..."
git tag "$TAG"

echo "Building package with uv..."
uv build

echo "Publishing to PyPI with twine..."
uv run --with twine twine upload dist/*

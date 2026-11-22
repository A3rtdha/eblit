"""PyInstaller entry. Must not live as app/__main__.py — that file becomes a script without a package."""

from app.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())

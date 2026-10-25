# audio-zones-delay — agent instructions

## Language

Everything in this repo is written in English: code, identifiers, comments,
docs, commit messages, branch names, issues and pull requests. This holds even
when the conversation with the owner happens in another language.

## Commands

| Command | Purpose |
| --- | --- |
| `uv sync` | Install dependencies into `.venv` |
| `uv run pytest` | Run the Python tests |
| `uv run azd serve` | Serve the player page on `127.0.0.1` |
| `uv run azd analyze <session-dir> <recording>` | Analyze a recording |
| `node --test "tests/js/*.test.mjs"` | Run the JS tests (Node ≥ 20 on PATH, e.g. via nvm) |

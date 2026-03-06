# Contributing to ARAM Oracle

Thanks for your interest in contributing! This guide covers how to set up the project locally, our coding conventions, and how to submit changes.

## Development Setup

### Prerequisites

- Python 3.11+
- Git
- Tesseract OCR *(optional, for OCR-related development)*

### Clone and Install

```bash
git clone https://github.com/fabs133/league-aram-builder.git
cd league-aram-builder
pip install -e ".[dev]"
```

This installs the project in editable mode with test dependencies (pytest, pytest-asyncio, httpx, pyinstaller).

### Running Tests

```bash
python -m pytest tests/ -q
```

All 104 tests should pass. Tests mock the game API so no running League client is needed.

### Running the Server

```bash
python -m backend.main
```

Open `http://localhost:8765/overlay` for the companion UI. The server polls the Live Client Data API and pushes updates via WebSocket.

## Project Structure

```
backend/
  api/server.py         -- FastAPI server, WebSocket, poll loop state machine
  collectors/           -- Data ingestion (LCDA game API, OCR screen capture)
  engine/               -- Pure scoring functions (no I/O)
    scoring.py          -- 12D stat vector dot-product scoring
    ranker.py           -- Augment ranking and reroll advice
    augment_detector.py -- Stat-delta cosine similarity matching
    build_suggester.py  -- Item build path projection
  static_data/loader.py -- Champion/augment/item data loading from APIs
  storage/db.py         -- SQLite personal winrate tracking
  workflow/pipeline.py  -- Orchestrates engine calls
frontend/               -- Vanilla HTML/CSS/JS overlay UI
tests/                  -- pytest test suite
data/                   -- Champions JSON, augment overrides, scaling specs
```

## Coding Conventions

### Style

- **Type hints** on all function signatures
- **Dataclasses** for data models (see `backend/models.py`)
- **Pure functions** in the engine layer -- no I/O, no side effects
- **asyncio.Lock** for shared mutable state in the server
- No external formatters enforced yet -- just keep consistent with surrounding code

### Architecture Rules

- Engine modules (`backend/engine/`) must never import from `backend/api/` or `backend/collectors/`
- All game state mutations happen through `GameState` methods under the lock
- OCR/thread-pool functions must be pure -- return data, let the caller mutate state

### Commit Messages

- Use imperative mood: "Add feature" not "Added feature"
- Keep the first line under 72 characters
- Reference issue numbers when applicable: "Fix augment scoring for tanks (#12)"

## Submitting Changes

### Issues

- Check existing issues before creating a new one
- Use the provided issue templates (bug report, feature request)
- Include system info for bugs (Python version, OS, screen resolution)

### Pull Requests

1. Fork the repo and create a feature branch from `master`
2. Make your changes with tests where applicable
3. Run `python -m pytest tests/ -q` and ensure all tests pass
4. Fill out the PR template
5. Keep PRs focused -- one feature or fix per PR

### What We're Looking For

- Bug fixes with regression tests
- New augment/champion data contributions (`data/champions/`, `data/augments/`)
- OCR accuracy improvements
- Scoring model refinements (with before/after comparisons)
- Documentation improvements

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Questions?

Open a [discussion](https://github.com/fabs133/league-aram-builder/issues) or reach out via an issue tagged `question`.

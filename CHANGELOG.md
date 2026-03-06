# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-03-06

### Added

- 12-dimensional stat vector scoring engine with role weights and synergy multipliers
- Augment ranking with overlap penalties, CC-CDR bonuses, and enemy comp awareness
- Scaling spec system for indirect/proc-based augments (on-hit, stacking, threshold)
- OCR-based augment detection using Tesseract with perceptual image hashing
- Stat-delta matching via cosine similarity to auto-detect chosen augments
- Item build path suggestions adapting to active augments and current gold
- Reroll advisor comparing best option against champion ceiling score
- FastAPI server with WebSocket push updates and REST endpoints
- Poll loop state machine for augment pick window lifecycle
- SQLite personal winrate tracking per champion per augment
- Vanilla HTML/CSS/JS overlay frontend (320px dark theme)
- PyQt6 and pywebview desktop overlay options (click-through)
- Champion data with CC profiles (100+ champions)
- Augment data from CommunityDragon cherry-augments.json (517 augments)
- Manual augment overrides and name-based stat hints
- Screenshot saving with OCR annotation for debugging
- Diagnostics collector with ring-buffer error/log/WS message tracking
- Bug report generation (local JSON + optional GitHub issue)
- TOML configuration file support (~/.aram-oracle/config.toml)
- PyInstaller packaging support
- 104 unit and integration tests

### Fixed

- Thread-safety: OCR helper functions no longer mutate shared state outside the lock
- Path traversal protection on screenshot serving endpoint
- Deprecated `datetime.utcnow()` replaced with `datetime.now(timezone.utc)`

### Changed

- Bug report endpoint rate-limited to one report per 30 seconds
- Health endpoint now exposes augment/item/champion load counts
- Startup logs warning when critical data (augments, champions, items) fails to load

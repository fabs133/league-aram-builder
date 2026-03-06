"""
ARAM Oracle — Screen OCR Augment Detection

Captures a screenshot of the augment selection area, runs OCR,
and fuzzy-matches detected text against known augment names.

Uses perceptual image hashing for cheap change detection:
- After a successful OCR scan, the region hash is stored.
- On subsequent ticks, only the hash is recomputed (fast).
- If the hash changes significantly, a reroll happened and OCR re-runs.

Screenshots are saved persistently to data/screenshots/ for debugging.

Requires Tesseract OCR installed:
  Windows: winget install UB-Mannheim.TesseractOCR
  Or download from: https://github.com/UB-Mannheim/tesseract/wiki
"""
import hashlib
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger("aram-oracle.ocr")

# App root for resolving data paths (PyInstaller sets sys._MEIPASS)
_APP_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))

try:
    import mss
    import pytesseract
    from PIL import Image, ImageFilter, ImageEnhance, ImageOps, ImageDraw, ImageFont
    from rapidfuzz import fuzz, process

    OCR_AVAILABLE = True
except ImportError as e:
    OCR_AVAILABLE = False
    logger.warning("OCR dependencies not installed: %s", e)

# Default Tesseract path on Windows (UB-Mannheim installer)
# Override with TESSERACT_PATH env var if Tesseract is installed elsewhere.
import os as _os

_DEFAULT_TESS_WIN = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
_tess_path = _os.environ.get("TESSERACT_PATH", _DEFAULT_TESS_WIN)
if OCR_AVAILABLE and Path(_tess_path).exists():
    pytesseract.pytesseract.tesseract_cmd = _tess_path


# -- Paths --
SCREENSHOT_DIR = _APP_ROOT / "data" / "screenshots"

# -- Screen regions --
# Region as fractions of screen: (left%, top%, right%, bottom%)
AUGMENT_REGION_16_9 = (0.15, 0.22, 0.85, 0.50)
AUGMENT_REGION_21_9 = (0.24, 0.22, 0.76, 0.50)  # Ultrawide letterboxed
AUGMENT_REGION_16_10 = (0.15, 0.20, 0.85, 0.48)

# Legacy alias for backwards compatibility
AUGMENT_REGION = AUGMENT_REGION_16_9

# Minimum fuzzy match score to accept (0-100)
MATCH_THRESHOLD = 65

# Minimum text length to even attempt matching
MIN_TEXT_LEN = 3

# Max screenshots to keep (oldest get cleaned up)
MAX_SCREENSHOTS = 50

# Perceptual hash size (NxN grid). Higher = more sensitive to small changes.
HASH_SIZE = 16

# Hamming distance threshold: if distance > this, the image changed (reroll).
# With HASH_SIZE=16, total bits = 256. Threshold ~30 means ~12% difference.
HASH_CHANGE_THRESHOLD = 30


_logged_resolution = False


def get_augment_region(screen_width: int, screen_height: int) -> tuple[float, float, float, float]:
    """Return the augment screen region adjusted for aspect ratio."""
    # Check config override first
    try:
        from backend.config import config
        override = config.get("ocr_region")
        if override and len(override) == 4:
            return tuple(override)
    except Exception:
        pass

    ratio = screen_width / screen_height if screen_height > 0 else 1.78

    if ratio >= 2.2:       # 21:9 ultrawide (2.33)
        return AUGMENT_REGION_21_9
    elif ratio >= 1.55:    # 16:9 (1.78) and 16:10 (1.6)
        return AUGMENT_REGION_16_9
    else:                  # 4:3 or other
        return AUGMENT_REGION_16_9


# -- Perceptual hashing --


def _perceptual_hash(img: "Image.Image") -> str:
    """Compute a perceptual hash (average hash) of an image.

    Resizes to a small grid, converts to grayscale, and compares each pixel
    to the mean. Returns a hex string. Fast (~1ms).
    """
    small = img.resize((HASH_SIZE, HASH_SIZE), Image.LANCZOS).convert("L")
    pixels = list(small.getdata())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if p > avg else "0" for p in pixels)
    # Convert to hex for compact storage
    return hex(int(bits, 2))[2:].zfill(HASH_SIZE * HASH_SIZE // 4)


def _hamming_distance(hash1: str, hash2: str) -> int:
    """Count differing bits between two hex hash strings."""
    if len(hash1) != len(hash2):
        return HASH_SIZE * HASH_SIZE  # max distance if incompatible
    val1 = int(hash1, 16)
    val2 = int(hash2, 16)
    xor = val1 ^ val2
    return bin(xor).count("1")


class ScreenWatcher:
    """Stateful screen watcher that uses hashing to detect augment changes.

    Usage in the poll loop:
        watcher = ScreenWatcher()

        # Each tick:
        action = watcher.check(augment_names)
        # action is one of:
        #   ("detected", matches)  — first detection or reroll detected, OCR ran
        #   ("unchanged", None)    — same augments still showing, no action needed
        #   ("no_augments", None)  — no augment UI detected on screen
        #   ("disappeared", None)  — augments were showing but are now gone (player chose)
        #   ("unavailable", None)  — OCR not ready
    """

    def __init__(self) -> None:
        self._frozen_hash: str | None = None  # hash after successful detection
        self._last_detected: list[tuple[str, str, int]] = []
        self._no_augment_hash: str | None = None  # hash of "normal gameplay" screen
        self._had_detection: bool = False  # True after augments were successfully detected
        self._disappear_confirm: int = 0   # consecutive ticks with no augments after detection

    def reset(self) -> None:
        """Reset state (e.g., when game ends or augment confirmed)."""
        self._frozen_hash = None
        self._last_detected = []
        self._no_augment_hash = None
        self._had_detection = False
        self._disappear_confirm = 0

    def check(
        self,
        augment_names: dict[str, str],
        monitor_index: int = 1,
        save: bool = True,
    ) -> tuple[str, list[tuple[str, str, int]] | None]:
        """Check the screen for augment changes.

        Returns:
            Tuple of (action, matches_or_none).
        """
        if not is_available():
            return ("unavailable", None)

        # Capture the augment region (fast, ~5-10ms)
        img = capture_augment_region(monitor_index)
        if img is None:
            return ("unavailable", None)

        current_hash = _perceptual_hash(img)

        # Case 1: No prior detection — this is the first scan
        if self._frozen_hash is None:
            # Store hash even if OCR fails, so subsequent checks can
            # detect when the screen changes (augments appearing).
            self._frozen_hash = current_hash
            return self._run_full_ocr(img, current_hash, augment_names, save)

        # Case 2: Compare hash to frozen reference
        distance = _hamming_distance(current_hash, self._frozen_hash)

        if distance <= HASH_CHANGE_THRESHOLD:
            # Screen looks the same — augments unchanged
            return ("unchanged", None)

        # Case 3: Hash changed significantly — reroll detected
        logger.info(
            "Screen changed (hamming distance=%d, threshold=%d) — reroll, rescanning",
            distance, HASH_CHANGE_THRESHOLD,
        )
        if save:
            save_screenshot(img, label="reroll_detected")

        # Reset disappear counter — this is a reroll, not a disappearance
        self._disappear_confirm = 0
        # Update frozen hash so next check compares against the new screen
        self._frozen_hash = current_hash

        return self._run_full_ocr(img, current_hash, augment_names, save)

    def _run_full_ocr(
        self,
        img: "Image.Image",
        img_hash: str,
        augment_names: dict[str, str],
        save: bool,
    ) -> tuple[str, list[tuple[str, str, int]] | None]:
        """Run full OCR pipeline and update frozen hash."""
        texts = extract_text(img)

        if not texts:
            if save:
                save_screenshot(img, label="no_text")
            # No text found — check if augments just disappeared
            if self._had_detection:
                self._disappear_confirm += 1
                if self._disappear_confirm >= 2:
                    # Confirmed: augments were showing, now gone = player chose
                    logger.info(
                        "Augment UI disappeared (confirmed after %d ticks)",
                        self._disappear_confirm,
                    )
                    self._disappear_confirm = 0
                    return ("disappeared", None)
                return ("unchanged", None)  # wait for confirmation tick
            return ("no_augments", None)

        # Text found — reset disappear counter (augments are still on screen)
        self._disappear_confirm = 0

        matches = match_augments(texts, augment_names)

        if save:
            save_screenshot(img, label="ocr", ocr_texts=texts, matches=matches)

        if matches:
            self._frozen_hash = img_hash
            self._last_detected = matches
            self._had_detection = True
            logger.info(
                "Detected augments: %s",
                [(name, score) for _, name, score in matches],
            )
            return ("detected", matches)

        # OCR found text but no augment name matches.
        # If we previously had a detection, this likely means a reroll
        # showed new augments that OCR couldn't fuzzy-match. Keep trying
        # rather than declaring "disappeared".
        if self._had_detection:
            logger.info(
                "OCR found text but no augment matches — retrying next tick "
                "(found: %s)",
                texts[:5],
            )
            return ("unchanged", None)

        return ("no_augments", None)

    @property
    def last_detected(self) -> list[tuple[str, str, int]]:
        return list(self._last_detected)

    @property
    def has_detection(self) -> bool:
        return self._frozen_hash is not None


# -- Module-level singleton --
watcher = ScreenWatcher()


# -- Standalone functions (unchanged API for backwards compat) --


def is_available() -> bool:
    """Check if OCR system is ready."""
    if not OCR_AVAILABLE:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except (OSError, ImportError) as e:
        logger.debug("Tesseract not available: %s", e)
        return False


def _ensure_screenshot_dir() -> Path:
    """Create screenshot directory if needed, clean old files."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    pngs = sorted(SCREENSHOT_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime)
    while len(pngs) > MAX_SCREENSHOTS:
        oldest = pngs.pop(0)
        try:
            oldest.unlink()
        except OSError:
            pass

    return SCREENSHOT_DIR


def capture_full_screen(monitor_index: int = 1) -> "Image.Image | None":
    """Capture the entire screen."""
    if not OCR_AVAILABLE:
        return None

    try:
        with mss.mss() as sct:
            monitors = sct.monitors
            if monitor_index >= len(monitors):
                monitor_index = 1
            mon = monitors[monitor_index]

            screenshot = sct.grab(mon)
            return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
    except (OSError, ValueError) as e:
        logger.error("Full screen capture failed: %s", e)
        return None


def capture_augment_region(monitor_index: int = 1) -> "Image.Image | None":
    """Capture the augment selection area of the screen."""
    global _logged_resolution
    if not OCR_AVAILABLE:
        return None

    try:
        with mss.mss() as sct:
            monitors = sct.monitors
            if monitor_index >= len(monitors):
                monitor_index = 1
            mon = monitors[monitor_index]

            w = mon["width"]
            h = mon["height"]

            region_fracs = get_augment_region(w, h)

            if not _logged_resolution:
                logger.info(
                    "Screen: %dx%d, aspect=%.2f, region=%s",
                    w, h, w / h if h > 0 else 0, region_fracs,
                )
                _logged_resolution = True

            region = {
                "left": mon["left"] + int(w * region_fracs[0]),
                "top": mon["top"] + int(h * region_fracs[1]),
                "width": int(w * (region_fracs[2] - region_fracs[0])),
                "height": int(h * (region_fracs[3] - region_fracs[1])),
            }

            screenshot = sct.grab(region)
            return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
    except (OSError, ValueError) as e:
        logger.error("Screen capture failed: %s", e)
        return None


def save_screenshot(
    img: "Image.Image",
    label: str = "",
    ocr_texts: list[str] | None = None,
    matches: list[tuple[str, str, int]] | None = None,
) -> Path | None:
    """Save a screenshot with optional OCR annotation for debugging."""
    if not OCR_AVAILABLE:
        return None

    try:
        out_dir = _ensure_screenshot_dir()
        ts = int(time.time())
        prefix = f"{label}_" if label else ""
        filename = f"{prefix}{ts}.png"

        annotated = img.copy()
        if ocr_texts or matches:
            draw = ImageDraw.Draw(annotated)
            y = 5
            try:
                font = ImageFont.truetype("arial.ttf", 14)
            except OSError:
                font = ImageFont.load_default()

            if matches:
                for aug_id, name, score in matches:
                    text = f"MATCH: {name} ({score}%)"
                    draw.text((5, y), text, fill=(0, 255, 0), font=font)
                    y += 18

            if ocr_texts:
                draw.text((5, y), "--- OCR lines ---", fill=(255, 255, 0), font=font)
                y += 18
                for line in ocr_texts[:15]:
                    draw.text((5, y), line, fill=(255, 255, 255), font=font)
                    y += 16

        path = out_dir / filename
        annotated.save(str(path), "PNG")
        logger.info("Screenshot saved: %s", path)
        return path
    except OSError as e:
        logger.error("Failed to save screenshot: %s", e)
        return None


def preprocess_for_ocr(img: "Image.Image") -> "Image.Image":
    """Enhance screenshot for better OCR accuracy on game UI."""
    w, h = img.size
    if w < 1500:
        img = img.resize((w * 2, h * 2), Image.LANCZOS)

    gray = img.convert("L")

    enhancer = ImageEnhance.Contrast(gray)
    gray = enhancer.enhance(2.5)

    gray = gray.filter(ImageFilter.SHARPEN)

    pixels = list(gray.getdata())
    avg = sum(pixels) / len(pixels) if pixels else 128
    if avg < 128:
        gray = ImageOps.invert(gray)

    return gray


def extract_text(img: "Image.Image") -> list[str]:
    """Run OCR on preprocessed image and return candidate text lines."""
    if not OCR_AVAILABLE:
        return []

    processed = preprocess_for_ocr(img)

    try:
        raw = pytesseract.image_to_string(
            processed,
            lang="eng",
            config="--psm 6 --oem 3",
        )
    except (OSError, RuntimeError) as e:
        logger.error("OCR failed: %s", e)
        return []

    lines = []
    for line in raw.split("\n"):
        cleaned = line.strip()
        if len(cleaned) >= MIN_TEXT_LEN and any(c.isalpha() for c in cleaned):
            lines.append(cleaned)

    return lines


def match_augments(
    ocr_texts: list[str],
    augment_names: dict[str, str],
    threshold: int | None = None,
) -> list[tuple[str, str, int]]:
    """Fuzzy-match OCR text against known augment names."""
    if not OCR_AVAILABLE or not ocr_texts or not augment_names:
        return []

    if threshold is None:
        try:
            from backend.config import config
            threshold = config.get("match_threshold", MATCH_THRESHOLD)
        except Exception:
            threshold = MATCH_THRESHOLD

    name_to_id: dict[str, str] = {name: aid for aid, name in augment_names.items()}
    all_names = list(name_to_id.keys())

    matches: dict[str, tuple[str, int]] = {}

    for text in ocr_texts:
        result = process.extractOne(
            text,
            all_names,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=threshold,
        )
        if result:
            matched_name, score, _ = result
            aug_id = name_to_id[matched_name]
            if aug_id not in matches or score > matches[aug_id][1]:
                matches[aug_id] = (matched_name, int(score))

        words = text.split()
        for i in range(len(words)):
            for j in range(i + 1, min(i + 5, len(words) + 1)):
                fragment = " ".join(words[i:j])
                if len(fragment) < MIN_TEXT_LEN:
                    continue
                result = process.extractOne(
                    fragment,
                    all_names,
                    scorer=fuzz.token_sort_ratio,
                    score_cutoff=max(threshold, 70),
                )
                if result:
                    matched_name, score, _ = result
                    aug_id = name_to_id[matched_name]
                    if aug_id not in matches or score > matches[aug_id][1]:
                        matches[aug_id] = (matched_name, int(score))

    sorted_matches = sorted(
        [(aid, name, score) for aid, (name, score) in matches.items()],
        key=lambda x: x[2],
        reverse=True,
    )

    return sorted_matches[:3]


def detect_augments(
    augment_names: dict[str, str],
    monitor_index: int = 1,
    save: bool = True,
) -> list[tuple[str, str, int]]:
    """Full pipeline: capture screen -> OCR -> match augments.

    For poll-loop usage, prefer ScreenWatcher.check() instead — it uses
    hashing to avoid redundant OCR calls.
    """
    if not is_available():
        logger.warning("OCR not available — Tesseract installed?")
        return []

    if save:
        full = capture_full_screen(monitor_index)
        if full:
            save_screenshot(full, label="full")

    img = capture_augment_region(monitor_index)
    if img is None:
        return []

    texts = extract_text(img)

    if not texts:
        if save and img:
            save_screenshot(img, label="region_no_text")
        logger.debug("No text found in screenshot")
        return []

    logger.debug("OCR found %d text lines: %s", len(texts), texts[:10])

    matches = match_augments(texts, augment_names)

    if save:
        save_screenshot(img, label="region", ocr_texts=texts, matches=matches)

    if matches:
        logger.info(
            "Detected augments: %s",
            [(name, score) for _, name, score in matches],
        )

    return matches

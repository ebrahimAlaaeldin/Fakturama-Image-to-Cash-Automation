"""Runtime settings, read from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    groq_api_key: str = field(default_factory=lambda: os.environ.get("GROQ_API_KEY", ""))
    groq_model: str = field(default_factory=lambda: os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"))
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # OCR
    ocr_min_width: int = 1400  # images narrower than this are upscaled before OCR
    ocr_min_confidence: float = 0.80

    # Fakturama / UIA
    fakturama_exe: str = field(default_factory=lambda: os.environ.get("FAKTURAMA_EXE", ""))
    main_window_title_re: str = ".*Fakturama.*"
    default_timeout: float = 15.0
    poll_interval: float = 0.15
    stable_polls: int = 3  # list must be unchanged this many polls in a row to count as "stable"

    runs_dir: Path = Path("runs")


settings = Settings()

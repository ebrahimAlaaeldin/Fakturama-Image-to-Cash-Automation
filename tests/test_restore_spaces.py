"""OCR sometimes drops a word space ('BankTransfer'); restore it from the pixel gaps."""

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from fakturama_i2c.vision.ocr import restore_word_spaces


def crop_of(printed: str, size: int = 26) -> np.ndarray:
    try:
        font = ImageFont.truetype("segoeui.ttf", size)
    except OSError:
        pytest.skip("Segoe UI not available")
    img = Image.new("L", (16 * len(printed) + 20, size + 12), 235)
    ImageDraw.Draw(img).text((8, 2), printed, fill=30, font=font)
    return np.asarray(img).astype(np.int16)


@pytest.mark.parametrize("printed, ocr", [
    ("Bank Transfer", "BankTransfer"),
    ("Office Guide Vol. 2", "Office Guide Vol.2"),
    ("Credit Card", "CreditCard"),
])
def test_lost_space_is_restored(printed, ocr):
    assert restore_word_spaces(ocr, crop_of(printed)) == printed


@pytest.mark.parametrize("printed", ["Bank Transfer", "Ergonomic Desk Chair", "Friedrichstrasse 88",
                                     "Northstar Office GmbH", "Anti-Fatigue Desk Mat"])
def test_correct_text_is_unchanged(printed):
    assert restore_word_spaces(printed, crop_of(printed)) == printed


@pytest.mark.parametrize("printed", ["CHR-ERG-01", "WEB-2026-0714-A17", "marta.klein@example.test", "1,250.00",
                                     "Friedrichstrasse"])
def test_never_touches_codes_numbers_or_single_words(printed):
    assert restore_word_spaces(printed, crop_of(printed)) == printed

import json
from pathlib import Path

import pytest

from fakturama_i2c.extraction.normalize import to_order
from fakturama_i2c.models import RawOrder

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def raw_order() -> RawOrder:
    return RawOrder.model_validate(json.loads((FIXTURES / "sample_raw_order.json").read_text()))


@pytest.fixture
def order(raw_order):
    return to_order(raw_order)

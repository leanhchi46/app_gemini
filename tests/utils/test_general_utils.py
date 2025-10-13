import pytest

from APP.utils import general_utils


def test_extract_symbol_basic():
    assert general_utils.extract_symbol_from_filename("plan_XAUUSD_h4.png") == "XAUUSD"


def test_guess_symbol_majority():
    filenames = [
        "eurusd-analysis.png",
        "EURUSD_plan.jpg",
        "setup_gbpusd.png",
    ]
    symbol, stats = general_utils.guess_symbol_from_filenames(filenames)
    assert symbol == "EURUSD"
    assert stats == {"EURUSD": 2, "GBPUSD": 1}


def test_guess_symbol_combines_split_tokens():
    symbol, stats = general_utils.guess_symbol_from_filenames(["xau_usd-entry-h1.jpeg"])
    assert symbol == "XAUUSD"
    assert stats[symbol] == 1


def test_guess_symbol_handles_index_with_digits():
    symbol, _ = general_utils.guess_symbol_from_filenames(["us30-trade.png"])
    assert symbol == "US30"


def test_guess_symbol_returns_none_when_no_candidates():
    symbol, stats = general_utils.guess_symbol_from_filenames(["Screenshot 2024-01-01.png"])
    assert symbol is None
    assert stats == {}


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("XAUUSDm15.png", "XAUUSD"),
        ("xauusd20240101.jpg", "XAUUSD"),
        ("analysis_eurusd_m30.png", "EURUSD"),
    ],
)
def test_extract_symbol_handles_suffixes_and_digits(filename, expected):
    assert general_utils.extract_symbol_from_filename(filename) == expected

"""Guards for the README."""

from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_credits_data_sources():
    text = README.read_text(encoding="utf-8")
    assert "Open-Meteo" in text
    assert "CC BY 4.0" in text
    assert "ČHMÚ" in text

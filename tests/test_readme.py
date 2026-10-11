"""Guards for the README structure the pipeline relies on.

`mvd report --readme` (roadmap 3.1) rewrites only the text between the
leaderboard markers, so they must exist exactly once and in order.
"""

from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"
START = "<!-- LEADERBOARD:START -->"
END = "<!-- LEADERBOARD:END -->"


def test_leaderboard_markers_exist_once_and_in_order():
    text = README.read_text(encoding="utf-8")
    assert text.count(START) == 1
    assert text.count(END) == 1
    assert text.index(START) < text.index(END)


def test_readme_credits_data_sources():
    text = README.read_text(encoding="utf-8")
    assert "Open-Meteo.com" in text
    assert "CC BY 4.0" in text
    assert "ČHMÚ" in text

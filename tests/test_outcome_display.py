"""How a season's outcome is shown.

Colour is applied after the table is laid out, never before: the outcome is
the last column, so styling it cannot disturb the alignment of the columns
before it — and `display_width` would count escape codes as characters.
"""

import click

from football.cli_stats import display_outcome, style_outcome


def test_an_unchanged_season_shows_a_dash_not_a_word():
    """Sixty rows of "stayed" is noise; the eye wants the exceptions."""
    assert display_outcome("stayed") == "-"


def test_finishing_top_is_reported_as_winning_the_division():
    assert display_outcome("promoted", position=1) == "champions"
    assert display_outcome("stayed", position=1) == "champions"


def test_winning_the_top_flight_is_champions_without_a_promotion():
    assert display_outcome("stayed", position=1) == "champions"


def test_second_place_is_not_champions():
    assert display_outcome("promoted", position=2) == "promoted"


def test_runner_up_in_the_top_flight_is_marked():
    assert display_outcome("stayed", position=2, tier=1) == "runner-up"


def test_second_place_outside_the_top_flight_is_not_a_runner_up():
    """It is a promotion already, which is the fact worth naming there."""
    assert display_outcome("promoted", position=2, tier=2) == "promoted"
    assert display_outcome("promoted", position=2) == "promoted"


def test_runner_up_is_styled_distinctly():
    styled = style_outcome("2022-23 | premier-league | runner-up")
    assert click.style("runner-up", fg=252, bold=True) in styled


def test_champions_is_bright_green():
    styled = style_outcome("2010-11 | league-one | champions")
    assert click.style("champions", fg="bright_green", bold=True) in styled


def test_the_outcomes_that_matter_keep_their_words():
    assert display_outcome("promoted") == "promoted"
    assert display_outcome("relegated") == "relegated"
    assert display_outcome("promoted-via-play-offs") == "promoted-via-play-offs"
    assert display_outcome("current") == "current"


def test_promotion_is_bright_green():
    styled = style_outcome("1978-79 | division-two | promoted")
    assert click.style("promoted", fg="bright_green", bold=True) in styled


def test_promotion_via_the_play_offs_is_also_green():
    styled = style_outcome("2003-04 | x | promoted-via-play-offs")
    assert "bright_green" in _codes(styled) or "\x1b[92m" in styled


def test_relegation_is_red():
    styled = style_outcome("1982-83 | division-one | relegated")
    assert click.style("relegated", fg="red", bold=True) in styled


def test_a_dash_is_left_unstyled():
    line = "1990-91 | division-two | -"
    assert style_outcome(line) == line


def test_a_line_that_ends_in_something_else_is_untouched():
    line = "season | competition | outcome"
    assert style_outcome(line) == line


def test_promoted_is_not_matched_inside_promoted_via_play_offs():
    """Suffix matching must colour the whole outcome, not a fragment of it."""
    styled = style_outcome("2003-04 | x | promoted-via-play-offs")
    assert styled.endswith(
        click.style("promoted-via-play-offs", fg="bright_green", bold=True))


def _codes(text: str) -> str:
    return repr(text)

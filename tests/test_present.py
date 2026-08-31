from football.present import display_width, render_table


def test_display_width_counts_plain_text_as_its_length():
    assert display_width("Brighton") == 8


def test_display_width_ignores_combining_marks():
    assert display_width("Munchen") == display_width("München")


def test_display_width_counts_wide_glyphs_as_two_columns():
    assert display_width("サ") == 2


def test_render_table_pads_columns_to_the_widest_cell():
    output = render_table(["club", "goals"], [["Arsenal", 3], ["Brighton", 12]])
    lines = output.splitlines()
    assert lines[1].startswith("club")
    positions = {line.index("|") for line in lines if "|" in line}
    assert len(positions) == 1, "the separator must line up on every row"


def test_render_table_shows_none_as_empty_not_as_the_word_none():
    output = render_table(["attendance"], [[None]])
    assert "None" not in output


def test_render_table_aligns_when_a_name_carries_an_accent():
    output = render_table(["club"], [["Bayern Munchen"], ["Bayern München"]])
    widths = {display_width(line.rstrip()) for line in output.splitlines()[3:]}
    assert len(widths) == 1


def test_render_table_handles_no_rows():
    assert "club" in render_table(["club"], [])


def test_large_numbers_are_grouped_in_thousands():
    output = render_table(["played"], [[4791]])
    assert "4,791" in output


def test_small_numbers_are_unaffected():
    assert "1,0" not in render_table(["tier"], [[3]])
    assert render_table(["position"], [[22]]).endswith("22")


def test_strings_that_look_like_numbers_are_left_alone():
    """A season is "1982-83" and a slug may contain digits; neither is a count."""
    output = render_table(["season"], [["1982-83"]])
    assert "1,982" not in output and "1982-83" in output


def test_a_year_held_as_text_keeps_its_shape():
    assert "1,982" not in render_table(["year"], [["1982"]])


def test_grouping_does_not_break_alignment():
    output = render_table(["club", "played"], [["Arsenal", 4791], ["Brighton", 7]])
    positions = {line.index("|") for line in output.splitlines() if "|" in line}
    assert len(positions) == 1


def test_booleans_are_not_rendered_as_numbers():
    assert "True" in render_table(["neutral"], [[True]])


def test_decimals_are_left_as_they_arrive():
    """Percentages are already formatted by the caller."""
    assert "38.6" in render_table(["win %"], [["38.6"]])


def test_number_columns_are_set_flush_right():
    output = render_table(["played"], [[2713], [59]])
    assert output.splitlines()[3:] == [" 2,713", "    59"]


def test_number_headings_sit_over_the_right_edge():
    output = render_table(["won"], [[1636]])
    assert output.splitlines()[1] == "  won"


def test_negative_and_percentage_columns_count_as_numbers():
    output = render_table(["diff", "win %"], [["-325", "34.3"], ["22", "7.0"]])
    positions = {line.index("|") for line in output.splitlines() if "|" in line}
    assert len(positions) == 1
    assert output.splitlines()[4].startswith("  22")


def test_text_columns_keep_their_left_edge():
    output = render_table(["season"], [["1982-83"], ["2001-02"]])
    assert all(not line.startswith(" ") for line in output.splitlines())


def test_a_table_opens_with_a_blank_line():
    """The headings must not be mistaken for another line of prose."""
    assert render_table(["club"], [["Arsenal"]]).splitlines()[0] == ""


def test_a_caption_sits_directly_above_the_headings():
    """Inside the opening blank line, so it cannot drift from its table."""
    lines = render_table(["club"], [["Arsenal"]], caption="League").splitlines()
    assert lines[:3] == ["", "League", "club"]

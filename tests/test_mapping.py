"""Mapping details the conformance suite does not pin down."""

from yaft import (
    Feature,
    normalise_booleans,
    normalise_collection,
    normalise_feature,
    normalise_group,
)


def test_a_value_that_is_not_a_string_is_not_set() -> None:
    # A JSON boolean belongs in the boolean shape; in the feature shape it is
    # not coerced to "true", so the feature is off (R1, R4).
    assert normalise_feature({"key": "f", "value": True}).value == ""
    assert normalise_feature({"key": "f", "value": 1}).value == ""


def test_an_entry_whose_key_is_not_a_string_is_skipped() -> None:
    assert normalise_collection({"toggles": [{"key": 7, "value": "true"}]}) == {}


def test_tags_that_are_not_strings_are_dropped() -> None:
    feature = normalise_feature({"key": "f", "value": "true", "tags": ["ok", 42, None, "fine"]})
    assert feature.tags == ("ok", "fine")


def test_a_list_of_toggles_is_not_a_group() -> None:
    assert normalise_group([{"key": "f", "value": "true"}]) is None


def test_single_toggle_is_a_group() -> None:
    assert normalise_group({"key": "f", "value": "true"}) == {"f": Feature(key="f", value="true")}


def test_booleans_keep_only_booleans() -> None:
    assert normalise_booleans({"on": True, "off": False, "text": "true", "one": 1}) == {
        "on": True,
        "off": False,
    }
    assert normalise_booleans(None) == {}

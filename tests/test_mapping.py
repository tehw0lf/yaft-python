"""Mapping details the conformance suite does not pin down."""

from yaft import Feature, normalise_booleans, normalise_feature, normalise_group


def test_non_string_values_read_like_the_other_ports() -> None:
    # Go, Java and TypeScript all turn the JSON boolean true into "true".
    # Python's str(True) is "True", which would be off in this port alone.
    assert normalise_feature({"key": "f", "value": True}).value == "true"
    assert normalise_feature({"key": "f", "value": False}).value == "false"
    assert normalise_feature({"key": 7, "value": "true"}).key == "7"
    assert normalise_feature({"key": 7.0, "value": "true"}).key == "7"


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

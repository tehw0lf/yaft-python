"""The local providers."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from yaft import Feature, FeatureProvider, LocalBooleanProvider, LocalFeatureProvider


def fixed(instant: str) -> datetime:
    return datetime.fromisoformat(instant).astimezone(UTC)


def write(tmp_path: Path, content: object) -> Path:
    path = tmp_path / "features.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


def test_feature_provider_evaluates_against_its_clock() -> None:
    now = fixed("2026-09-18T12:00:00+00:00")
    provider = LocalFeatureProvider(
        {"f": Feature(key="f", value="true", active_at="2026-09-18T13:00:00Z")},
        clock=lambda: now,
    )
    assert not provider.is_enabled("f")
    now = fixed("2026-09-18T13:00:00+00:00")
    assert provider.is_enabled("f")
    assert not provider.is_enabled("missing")


def test_reads_the_keyed_file_format_of_yaft_ts(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        {
            "on": {"key": "on", "value": "true", "activeAt": "", "disabledAt": ""},
            "off": {"value": "false"},
            "stray": "not a feature",
        },
    )
    provider = LocalFeatureProvider.from_file(path)
    assert set(provider.data) == {"on", "off"}
    assert provider.is_enabled("on")
    assert not provider.is_enabled("off")


def test_reads_a_backend_response_from_a_file(tmp_path: Path) -> None:
    path = write(tmp_path, {"toggles": [{"Key": "uuid|a", "Value": "true"}]})
    assert LocalFeatureProvider.from_file(path).is_enabled("uuid|a")


def test_a_missing_file_raises(tmp_path: Path) -> None:
    # Starting with every feature off would hide the misconfiguration.
    with pytest.raises(FileNotFoundError):
        LocalFeatureProvider.from_file(tmp_path / "absent.json")
    with pytest.raises(FileNotFoundError):
        LocalBooleanProvider.from_file(tmp_path / "absent.json")


def test_load_keeps_the_data_when_the_body_is_not_a_group() -> None:
    provider = LocalFeatureProvider.from_response({"key": "f", "value": "true"})
    with pytest.raises(ValueError, match="not a toggle group"):
        provider.load({"error": "Bad Gateway"})
    assert provider.is_enabled("f")

    provider.load({"toggles": []})
    assert not provider.is_enabled("f")


def test_data_is_read_only() -> None:
    provider = LocalFeatureProvider({"f": Feature(key="f", value="true")})
    with pytest.raises(TypeError):
        provider.data["f"] = Feature(key="f", value="false")  # type: ignore[index]


def test_constructor_copies_the_data() -> None:
    data = {"f": Feature(key="f", value="true")}
    provider = LocalFeatureProvider(data)
    data.clear()
    assert provider.is_enabled("f")


def test_boolean_provider_drops_non_booleans(tmp_path: Path) -> None:
    provider = LocalBooleanProvider.from_file(write(tmp_path, {"on": True, "text": "true"}))
    assert provider.data == {"on": True}
    assert provider.is_enabled("on")
    assert not provider.is_enabled("text")

    provider.replace({"on": False, "one": 1})
    assert provider.data == {"on": False}
    assert not provider.is_enabled("on")


def test_boolean_file_must_be_an_object(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="expected a JSON object"):
        LocalBooleanProvider.from_file(write(tmp_path, [True]))


def test_providers_satisfy_the_protocol() -> None:
    assert isinstance(LocalFeatureProvider(), FeatureProvider)
    assert isinstance(LocalBooleanProvider(), FeatureProvider)

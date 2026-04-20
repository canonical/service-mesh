# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from contextlib import nullcontext as does_not_raise

import pytest

from canonical_service_mesh.utils import charm_kubernetes_label, generate_telemetry_labels


@pytest.mark.parametrize(
    "model_name, app_name, prefix, suffix, expected",
    [
        ("model", "app", "", "", "model.app"),
        ("model", "app", "prefix/", "-suffix", "prefix/model.app-suffix"),
        # Exactly at the limit (31+31+1 separator = 63)
        ("m" * 31, "a" * 31, "", "", f"{'m' * 31}.{'a' * 31}"),
        # 1 char over — triggers truncation with hash
        (
            "m" * 32,
            "a" * 31,
            "",
            "",
            "mmmmmmmmmmmmmmmmmmmmmmmmmmm.aaaaaaaaaaaaaaaaaaaaaaaaaaaa.c4949d",
        ),
        # Truncation with prefix and suffix
        (
            "m" * 40,
            "a" * 40,
            "prefix/",
            "-suffix",
            "prefix/mmmmmmmmmmmmmmmmmmmm.aaaaaaaaaaaaaaaaaaaaa.499dc0-suffix",
        ),
    ],
)
def test_label_generation(model_name, app_name, prefix, suffix, expected):
    label = charm_kubernetes_label(model_name, app_name, prefix, suffix)
    assert label == expected
    assert len(label) <= 63


def test_label_custom_separator():
    label = charm_kubernetes_label("m" * 40, "a" * 40, separator="-")
    assert "-" in label
    assert len(label) <= 63


def test_truncated_labels_are_unique():
    label1 = charm_kubernetes_label("m" * 100, "a" * 100)
    label2 = charm_kubernetes_label("m" * 90, "a" * 90)
    assert label1 != label2
    assert len(label1) <= 63
    assert len(label2) <= 63


def test_error_on_empty_model_or_app():
    with pytest.raises(ValueError):
        charm_kubernetes_label("", "app")
    with pytest.raises(ValueError):
        charm_kubernetes_label("model", "")


@pytest.mark.parametrize(
    "model_name, app_name, suffix, max_length, ctx",
    [
        ("m" * 31, "a" * 31, "", 63, does_not_raise()),
        ("m" * 31, "a" * 31, "", 62, does_not_raise()),
        ("m", "a", "", 1, pytest.raises(ValueError)),
        ("m", "a", "s" * 60, 62, pytest.raises(ValueError)),
    ],
)
def test_max_length_constraints(model_name, app_name, suffix, max_length, ctx):
    with ctx:
        result = charm_kubernetes_label(
            model_name=model_name, app_name=app_name, suffix=suffix, max_length=max_length
        )
        assert len(result) <= max_length


def test_generate_telemetry_labels():
    labels = generate_telemetry_labels(app_name="myapp", model_name="mymodel")
    assert len(labels) == 1
    key = next(iter(labels))
    assert key.startswith("charms.canonical.com/")
    assert key.endswith(".telemetry")
    assert labels[key] == "aggregated"

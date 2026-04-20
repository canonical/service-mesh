# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Kubernetes label generation utilities."""

import hashlib


def _truncate_charm_kubernetes_label(
    model_name: str,
    app_name: str,
    prefix: str = "",
    suffix: str = "",
    max_length: int = 63,
    separator: str = ".",
    hash_length: int = 6,
    min_characters_per_truncatable_part: int = 1,
) -> str:
    """Generate a truncated label with a uniqueness hash.

    Returns a label in the form ``{prefix}{model_name}{separator}{app_name}{suffix}{separator}{hash}``
    where ``model_name`` and ``app_name`` are truncated to fit within ``max_length``.

    Args:
        model_name: The name of the model (must be at least 1 character).
        app_name: The name of the application (must be at least 1 character).
        prefix: An optional prefix to prepend.
        suffix: An optional suffix to append.
        max_length: The maximum length of the label string.
        separator: The separator between model_name and app_name.
        hash_length: The length of the hash to append.
        min_characters_per_truncatable_part: Minimum characters to keep per truncatable part.

    Returns:
        The generated label string, at most ``max_length`` characters long.

    Raises:
        ValueError: If the fixed label portion is too long to allow for truncation.
    """
    fixed_length = len(prefix) + len(suffix) + hash_length + 2
    if fixed_length + 2 * min_characters_per_truncatable_part > max_length:
        raise ValueError(
            f"Fixed label portion (prefix, suffix, hash, and separator) is too long "
            f"({fixed_length} chars); must leave at least 1 character each for model_name "
            f"and app_name to fit within the {max_length} character limit."
        )

    hash_digest = hashlib.sha1(
        f"{model_name}{separator}{app_name}".encode()
    ).hexdigest()[:hash_length]

    available = max_length - fixed_length
    total = len(model_name) + len(app_name)
    model_len = max(min_characters_per_truncatable_part, int(available * len(model_name) / total))
    app_len = max(min_characters_per_truncatable_part, available - model_len)
    truncated_model = model_name[:model_len]
    truncated_app = app_name[:app_len]

    return f"{prefix}{truncated_model}{separator}{truncated_app}{separator}{hash_digest}{suffix}"


def charm_kubernetes_label(
    model_name: str,
    app_name: str,
    prefix: str = "",
    suffix: str = "",
    max_length: int = 63,
    separator: str = ".",
) -> str:
    """Generate a Kubernetes-compliant label value.

    Returns a label in the form ``{prefix}{model_name}{separator}{app_name}{suffix}``.
    If the label exceeds ``max_length`` characters, model_name and app_name are truncated
    and a hash is appended to ensure uniqueness.

    See https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/#syntax-and-character-set

    Args:
        model_name: The name of the model (must be at least 1 character).
        app_name: The name of the application (must be at least 1 character).
        prefix: An optional prefix to prepend.
        suffix: An optional suffix to append.
        max_length: The maximum length of the label string.
        separator: The separator between model_name and app_name.

    Returns:
        The generated label string, at most ``max_length`` characters long.

    Raises:
        ValueError: If model_name or app_name is empty, or if the fixed portion is too long.
    """
    if not model_name or not app_name:
        raise ValueError("Both model_name and app_name must be at least 1 character long.")

    label = f"{prefix}{model_name}{separator}{app_name}{suffix}"

    if len(label) > max_length:
        return _truncate_charm_kubernetes_label(
            model_name=model_name,
            app_name=app_name,
            prefix=prefix,
            suffix=suffix,
            max_length=max_length,
            separator=separator,
        )

    return label


def generate_telemetry_labels(app_name: str, model_name: str) -> dict[str, str]:
    """Generate telemetry labels for the application.

    The label key includes model_name and app_name, truncated to fit within
    Kubernetes' 63-character limit while maintaining uniqueness via a hash.

    Args:
        app_name: The application name.
        model_name: The model (namespace) name.

    Returns:
        A dictionary with a single telemetry label.
    """
    telemetry_key = charm_kubernetes_label(
        model_name=model_name,
        app_name=app_name,
        prefix="charms.canonical.com/",
        suffix=".telemetry",
    )
    return {
        telemetry_key: "aggregated",
    }

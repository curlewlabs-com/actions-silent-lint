"""Type guards for parsed YAML, so strict type checking can follow an
`isinstance` test on a value that arrived as `Any` or `object`.

`isinstance(value, Mapping)` narrows to a mapping of Unknown, which strict
pyright rejects wherever the contents are used. Each guard here is that same
`isinstance` test and only states what the contents are: the keys and values
of a parsed document are read, never assumed, by their callers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeGuard


def is_mapping(value: object) -> TypeGuard[Mapping[Any, Any]]:
    return isinstance(value, Mapping)


def is_list(value: object) -> TypeGuard[list[Any]]:
    return isinstance(value, list)

from __future__ import annotations

import json
from typing import Any

from storyforge.core.io import to_jsonable


def json_dump(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False)


def json_load(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)

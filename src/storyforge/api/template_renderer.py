from __future__ import annotations

from pathlib import Path
import re


INCLUDE_PATTERN = re.compile(r'{{\s*include\s+"(?P<path>[^"]+)"\s*}}')


def render_template(template_root: Path, template_name: str) -> str:
    cache: dict[str, str] = {}

    def load(name: str) -> str:
        if name in cache:
            return cache[name]

        template_path = template_root / name
        content = template_path.read_text(encoding="utf-8")

        def replace_include(match: re.Match[str]) -> str:
            nested_name = match.group("path")
            return load(nested_name)

        rendered = INCLUDE_PATTERN.sub(replace_include, content)
        cache[name] = rendered
        return rendered

    return load(template_name)

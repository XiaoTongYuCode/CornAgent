from collections.abc import Mapping


def render_metric_line(name: str, labels: Mapping[str, str], value: int | float) -> str:
    return f"{name}{_render_label_block(labels)} {format_metric_value(value)}"


def _render_label_block(labels: Mapping[str, str]) -> str:
    if not labels:
        return ""
    rendered = ",".join(f'{name}="{_escape_label_value(value)}"' for name, value in labels.items())
    return f"{{{rendered}}}"


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def format_metric_value(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    if value.is_integer():
        return str(int(value))
    return f"{value:.15g}"

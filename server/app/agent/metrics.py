"""Low-cardinality observability for the Agent runtime."""

from __future__ import annotations

from threading import Lock

from app.metric_format import render_metric_line


class AgentMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}
        self._timings: dict[str, tuple[int, float]] = {}
        self._active_runs = 0
        self._active_children = 0

    def child_started(self) -> None:
        with self._lock:
            self._active_children += 1

    def child_finished(self) -> None:
        with self._lock:
            self._active_children = max(0, self._active_children - 1)

    def increment(self, name: str, **labels: str) -> None:
        key = (name, tuple(sorted(labels.items())))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + 1

    def run_started(self) -> None:
        with self._lock:
            self._active_runs += 1
        self.increment("cornagent_agent_runs_started_total")

    def run_finished(self, outcome: str) -> None:
        with self._lock:
            self._active_runs = max(0, self._active_runs - 1)
        self.increment("cornagent_agent_runs_finished_total", outcome=outcome)

    def observe_duration(self, name: str, seconds: float) -> None:
        with self._lock:
            count, total = self._timings.get(name, (0, 0.0))
            self._timings[name] = (count + 1, total + max(0.0, seconds))

    def render(self) -> str:
        with self._lock:
            counters = dict(self._counters)
            timings = dict(self._timings)
            active_runs = self._active_runs
            active_children = self._active_children
        lines = [
            "# HELP cornagent_agent_active_runs Agent Runs currently holding an execution slot.",
            "# TYPE cornagent_agent_active_runs gauge",
            render_metric_line("cornagent_agent_active_runs", {}, active_runs),
            render_metric_line("cornagent_subagent_active_tasks", {}, active_children),
        ]
        for (name, label_items), count in sorted(counters.items()):
            lines.append(render_metric_line(name, dict(label_items), count))
        for name, (count, total) in sorted(timings.items()):
            lines.append(render_metric_line(f"{name}_seconds_sum", {}, total))
            lines.append(render_metric_line(f"{name}_seconds_count", {}, count))
        return "\n".join(lines) + "\n"


__all__ = ["AgentMetrics"]

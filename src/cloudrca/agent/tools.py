"""Read-only agent tools (plan §7). Parameterised SQL only; row limits; every call -> agent_log.
Tools: list_incidents, get_rca, get_cost_breakdown, query_metrics, get_logs, find_similar, what_if, get_changes.
TODO(W19)."""
MAX_ROWS = 200

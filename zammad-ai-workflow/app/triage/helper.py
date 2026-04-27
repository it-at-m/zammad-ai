"""Helper utilities for triage rules and comparisons."""

import operator as op

from app.settings.triage import ConditionOperator


def get_operator_function(operator: ConditionOperator):
    """Map a ConditionOperator identifier to the corresponding binary comparison function.

    Parameters:
        operator (ConditionOperator): Identifier for the comparison; expected values are
            "equals", "not_equals", "less", "less_equals", "greater", and "greater_equals".

    Returns:
        function: The binary comparison function from the `operator` module that matches
        `operator` (e.g., `op.eq`, `op.lt`). If `operator` is unrecognized, returns `op.eq`.
    """
    operator_map = {
        "equals": op.eq,
        "not_equals": op.ne,
        "less": op.lt,
        "less_equals": op.le,
        "greater": op.gt,
        "greater_equals": op.ge,
    }
    return operator_map.get(operator, op.eq)

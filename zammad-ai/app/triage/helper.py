import operator as op

from app.core.settings.triage import ConditionOperator


def get_operator_function(operator: ConditionOperator):
    """
    Return the Python binary comparison function that corresponds to the given ConditionOperator.
    
    Parameters:
        operator (ConditionOperator): Comparison operator identifier — expected values include
            "equals", "not_equals", "less", "less_equals", "greater", and "greater_equals".
    
    Returns:
        function: A binary function that performs the requested comparison (for example,
        `operator.eq` or `operator.lt`). If `operator` is not recognized, returns `operator.eq`.
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
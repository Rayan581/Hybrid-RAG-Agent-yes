import math
import logging

logger = logging.getLogger(__name__)

def calculate(expression: str) -> str:
    """
    Evaluates a mathematical expression safely.
    Example: "2 + 2", "sqrt(16)", "5 * 10"
    """
    try:
        # Define allowed functions for safety
        allowed_names = {
            "abs": abs,
            "round": round,
            "sum": sum,
            "min": min,
            "max": max,
            "pow": pow,
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "pi": math.pi,
            "e": math.e,
        }
        
        # eval() is generally dangerous, but with restricted globals/locals it's safer for a demo
        # For a production app, use a proper math parser like 'numexpr' or 'simpleeval'
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return f"The result of {expression} is {result}."
    except Exception as e:
        logger.error(f"Calculator tool error: {e}")
        return f"I couldn't calculate that. Error: {str(e)}"

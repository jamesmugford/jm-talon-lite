"""Pure conversion of fractional scroll motion to protocol steps."""


def accumulate_steps(delta: float, remainder: float) -> tuple[int, float]:
    """Return whole scroll steps and the unconsumed fractional remainder."""
    total = delta + remainder
    steps = int(total)
    return steps, total - steps

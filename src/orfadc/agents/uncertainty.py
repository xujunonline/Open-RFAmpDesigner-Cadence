class RemoteEvaluationUncertain(RuntimeError):
    """A planned remote dispatch may still be running; do not dispatch it again."""

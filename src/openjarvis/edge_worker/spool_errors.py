"""Stable local failures raised by the durable Edge spool."""


class EdgeSpoolCapacityError(RuntimeError):
    """The durable outbound queue reached its configured safety boundary."""


class EdgeTerminalPayloadError(ValueError):
    """A terminal result cannot be represented by the bounded Edge protocol."""


__all__ = ["EdgeSpoolCapacityError", "EdgeTerminalPayloadError"]

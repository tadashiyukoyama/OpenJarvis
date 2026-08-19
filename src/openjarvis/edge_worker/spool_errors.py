"""Stable local failures raised by the durable Edge spool."""


class EdgeSpoolCapacityError(RuntimeError):
    """The durable outbound queue reached its configured safety boundary."""


__all__ = ["EdgeSpoolCapacityError"]

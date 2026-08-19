"""Domain-specific failures exposed by Wayland capabilities."""


class CapabilityUnavailable(RuntimeError):
    """A requested desktop capability is not currently available."""

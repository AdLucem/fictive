"""Public exceptions raised by the standalone agent harness."""


class AgentHarnessError(Exception):
    """Base class for harness configuration and policy failures."""


class ConfigurationError(AgentHarnessError):
    """Trusted host configuration or a request is invalid."""


class WorkspaceViolation(AgentHarnessError):
    """A requested workspace is outside the host-granted root."""

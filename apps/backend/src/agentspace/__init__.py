"""The local FastAPI sidecar for AgentSpace.

Orchestration and state remain local. Providers, the web tool, and the optional
Discord adapter make the outbound connections described in the user guide.
"""

__all__ = ["__version__"]

__version__ = "0.4.1"

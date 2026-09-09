"""agentspace — the local-first FastAPI sidecar for the agent co-working space.

Everything this package exposes runs on the user's own machine. The only traffic
that leaves it is model inference (BUILD_SPEC §2).
"""

__all__ = ["__version__"]

__version__ = "0.1.0"

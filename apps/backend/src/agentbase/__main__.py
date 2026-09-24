"""Console entry point, and the script PyInstaller freezes.

Kept separate from :mod:`agentbase.main` so that importing the application in
tests or other Python callers never starts a server as a side effect.
"""

from agentbase.main import run

if __name__ == "__main__":
    run()

"""Local artifact API plugin package."""

__all__ = ["LocalArtifactApiPlugin"]


def __getattr__(name: str):
    if name == "LocalArtifactApiPlugin":
        from .main import LocalArtifactApiPlugin

        return LocalArtifactApiPlugin
    raise AttributeError(name)

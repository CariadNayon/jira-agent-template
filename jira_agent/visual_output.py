"""Rich read-only tool results: pixels for the model, small metadata for the UI/history."""
from dataclasses import dataclass


@dataclass(repr=False)
class PageImage:
    page: int
    data: bytes
    mime: str = "image/png"


@dataclass(repr=False)
class VisualResult:
    metadata: dict
    images: list[PageImage]

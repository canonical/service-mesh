"""Configuration parser for the charm."""

from pydantic import BaseModel, Field


class CharmConfig(BaseModel):
    """Manager for the charm configuration."""

    view_only_mode: bool = Field(alias="view-only-mode")  # type: ignore

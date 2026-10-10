from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable explanation.")
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """The single error shape used by every endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "error": {
                        "code": "PROCESSING_FAILED",
                        "message": "No .shp file found in the archive. Files found: readme.txt",
                        "details": {"file_id": "3f2b8c1e-5d0a-4a7e-9b8e-2c4d6f8a1b3c"},
                    }
                }
            ]
        }
    )

    error: ErrorBody

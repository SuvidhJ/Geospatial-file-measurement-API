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
                        "message": "No .shp file found in the archive. Files found: readme.txt.",
                        "details": {"file_id": "8a8d93d7-e3df-497d-838f-75e475c97831"},
                    }
                }
            ]
        }
    )

    error: ErrorBody

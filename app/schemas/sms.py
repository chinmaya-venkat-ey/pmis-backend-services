from typing import Optional

from pydantic import BaseModel, Field


class SMSRequest(BaseModel):
    to: str = Field(..., description="Recipient phone number in E.164 format", examples=["+919999999999"])
    message: str = Field(..., min_length=1, max_length=1600)

    model_config = {
        "json_schema_extra": {
            "example": {
                "to": "+919999999999",
                "message": "Your PIMS appointment is confirmed.",
            }
        }
    }


class SMSResponse(BaseModel):
    success: bool
    message: str
    provider: str
    message_id: Optional[str] = None

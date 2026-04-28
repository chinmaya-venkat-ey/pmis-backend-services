from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


class EmailRequest(BaseModel):
    to: List[EmailStr] = Field(..., description="Recipient email addresses", min_length=1)
    subject: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1, description="Plain text or HTML body")
    is_html: bool = Field(default=False)
    cc: Optional[List[EmailStr]] = None
    bcc: Optional[List[EmailStr]] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "to": ["user@example.com"],
                "subject": "Welcome to PIMS",
                "body": "<h1>Hello</h1><p>Welcome to the PIMS portal.</p>",
                "is_html": True,
            }
        }
    }


class EmailResponse(BaseModel):
    success: bool
    message: str
    provider: str
    message_id: Optional[str] = None

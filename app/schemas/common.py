from pydantic import BaseModel


class Pagination(BaseModel):
    limit: int = 100
    offset: int = 0
    total: int


class ErrorResponse(BaseModel):
    detail: str

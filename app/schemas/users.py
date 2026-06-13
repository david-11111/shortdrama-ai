from pydantic import BaseModel


class UserProfileResponse(BaseModel):
    id: int
    user_id: str
    email: str
    display_name: str | None
    tier: str
    credits_balance: int


class ApiKeyCreateRequest(BaseModel):
    name: str = "default"


class ApiKeyResponse(BaseModel):
    key_id: str
    name: str
    created_at: str
    # 完整 key 只在创建时返回一次
    api_key: str | None = None


class ApiKeyListResponse(BaseModel):
    keys: list[ApiKeyResponse]

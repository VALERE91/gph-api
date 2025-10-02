from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Awesome API"
    db_url: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_seconds: int = 3600

    s3_endpoint_url: str
    s3_access_key: str
    s3_secret_key: str
    s3_region_name: str
    s3_bucket_name: str

    # Superuser credentials for initial setup
    superuser_username: str = "superuser"
    superuser_password: str = "superuser"

    model_config = SettingsConfigDict(env_file=".env")


@lru_cache
def get_settings():
    return Settings()
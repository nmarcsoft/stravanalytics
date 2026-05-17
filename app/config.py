from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./dev.db"
    STRAVA_CLIENT_ID: str = ""
    STRAVA_CLIENT_SECRET: str = ""
    SECRET_KEY: str = "changeme-in-production"
    BASE_URL: str = "http://localhost:8000"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()

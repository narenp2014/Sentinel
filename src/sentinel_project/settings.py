from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "OPEN_API_KEY"),
    )
    openai_base_url: str = "https://api.openai.com/v1"
    target_model: str = "gpt-4.1-mini"
    agent_model: str = "gpt-4.1-mini"
    database_url: str = "sqlite:///./sentinel.db"
    chroma_path: str = "./data/chroma"


settings = Settings()

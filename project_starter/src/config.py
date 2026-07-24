from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    
    model_name: str = Field(
        default="openrouter/free",  
        description="The LLM model to use"
    )
    max_steps: int = Field(default=10, description="Max steps for agent execution")
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="console", description="Logging format (json or console)")

    # مفاتيح API للمزودين المدعومين
    openrouter_api_key: str | None = Field(default=None, description="OpenRouter API key")
    openai_api_key: str | None = Field(default=None, description="OpenAI API key")
    groq_api_key: str | None = Field(default=None, description="Groq API key")
    cerebras_api_key: str | None = Field(default=None, description="Cerebras API key")

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()

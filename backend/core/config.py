from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Application ──
    APP_NAME: str = "ResearchFlow-Agent"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "*"

    # ── Database ──
    POSTGRES_URL: str = "postgresql+asyncpg://researchflow:changeme@localhost:5432/researchflow"
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── LLM ──
    LLM_API_BASE: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = "sk-placeholder"
    LLM_MODEL: str = "gpt-4o"
    EMBEDDING_MODEL: str = "text-embedding-3-large"

    # ── RAG ──
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 64
    RETRIEVAL_TOP_K: int = 8

    # ── External Services ──
    TAVILY_API_KEY: str = ""

    # ── MCP ──
    MCP_SERVER_CONFIG: str = "./mcp_servers.json"

    # ── Celery ──
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"

    # ── Security ──
    JWT_SECRET: str = "change-me-to-a-random-string"
    JWT_EXPIRE_MINUTES: int = 60
    RATE_LIMIT_PER_MINUTE: int = 30

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

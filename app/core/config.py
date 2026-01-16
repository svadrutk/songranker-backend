from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    MUSICBRAINZ_USER_AGENT: str = "SongRanker/0.1 ( https://github.com/svadrut/songranker )"
    
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    
    BACKEND_CORS_ORIGINS: list[str] = ["*"]
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

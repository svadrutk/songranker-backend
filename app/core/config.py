from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    MUSICBRAINZ_USER_AGENT: str = "SongRanker/0.1 ( https://github.com/svadrut/songranker )"
    LASTFM_API_KEY: str = ""
    LASTFM_SHARED_SECRET: str = ""
    
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    
    # Fallbacks for local/nextjs envs
    NEXT_PUBLIC_SUPABASE_URL: str = ""
    SUPABASE_PUBLIC_ANON_KEY: str = ""
    
    # Spotify
    SPOTIFY_CLIENT_ID: str = ""
    SPOTIFY_CLIENT_SECRET: str = ""
    
    BACKEND_CORS_ORIGINS: list[str] = ["*"]
    
    @property
    def effective_supabase_url(self) -> str:
        return self.SUPABASE_URL or self.NEXT_PUBLIC_SUPABASE_URL
        
    @property
    def effective_supabase_key(self) -> str:
        return self.SUPABASE_SERVICE_ROLE_KEY or self.SUPABASE_PUBLIC_ANON_KEY

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

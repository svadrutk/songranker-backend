from pydantic import SecretStr
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

    # Apple Music
    APPLE_MUSIC_TEAM_ID: str = ""
    APPLE_MUSIC_KEY_ID: str = ""
    # Store .p8 content as BASE64 (single-line).
    # Encode with: base64 -i AuthKey_xxx.p8 | tr -d '\n'
    APPLE_MUSIC_PRIVATE_KEY_B64: SecretStr = SecretStr("")
    APPLE_MUSIC_STOREFRONT: str = "us"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Rate Limiting
    SPOTIFY_PAUSE_KEY: str = "spotify:global_pause"
    
    BACKEND_CORS_ORIGINS: list[str] = ["*"]
    
    @property
    def effective_supabase_url(self) -> str:
        return self.SUPABASE_URL or self.NEXT_PUBLIC_SUPABASE_URL
        
    @property
    def effective_supabase_key(self) -> str:
        return self.SUPABASE_SERVICE_ROLE_KEY or self.SUPABASE_PUBLIC_ANON_KEY

    @property
    def apple_music_configured(self) -> bool:
        """True only when all three Apple Music credential fields are non-empty and the key is valid."""
        if not (
            self.APPLE_MUSIC_TEAM_ID.strip()
            and self.APPLE_MUSIC_KEY_ID.strip()
            and self.APPLE_MUSIC_PRIVATE_KEY_B64.get_secret_value().strip()
        ):
            return False
        # Validate the decoded key parses as a valid EC P-256 private key
        try:
            import base64
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey, SECP256R1
            raw = base64.b64decode(self.APPLE_MUSIC_PRIVATE_KEY_B64.get_secret_value())
            key = load_pem_private_key(raw, password=None)
            return isinstance(key, EllipticCurvePrivateKey) and isinstance(key.curve, SECP256R1)
        except Exception:
            return False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

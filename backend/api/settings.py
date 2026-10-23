import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    """Minimal KEY=VALUE loader; real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./labellock.db"
    auth_secret: str = "dev-only-change-me"
    cors_origin: str = "http://localhost:5173"
    extension_origin: str = ""  # chrome-extension://<id>; empty = not allowed
    upload_dir: Path = Path("./uploads")
    demo_mode: bool = False
    token_ttl_seconds: int = 12 * 3600

    @property
    def cors_origins(self) -> list[str]:
        return [o for o in (self.cors_origin, self.extension_origin) if o]

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        env = os.environ
        return cls(
            database_url=env.get("DATABASE_URL", cls.database_url),
            auth_secret=env.get("AUTH_SECRET", cls.auth_secret),
            cors_origin=env.get("CORS_ORIGIN", cls.cors_origin),
            extension_origin=env.get("EXTENSION_ORIGIN", ""),
            upload_dir=Path(env.get("UPLOAD_DIR", str(cls.upload_dir))),
            demo_mode=env.get("DEMO_MODE", "false").lower() == "true",
        )

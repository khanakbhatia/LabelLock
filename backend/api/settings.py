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
    sim_database_url: str = "sqlite:///./sim.db"
    sim_api_key: str = "dev-sim-key"
    sim_base_url: str = "http://localhost:8000"  # where adapters reach /sim/*
    seed_dir: Path = REPO_ROOT / "data" / "seed"
    llm_mode: str = "mock"
    llm_model: str = "claude-opus-5-5"
    eval_results_path: Path = REPO_ROOT / "backend" / "scenarios" / "results" / "latest.json"
    roi_assumptions_path: Path = REPO_ROOT / "backend" / "config" / "roi_assumptions.json"

    def insecure_defaults(self) -> list[str]:
        """Shipped development secrets still in use; only acceptable with DEMO_MODE=true."""
        return [name for name, value, default in (("AUTH_SECRET", self.auth_secret, Settings.auth_secret),
                                                  ("SIM_API_KEY", self.sim_api_key, Settings.sim_api_key)) if value == default]

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
            sim_database_url=env.get("SIM_DATABASE_URL", cls.sim_database_url),
            sim_api_key=env.get("SIM_API_KEY", cls.sim_api_key),
            sim_base_url=env.get("SIM_BASE_URL", cls.sim_base_url),
            seed_dir=Path(env.get("SEED_DIR", str(cls.seed_dir))),
            llm_mode=env.get("LLM_MODE", cls.llm_mode),
            llm_model=env.get("LLM_MODEL", cls.llm_model),
        )

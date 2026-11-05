from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # MONGO_URI: str = "mongodb+srv://Greenvtu:Greenvtu123@my.uomd83r.mongodb.net/?appName=My"
    MONGO_URI: str="mongodb://Greenvtu:Greenvtu123@ac-ywytwgt-shard-00-00.uomd83r.mongodb.net:27017,ac-ywytwgt-shard-00-01.uomd83r.mongodb.net:27017,ac-ywytwgt-shard-00-02.uomd83r.mongodb.net:27017/?ssl=true&replicaSet=atlas-12v6jw-shard-0&authSource=admin"
    MONGO_DB: str = "gdss_tudun_wada"
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    CORS_ORIGINS: str = "http://localhost:5173"

    class Config:
        env_file = ".env"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
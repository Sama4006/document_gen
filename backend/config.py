import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration from environment variables"""
    
    # OpenAI Configuration
    openai_api_key: str
    openai_model: str = "gpt-4"
    openai_embedding_model: str = "text-embedding-3-small"
    
    # Server Configuration
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    
    # ChromaDB Configuration
    chroma_db_path: str = "./chroma_data"
    collection_name: str = "documents"
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        
    
settings = Settings()

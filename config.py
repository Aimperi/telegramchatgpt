"""Configuration module for Telegram Recipe Bot."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

from errors import ConfigurationError


@dataclass
class BotConfig:
    """Bot configuration loaded from environment variables."""
    bot_token: str
    openai_api_key: str
    database_url: str | None = None
    webhook_url: str | None = None
    port: int = 8000
    
    @classmethod
    def from_env(cls) -> "BotConfig":
        """
        Load configuration from environment variables.
        
        ⚠️ ВАЖНО: Переменные окружения настраиваются в Railway Dashboard,
        не в локальном .env файле
        
        Returns:
            BotConfig: Configuration object
            
        Raises:
            ConfigurationError: If required environment variables are missing
        """
        # load_dotenv() используется только для совместимости,
        # на Railway переменные уже доступны в окружении
        load_dotenv()
        
        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            raise ConfigurationError("BOT_TOKEN environment variable is required")
            
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY environment variable is required")
            
        return cls(
            bot_token=bot_token,
            openai_api_key=openai_api_key,
            database_url=os.getenv("DATABASE_URL"),
            webhook_url=os.getenv("WEBHOOK_URL"),
            port=int(os.getenv("PORT", "8000"))
        )

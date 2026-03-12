"""Error classes for Telegram Recipe Bot."""


class BotError(Exception):
    """Base class for bot errors."""
    pass


class ValidationError(BotError):
    """Raised when user input validation fails."""
    pass


class OpenAIAPIError(BotError):
    """Base class for OpenAI API errors."""
    pass


class RateLimitError(OpenAIAPIError):
    """Raised when OpenAI API rate limit is exceeded."""
    pass


class AuthenticationError(OpenAIAPIError):
    """Raised when OpenAI API authentication fails."""
    pass


class ConfigurationError(BotError):
    """Raised when configuration is invalid or incomplete."""
    pass

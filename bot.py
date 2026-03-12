"""Main bot module for Telegram Recipe Bot."""
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

from config import BotConfig
from errors import ConfigurationError, RateLimitError, AuthenticationError, OpenAIAPIError
from openai_client import OpenAIClient
from prompts import WELCOME_MESSAGE, ERROR_MESSAGES
from validation import validate_product_list
from models import RecipeResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variables for bot components
bot: Bot = None
openai_client: OpenAIClient = None


async def start_handler(message: Message):
    """
    Handle /start command.
    
    Args:
        message: Incoming message from user
    """
    await message.answer(WELCOME_MESSAGE)
    logger.info(f"User {message.from_user.id} started the bot")


async def message_handler(message: Message):
    """
    Handle text messages with product lists.
    
    Args:
        message: Incoming message from user
    """
    user_id = message.from_user.id
    product_list = message.text
    
    logger.info(f"User {user_id} sent product list: {product_list[:50]}...")
    
    # Validate input
    is_valid, error_key = validate_product_list(product_list)
    if not is_valid:
        await message.answer(ERROR_MESSAGES[error_key])
        logger.warning(f"Invalid input from user {user_id}: {error_key}")
        return
    
    try:
        # Generate recipes
        await message.answer("🔍 Ищу рецепты для вас...")
        recipes = await openai_client.generate_recipes(product_list)
        
        # Format and send response
        recipe_response = RecipeResponse(
            recipe1=recipes["recipe1"],
            recipe2=recipes["recipe2"]
        )
        formatted_message = recipe_response.to_telegram_message()
        
        await message.answer(formatted_message, parse_mode="MarkdownV2")
        logger.info(f"Successfully sent recipes to user {user_id}")
        
    except (RateLimitError, AuthenticationError, OpenAIAPIError) as e:
        await message.answer(ERROR_MESSAGES["service_unavailable"])
        logger.error(f"OpenAI API error for user {user_id}: {e}")
    except Exception as e:
        await message.answer(ERROR_MESSAGES["service_unavailable"])
        logger.error(f"Unexpected error for user {user_id}: {e}", exc_info=True)


async def main():
    """Main entry point for the bot."""
    global bot, openai_client
    
    try:
        # Load configuration
        config = BotConfig.from_env()
        logger.info("Configuration loaded successfully")
        
        # Initialize bot and dispatcher
        bot = Bot(token=config.bot_token)
        dp = Dispatcher()
        
        # Initialize OpenAI client
        openai_client = OpenAIClient(api_key=config.openai_api_key)
        logger.info("OpenAI client initialized")
        
        # Register handlers
        dp.message.register(start_handler, Command("start"))
        dp.message.register(message_handler)
        
        logger.info("Bot started successfully")
        
        # Start polling
        await dp.start_polling(bot)
        
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        logger.error("Bot cannot start without proper configuration")
        return
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return


if __name__ == "__main__":
    asyncio.run(main())

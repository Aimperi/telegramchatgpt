"""Main bot module for Telegram Recipe Bot."""
import asyncio
import logging
import uvicorn
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

from config import BotConfig
from errors import ConfigurationError, RateLimitError, AuthenticationError, OpenAIAPIError
from openai_client import OpenAIClient
from database import Database
import admin as admin_module
from admin import app as admin_app
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
db: Database = None


async def start_handler(message: Message):
    """
    Handle /start command.
    
    Args:
        message: Incoming message from user
    """
    # Save user to database
    if db:
        await db.save_user(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name
        )
    
    await message.answer(WELCOME_MESSAGE)
    logger.info(f"User {message.from_user.id} started the bot")


async def history_handler(message: Message):
    """
    Handle /history command - show user's recent recipes.
    
    Args:
        message: Incoming message from user
    """
    user_id = message.from_user.id
    
    # Check if database is available
    if not db:
        await message.answer(
            "📊 История рецептов недоступна.\n\n"
            "Для использования этой функции необходимо подключение к базе данных."
        )
        logger.info(f"User {user_id} tried to access history without database")
        return
    
    try:
        # Get user's recent recipes
        recipes = await db.get_user_recipes(user_id, limit=5)
        
        if not recipes:
            await message.answer(
                "📭 У вас пока нет сохраненных рецептов.\n\n"
                "Отправьте список продуктов, чтобы получить рецепты!"
            )
            logger.info(f"User {user_id} has no recipes in history")
            return
        
        # Format history message
        history_text = "📚 *Ваши последние рецепты:*\n\n"
        
        for recipe in recipes:
            created_at = recipe['created_at'].strftime("%d.%m.%Y %H:%M")
            recipe_num = recipe['recipe_number']
            title = recipe['recipe_title']
            products = recipe['product_list'][:50]  # First 50 chars
            
            history_text += f"🍳 *{title}*\n"
            history_text += f"📅 {created_at}\n"
            history_text += f"🛒 Продукты: {products}{'...' if len(recipe['product_list']) > 50 else ''}\n"
            history_text += f"⏱ Время: {recipe['cooking_time']}\n\n"
        
        history_text += "💡 _Отправьте новый список продуктов для генерации рецептов_"
        
        await message.answer(history_text, parse_mode="Markdown")
        logger.info(f"Sent history to user {user_id}: {len(recipes)} recipes")
        
    except Exception as e:
        await message.answer(ERROR_MESSAGES["service_unavailable"])
        logger.error(f"Error fetching history for user {user_id}: {e}", exc_info=True)
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
    
    # Save/update user in database
    if db:
        await db.save_user(
            user_id=user_id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name
        )
    
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
        
        # Save recipes to database
        if db:
            await db.save_recipe(
                user_id=user_id,
                product_list=product_list,
                recipe_number=1,
                recipe_title=recipes["recipe1"].title,
                ingredients=recipes["recipe1"].ingredients,
                steps=recipes["recipe1"].steps,
                cooking_time=recipes["recipe1"].cooking_time
            )
            await db.save_recipe(
                user_id=user_id,
                product_list=product_list,
                recipe_number=2,
                recipe_title=recipes["recipe2"].title,
                ingredients=recipes["recipe2"].ingredients,
                steps=recipes["recipe2"].steps,
                cooking_time=recipes["recipe2"].cooking_time
            )
        
        # Format and send response
        recipe_response = RecipeResponse(
            recipe1=recipes["recipe1"],
            recipe2=recipes["recipe2"]
        )
        formatted_message = recipe_response.to_telegram_message()
        
        await message.answer(formatted_message, parse_mode="MarkdownV2")
        logger.info(f"Successfully sent recipes to user {user_id}")
        
        # Generate and send recipe image
        try:
            await message.answer("🎨 Генерирую изображение блюда...")
            image_url = await openai_client.generate_recipe_image(
                recipes["recipe1"].title,
                recipes["recipe1"].ingredients
            )
            await message.answer_photo(photo=image_url, caption=f"🍽 {recipes['recipe1'].title}")
            logger.info(f"Sent recipe image to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to generate image for user {user_id}: {e}")
            # Don't send error to user - image is optional
        
    except (RateLimitError, AuthenticationError, OpenAIAPIError) as e:
        await message.answer(ERROR_MESSAGES["service_unavailable"])
        logger.error(f"OpenAI API error for user {user_id}: {e}")
    except Exception as e:
        await message.answer(ERROR_MESSAGES["service_unavailable"])
        logger.error(f"Unexpected error for user {user_id}: {e}", exc_info=True)


async def main():
    """Main entry point for the bot."""
    global bot, openai_client, db
    
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
        
        # Initialize database if DATABASE_URL is provided
        if config.database_url:
            db = Database(database_url=config.database_url)
            await db.connect()
            admin_module.db = db  # Share db instance with admin panel
            logger.info("Database connected successfully")
            await db.create_default_admin("recipeadmin", "RecipeBot#2026!")
        else:
            logger.warning("DATABASE_URL not provided, running without database")
        
        # Register handlers
        dp.message.register(start_handler, Command("start"))
        dp.message.register(history_handler, Command("history"))
        dp.message.register(message_handler)
        
        logger.info("Bot started successfully")
        
        # Run web server and bot concurrently
        async def run_web():
            config_uvicorn = uvicorn.Config(
                admin_app, host="0.0.0.0", port=8080,
                log_level="info", timeout_graceful_shutdown=5
            )
            server = uvicorn.Server(config_uvicorn)
            logger.info("Admin panel started on port 8080")
            await server.serve()

        async def run_bot():
            await asyncio.sleep(1)  # Let web server bind first
            try:
                await dp.start_polling(bot)
            finally:
                if db:
                    await db.disconnect()
                    logger.info("Database disconnected")

        await asyncio.gather(run_web(), run_bot())
        
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        logger.error("Bot cannot start without proper configuration")
        return
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return


if __name__ == "__main__":
    asyncio.run(main())

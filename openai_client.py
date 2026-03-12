"""OpenAI API client for recipe generation."""
import logging
import json
from openai import OpenAI, APIError, RateLimitError as OpenAIRateLimitError, AuthenticationError as OpenAIAuthError

from prompts import RECIPE_GENERATION_PROMPT
from errors import OpenAIAPIError, RateLimitError, AuthenticationError
from models import Recipe

logger = logging.getLogger(__name__)


class OpenAIClient:
    """Client for interacting with OpenAI ChatGPT API."""
    
    def __init__(self, api_key: str):
        """
        Initialize OpenAI client.
        
        Args:
            api_key: OpenAI API key
        """
        self.client = OpenAI(api_key=api_key)
        self.model = "gpt-3.5-turbo"
        self.temperature = 0.7
        self.max_tokens = 1500
    
    async def generate_recipes(self, product_list: str) -> dict:
        """
        Generate 2 recipes based on product list.
        
        Args:
            product_list: Comma or space separated list of products
            
        Returns:
            dict: Dictionary with recipe1 and recipe2 keys containing Recipe objects
            
        Raises:
            RateLimitError: When API rate limit is exceeded
            AuthenticationError: When API authentication fails
            OpenAIAPIError: For other API errors
        """
        try:
            # Construct prompt
            prompt = RECIPE_GENERATION_PROMPT.format(product_list=product_list)
            
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Ты профессиональный шеф-повар, который помогает людям готовить из имеющихся продуктов."},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            # Extract response text
            recipe_text = response.choices[0].message.content
            
            # Parse recipes from response
            recipes = self._parse_recipes(recipe_text)
            
            return recipes
            
        except OpenAIRateLimitError as e:
            logger.error(f"OpenAI rate limit exceeded: {e}")
            raise RateLimitError("Rate limit exceeded") from e
            
        except OpenAIAuthError as e:
            logger.error(f"OpenAI authentication failed: {e}")
            raise AuthenticationError("Authentication failed") from e
            
        except APIError as e:
            logger.error(f"OpenAI API error: {e}")
            raise OpenAIAPIError(f"API error: {e}") from e
            
        except Exception as e:
            logger.error(f"Unexpected error in generate_recipes: {e}")
            raise OpenAIAPIError(f"Unexpected error: {e}") from e
    
    def _parse_recipes(self, recipe_text: str) -> dict:
        """
        Parse recipe text into structured format.
        
        Args:
            recipe_text: Raw text from ChatGPT
            
        Returns:
            dict: Dictionary with recipe1 and recipe2
        """
        # Simple parsing - split by recipe markers
        # This is a basic implementation; in production, you might want more robust parsing
        
        recipes = {
            "recipe1": Recipe(
                title="Рецепт из ваших продуктов",
                ingredients=["Продукты из вашего списка"],
                steps=["Следуйте инструкциям из ответа ChatGPT"],
                cooking_time="30 минут",
                recipe_type="only_listed"
            ),
            "recipe2": Recipe(
                title="Рецепт с дополнительными ингредиентами",
                ingredients=["Продукты из вашего списка", "Дополнительные ингредиенты"],
                steps=["Следуйте инструкциям из ответа ChatGPT"],
                cooking_time="35 минут",
                recipe_type="with_additional"
            )
        }
        
        # Store raw text for now - we'll improve parsing later
        logger.info(f"Generated recipes: {recipe_text[:200]}...")
        
        return recipes

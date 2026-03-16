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
    
    async def generate_recipe_image(self, recipe_title: str, ingredients: list) -> str:
        """
        Generate image for recipe using DALL-E 3.
        
        Returns:
            str: URL of generated image
        """
        ingredients_str = ", ".join(ingredients[:5])  # First 5 ingredients
        prompt = f"Professional food photography of {recipe_title}, made with {ingredients_str}. Beautiful plating, restaurant quality, natural lighting, top-down view."
        
        response = self.client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1
        )
        
        return response.data[0].url
        """
        Parse recipe text into structured format.
        
        Args:
            recipe_text: Raw text from ChatGPT (expected to be JSON)
            
        Returns:
            dict: Dictionary with recipe1 and recipe2
        """
        try:
            # Try to parse as JSON
            # Remove markdown code blocks if present
            cleaned_text = recipe_text.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text[7:]
            if cleaned_text.startswith("```"):
                cleaned_text = cleaned_text[3:]
            if cleaned_text.endswith("```"):
                cleaned_text = cleaned_text[:-3]
            cleaned_text = cleaned_text.strip()
            
            # Parse JSON
            data = json.loads(cleaned_text)
            
            # Create Recipe objects
            recipes = {
                "recipe1": Recipe(
                    title=data["recipe1"]["title"],
                    ingredients=data["recipe1"]["ingredients"],
                    steps=data["recipe1"]["steps"],
                    cooking_time=data["recipe1"]["cooking_time"],
                    recipe_type="only_listed"
                ),
                "recipe2": Recipe(
                    title=data["recipe2"]["title"],
                    ingredients=data["recipe2"]["ingredients"],
                    steps=data["recipe2"]["steps"],
                    cooking_time=data["recipe2"]["cooking_time"],
                    recipe_type="with_additional"
                )
            }
            
            logger.info(f"Successfully parsed recipes: {recipes['recipe1'].title}, {recipes['recipe2'].title}")
            return recipes
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse recipe JSON: {e}")
            logger.error(f"Raw response: {recipe_text[:500]}")
            
            # Fallback: return the raw text in a simple format
            recipes = {
                "recipe1": Recipe(
                    title="Рецепт из ваших продуктов",
                    ingredients=["См. описание ниже"],
                    steps=[recipe_text[:1000]],  # First 1000 chars
                    cooking_time="30-40 минут",
                    recipe_type="only_listed"
                ),
                "recipe2": Recipe(
                    title="Рецепт с дополнительными ингредиентами",
                    ingredients=["См. описание выше"],
                    steps=["Используйте второй рецепт из ответа"],
                    cooking_time="35-45 минут",
                    recipe_type="with_additional"
                )
            }
            
            return recipes

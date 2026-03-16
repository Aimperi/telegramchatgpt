"""Data models for Telegram Recipe Bot."""
from dataclasses import dataclass
from typing import Literal


@dataclass
class Recipe:
    """Recipe data model."""
    title: str
    ingredients: list[str]
    steps: list[str]
    cooking_time: str
    recipe_type: Literal["only_listed", "with_additional"]


@dataclass
class RecipeResponse:
    """Response containing two recipes."""
    recipe1: Recipe  # только из указанных продуктов
    recipe2: Recipe  # с дополнительными ингредиентами
    
    def to_telegram_message(self) -> str:
        """Convert recipes to Telegram Markdown format."""
        message_parts = []
        
        # Recipe 1 only
        message_parts.append("🍳 *Рецепт из ваших продуктов*\n")
        message_parts.append(f"*Название:* {self._escape_markdown(self.recipe1.title)}\n")
        message_parts.append("*Ингредиенты:*")
        for ingredient in self.recipe1.ingredients:
            message_parts.append(f"• {self._escape_markdown(ingredient)}")
        message_parts.append("\n*Приготовление:*")
        for i, step in enumerate(self.recipe1.steps, 1):
            message_parts.append(f"{i}\\. {self._escape_markdown(step)}")
        message_parts.append(f"\n⏱ *Время:* {self._escape_markdown(self.recipe1.cooking_time)}")
        
        return "\n".join(message_parts)
    
    @staticmethod
    def _escape_markdown(text: str) -> str:
        """
        Escape special characters for Telegram MarkdownV2.
        
        Args:
            text: Text to escape
            
        Returns:
            str: Escaped text
        """
        special_chars = ['_', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text

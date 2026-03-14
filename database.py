"""Database module for storing users and recipes."""
import logging
import json
from datetime import datetime
from typing import Optional, List
import asyncpg
from asyncpg import Pool

logger = logging.getLogger(__name__)


class Database:
    """PostgreSQL database manager."""
    
    def __init__(self, database_url: str):
        """
        Initialize database connection.
        
        Args:
            database_url: PostgreSQL connection URL
        """
        self.database_url = database_url
        self.pool: Optional[Pool] = None
    
    async def connect(self):
        """Create database connection pool."""
        try:
            self.pool = await asyncpg.create_pool(
                self.database_url,
                min_size=1,
                max_size=10,
                command_timeout=60
            )
            logger.info("Database connection pool created")
            await self.create_tables()
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    async def disconnect(self):
        """Close database connection pool."""
        if self.pool:
            await self.pool.close()
            logger.info("Database connection pool closed")
    
    async def create_tables(self):
        """Create database tables if they don't exist."""
        async with self.pool.acquire() as conn:
            # Users table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    first_name VARCHAR(255),
                    last_name VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Recipes table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS recipes (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id),
                    product_list TEXT NOT NULL,
                    recipe_number INTEGER NOT NULL,
                    recipe_title VARCHAR(500) NOT NULL,
                    ingredients JSONB NOT NULL,
                    steps JSONB NOT NULL,
                    cooking_time VARCHAR(100),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create index for faster queries
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_recipes_user_id 
                ON recipes(user_id)
            """)
            
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_recipes_created_at 
                ON recipes(created_at DESC)
            """)

            # Admins table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            logger.info("Database tables created/verified")
    
    async def save_user(self, user_id: int, username: str = None, 
                       first_name: str = None, last_name: str = None):
        """
        Save or update user information.
        
        Args:
            user_id: Telegram user ID
            username: Telegram username
            first_name: User's first name
            last_name: User's last name
        """
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, last_active)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (user_id) 
                DO UPDATE SET 
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    last_active = EXCLUDED.last_active
            """, user_id, username, first_name, last_name, datetime.now())
            
            logger.info(f"User {user_id} saved/updated")
    
    async def save_recipe(self, user_id: int, product_list: str, 
                         recipe_number: int, recipe_title: str,
                         ingredients: List[str], steps: List[str], 
                         cooking_time: str):
        """
        Save a generated recipe.
        
        Args:
            user_id: Telegram user ID
            product_list: Original product list from user
            recipe_number: Recipe number (1 or 2)
            recipe_title: Recipe title
            ingredients: List of ingredients
            steps: List of cooking steps
            cooking_time: Cooking time
        """
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO recipes 
                (user_id, product_list, recipe_number, recipe_title, 
                 ingredients, steps, cooking_time)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7)
            """, user_id, product_list, recipe_number, recipe_title,
                json.dumps(ingredients), json.dumps(steps), cooking_time)
            
            logger.info(f"Recipe saved for user {user_id}: {recipe_title}")
    
    async def get_user_recipes(self, user_id: int, limit: int = 10) -> List[dict]:
        """
        Get recent recipes for a user.
        
        Args:
            user_id: Telegram user ID
            limit: Maximum number of recipes to return
            
        Returns:
            List of recipe dictionaries
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, product_list, recipe_number, recipe_title,
                       ingredients, steps, cooking_time, created_at
                FROM recipes
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
            """, user_id, limit)
            
            return [dict(row) for row in rows]
    
    async def get_total_users(self) -> int:
        """Get total number of users."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM users")
    
    async def get_total_recipes(self) -> int:
        """Get total number of generated recipes."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM recipes")

    async def get_admin(self, username: str) -> Optional[dict]:
        """Get admin by username."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, username, password_hash FROM admins WHERE username = $1",
                username
            )
            return dict(row) if row else None

    async def create_default_admin(self, username: str, password: str):
        """Create default admin if no admins exist."""
        import bcrypt
        async with self.pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM admins")
            if count == 0:
                password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                await conn.execute(
                    "INSERT INTO admins (username, password_hash) VALUES ($1, $2)",
                    username, password_hash
                )
                logger.info(f"Default admin '{username}' created")

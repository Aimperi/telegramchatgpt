# Requirements Document

## Introduction

Telegram-бот «Что приготовить из продуктов» — это интеллектуальный помощник, который помогает пользователям находить рецепты на основе имеющихся у них продуктов. Бот интегрируется с ChatGPT API для генерации персонализированных рецептов и развертывается на платформе Railway для обеспечения непрерывной работы.

## Glossary

- **Recipe_Bot**: Telegram-бот, который принимает список продуктов и возвращает рецепты
- **User**: Пользователь Telegram, взаимодействующий с ботом
- **Product_List**: Текстовое сообщение от пользователя, содержащее список продуктов
- **ChatGPT_Service**: Внешний сервис OpenAI API для генерации рецептов
- **Recipe_Response**: Структурированный ответ с двумя рецептами
- **Railway_Platform**: Облачная платформа для развертывания и хостинга бота
- **Bot_Token**: Токен аутентификации Telegram Bot API
- **API_Key**: Ключ доступа к OpenAI API

## Requirements

### Requirement 1: Bot Initialization

**User Story:** Как пользователь, я хочу получить приветственное сообщение при первом запуске бота, чтобы понять, как им пользоваться

#### Acceptance Criteria

1. WHEN User sends /start command, THE Recipe_Bot SHALL respond with a welcome message within 2 seconds
2. THE Recipe_Bot SHALL include usage instructions in the welcome message
3. THE Recipe_Bot SHALL provide an example of product list format in the welcome message
4. THE welcome message SHALL contain text "Привет! 👨‍🍳 Напиши список продуктов, которые есть у тебя в холодильнике. Например: курица, картошка, сыр, помидоры"

### Requirement 2: Product List Processing

**User Story:** Как пользователь, я хочу отправить список продуктов и получить рецепты, чтобы приготовить блюдо из имеющихся ингредиентов

#### Acceptance Criteria

1. WHEN User sends Product_List, THE Recipe_Bot SHALL accept text messages up to 300 characters
2. WHEN Product_List is received, THE Recipe_Bot SHALL send the request to ChatGPT_Service
3. WHEN Product_List is empty or contains only whitespace, THE Recipe_Bot SHALL respond with "Пожалуйста отправьте список продуктов."
4. THE Recipe_Bot SHALL process Product_List containing comma-separated or space-separated product names
5. WHEN ChatGPT_Service returns recipes, THE Recipe_Bot SHALL format and send Recipe_Response to User within 10 seconds

### Requirement 3: ChatGPT Integration

**User Story:** Как система, я хочу генерировать персонализированные рецепты через ChatGPT API, чтобы предоставить пользователям релевантные кулинарные предложения

#### Acceptance Criteria

1. WHEN Recipe_Bot sends request to ChatGPT_Service, THE Recipe_Bot SHALL include Product_List in the prompt
2. THE Recipe_Bot SHALL request exactly 2 recipes from ChatGPT_Service
3. THE Recipe_Bot SHALL specify in prompt that Recipe 1 uses only products from Product_List
4. THE Recipe_Bot SHALL specify in prompt that Recipe 2 may include additional ingredients
5. THE Recipe_Bot SHALL request the following fields for each recipe: название блюда, ингредиенты, пошаговый рецепт, время приготовления
6. THE Recipe_Bot SHALL use API_Key for authentication with ChatGPT_Service

### Requirement 4: Recipe Response Formatting

**User Story:** Как пользователь, я хочу получить структурированный и читаемый ответ с рецептами, чтобы легко следовать инструкциям по приготовлению

#### Acceptance Criteria

1. THE Recipe_Response SHALL contain exactly 2 recipes
2. THE Recipe_Response SHALL label first recipe as "Рецепт №1 (только из указанных продуктов)"
3. THE Recipe_Response SHALL label second recipe as "Рецепт №2 (с дополнительными ингредиентами)"
4. FOR EACH recipe, THE Recipe_Response SHALL include название блюда
5. FOR EACH recipe, THE Recipe_Response SHALL include список ингредиентов
6. FOR EACH recipe, THE Recipe_Response SHALL include пошаговое приготовление
7. FOR EACH recipe, THE Recipe_Response SHALL include время приготовления
8. THE Recipe_Response SHALL use Telegram markdown formatting for readability

### Requirement 5: Error Handling

**User Story:** Как пользователь, я хочу получать понятные сообщения об ошибках, чтобы знать, что делать в случае проблем

#### Acceptance Criteria

1. IF ChatGPT_Service is unavailable, THEN THE Recipe_Bot SHALL respond with "Сервис рецептов временно недоступен. Попробуйте позже."
2. IF ChatGPT_Service returns rate limit error, THEN THE Recipe_Bot SHALL respond with "Сервис рецептов временно недоступен. Попробуйте позже."
3. IF ChatGPT_Service returns authentication error, THEN THE Recipe_Bot SHALL log the error and respond with "Сервис рецептов временно недоступен. Попробуйте позже."
4. IF Product_List exceeds 300 characters, THEN THE Recipe_Bot SHALL respond with "Список продуктов слишком длинный. Пожалуйста, сократите до 300 символов."
5. THE Recipe_Bot SHALL continue operation after handling any error

### Requirement 6: Configuration Management

**User Story:** Как администратор, я хочу управлять конфигурацией бота через переменные окружения, чтобы безопасно хранить секретные данные

#### Acceptance Criteria

1. THE Recipe_Bot SHALL read Bot_Token from environment variable BOT_TOKEN
2. THE Recipe_Bot SHALL read API_Key from environment variable OPENAI_API_KEY
3. IF Bot_Token is not set, THEN THE Recipe_Bot SHALL fail to start with descriptive error message
4. IF API_Key is not set, THEN THE Recipe_Bot SHALL fail to start with descriptive error message
5. THE Recipe_Bot SHALL support loading environment variables from .env file for local development

### Requirement 7: Railway Deployment

**User Story:** Как администратор, я хочу развернуть бота на Railway Platform, чтобы обеспечить непрерывную работу без локальной установки

#### Acceptance Criteria

1. THE Recipe_Bot SHALL be deployable to Railway_Platform via GitHub repository
2. THE Recipe_Bot SHALL include Procfile with command "worker: python bot.py"
3. THE Recipe_Bot SHALL include requirements.txt with dependencies: aiogram, openai, python-dotenv, fastapi, uvicorn
4. WHEN deployed to Railway_Platform, THE Recipe_Bot SHALL automatically install dependencies from requirements.txt
5. WHEN deployed to Railway_Platform, THE Recipe_Bot SHALL start automatically using Procfile configuration
6. THE Recipe_Bot SHALL run continuously on Railway_Platform without manual intervention

### Requirement 8: Project Structure

**User Story:** Как разработчик, я хочу иметь четкую структуру проекта, чтобы легко ориентироваться в коде и поддерживать его

#### Acceptance Criteria

1. THE Recipe_Bot project SHALL include bot.py file containing main bot logic
2. THE Recipe_Bot project SHALL include openai_client.py file containing ChatGPT_Service integration
3. THE Recipe_Bot project SHALL include prompts.py file containing prompt templates
4. THE Recipe_Bot project SHALL include requirements.txt file listing all dependencies
5. THE Recipe_Bot project SHALL include Procfile for Railway_Platform deployment
6. THE Recipe_Bot project SHALL include railway.json for Railway_Platform configuration
7. THE Recipe_Bot project SHALL include .env.example file with example environment variables
8. THE Recipe_Bot project SHALL include README.md with setup and deployment instructions

### Requirement 9: Technology Stack

**User Story:** Как разработчик, я хочу использовать современные и надежные технологии, чтобы обеспечить качество и поддерживаемость кода

#### Acceptance Criteria

1. THE Recipe_Bot SHALL use Python version 3.11 or higher
2. THE Recipe_Bot SHALL use aiogram library for Telegram Bot API integration
3. THE Recipe_Bot SHALL use openai library for ChatGPT_Service integration
4. THE Recipe_Bot SHALL use python-dotenv library for environment variable management
5. WHERE webhook mode is enabled, THE Recipe_Bot SHALL use fastapi and uvicorn libraries

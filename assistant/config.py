from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    shop_name: str = "ZooMarket"

    # sqlite для локального запуску; postgresql+psycopg://... для pgvector
    database_url: str = "sqlite:///data/assistant.sqlite"

    # без ключа асистент працює в "локальному" режимі: пошук BM25 і відповідь фрагментом з бази знань
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    # нижче цієї оцінки релевантності питання передається оператору
    min_score: float = 0.45

    # API магазину для статусу замовлення і повернень
    shop_api_url: str = ""
    shop_api_token: str = ""

    telegram_token: str = ""
    operators_chat_id: str = ""     # куди слати питання, на які бот не знає відповіді
    viber_token: str = ""

    admin_user: str = "admin"
    admin_password: str = "admin"


settings = Settings()

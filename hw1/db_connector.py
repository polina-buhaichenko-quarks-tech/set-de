import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    """Return a new MySQL connection using .env credentials."""
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 3306)),
        database=os.getenv("DB_NAME", "db_name"),
        user=os.getenv("DB_USER", "user"),
        password=os.getenv("DB_PASSWORD", "password"),
    )
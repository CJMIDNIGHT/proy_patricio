"""
Motor SQLAlchemy y URL de conexión desde variables de entorno (.env).
"""

import os
from functools import lru_cache
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

# Cargar .env desde el directorio de este paquete (patricio_web/)
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))


def _database_url() -> str:
    url = os.getenv('DATABASE_URL')
    if url:
        return url
    host = os.getenv('MYSQL_HOST', '127.0.0.1')
    port = int(os.getenv('MYSQL_PORT', '3306'))
    user = os.getenv('MYSQL_USER', 'patricio')
    password = os.getenv('MYSQL_PASSWORD', '')
    database = os.getenv('MYSQL_DATABASE', 'patricio_db')
    safe = quote_plus(password, safe='')
    return f'mysql+pymysql://{quote_plus(user, safe="")}:{safe}@{host}:{port}/{database}'


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(
        _database_url(),
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=os.getenv('SQL_ECHO', '').lower() in ('1', 'true', 'yes'),
    )


def get_session_factory():
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)


def get_db() -> Session:
    """Contexto típico: session = get_db(); try: ... finally: session.close()"""
    return get_session_factory()()

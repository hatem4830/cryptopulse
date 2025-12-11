
from typing import Optional
import os
from sqlmodel import SQLModel, create_engine, Session
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dev.db")

# echo can be enabled by setting SQLALCHEMY_ECHO=1 in env
ECHO = bool(int(os.getenv("SQLALCHEMY_ECHO", "0")))

engine = create_engine(DATABASE_URL, echo=ECHO, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)

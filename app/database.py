import os, sys
from typing import Annotated
from sqlmodel import SQLModel, create_engine
from fastapi import Depends
from sqlmodel import Session

from .models import user
from .models import organization
from .models import build
from .models import team

db_url = ""
try:
    db_url = os.environ['DB_URL']
except KeyError:
    print("Error: The 'DB_URL' environment variable must be set.", file=sys.stderr)
    sys.exit(1)

engine = create_engine(db_url, echo=True)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

DbSessionDep = Annotated[Session, Depends(get_session)]
import uvicorn
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from contextlib import asynccontextmanager
from .database import create_db_and_tables
from .api import organization, team, user, build, profile, roles
from .setup import create_initial_roles_and_permissions
from .database import engine
from . import auth

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    create_initial_roles_and_permissions(engine)
    yield

app = FastAPI(lifespan=lifespan)
app.include_router(organization.router)
app.include_router(team.router)
app.include_router(user.router)
app.include_router(build.router)
app.include_router(profile.router)
app.include_router(roles.router)
app.include_router(auth.router)

@app.get("/")
def read_root():
    return {"Hello": "World"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
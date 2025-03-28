import uuid
from typing import List, Dict, Optional
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, status, Request, Depends
from src.llm_handler.gemini_client import Assistant
from src.config.settings import settings
from loguru import logger
import redis.asyncio as redis

# Global variable to hold redis connectio
redis_pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize Redis pool
    global redis_pool
    logger.info(f"Connecting to redis at {settings.REDIS_HOST}:{settings.REDIS_PORT}")
    try:
        redis_pool = redis.ConnectionPool(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD,
            decode_responses=True  # Decode key values from bytes to strings
        )
        # Test connectino
        r = redis.Redis(connection_pool=redis_pool)
        await r.ping()
        logger.info(f"Successfully connected to Redis and pinged.")
        await r.close()
    except Exception as e:
        logger.exception(f"Failed to connect to Redis: {e}")
        #TODO : decide to fail the api startup or continue
    
    yield

    # Teardown
    logger.info("Closing Redis connection pool.")
    if redis_pool:
        await redis_pool.disconnect()
    
    logger.info("Redis connection pool terminated.")

async def get_redis():
    if not redis_pool:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Redis connection not available")
    return redis.Redis(connection_pool=redis_pool)


# Instantiate FastAPI with lifespan
app = FastAPI(lifespan=lifespan)

# Define Response models
class LLMRequest(BaseModel):    
    query: str
    session_id: Optional[str] = None


class LLMResponse(BaseModel):
    response_str: str
    session_id: str


# API Endpoints  
@app.post("/chat", response_model=LLMResponse)
async def handle_chat(
    request_data: LLMRequest,
    redis_client: redis.Redis = Depends(get_redis)
):
    logger.info(f"Recieved request for session: {request_data.session_id or 'New Session'}")
    session_id = request_data.session_id
    is_new_session = False

    try:
        if session_id:
            # Check if session exists 
            session_exits = await redis_client.exists(session_id)
            if session_exits:
                logger.info(f"Existing session ID '{session_id}' found in Redis")
                await redis_client.expire(session_id, settings.SESSION_TTL_SECONDS)
            else:
                logger.info("Provided session ID not found or expired, generating a new session")
                session_id = None  # Treat as new session 

        if not session_id: 
            # Generate a session id
            session_id = str(uuid.uuid4())
            is_new_session = True
            # Store the new session ID in redis with TTL
            # Using SETEX: SETEX key seconds value
            # Simple value '1' indicating existence 
            await redis_client.setex(session_id, settings.SESSION_TTL_SECONDS, 1)
            logger.info(f"Generated and stored new seesion ID '{session_id} with TTL {settings.SESSION_TTL_SECONDS}")

        # Core Logic 
        # Instantiate the Assistant class
        assistant = Assistant(session_id=session_id)

        # Call core logic 
        # TODO: await this response 
        llm_response_str = assistant.ask(query=request_data.query)

        logger.info(f"Response generated for session: {request_data.session_id}")

        # Return successful response
        response = LLMResponse(
            response_str=llm_response_str, 
            session_id=session_id
        )

        return response
    except redis.RedisError as e:
        logger.exception(f"Redis erro during request processing: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Session sevice unavailable (Redis Error): {e}"
        )
    except Exception as e:
        logger.error(f"Error processing request for session: {request_data.session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal Server error: {e}"
        )
    





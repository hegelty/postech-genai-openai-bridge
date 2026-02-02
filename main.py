import json
import os
import uuid
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="POSTECH GenAI OpenAI Bridge")

# Configuration
POSTECH_BASE_URL = os.getenv("POSTECH_BASE_URL", "https://genai.postech.ac.kr/agent/api")
POSTECH_API_KEY = os.getenv("POSTECH_API_KEY", "")
PROXY_HOST = os.getenv("PROXY_HOST", "http://localhost:8080")
TMP_DIR = Path("./tmp")
TMP_DIR.mkdir(exist_ok=True)

# Model routing
MODEL_ENDPOINTS = {
    "postech-gpt": "a1/gpt",
    "postech-gemini": "a2/gemini",
    "postech-claude": "a3/claude",
}
DEFAULT_MODEL = "postech-gpt"


# Pydantic models
class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = DEFAULT_MODEL
    messages: list[Message]
    stream: bool = False


class FileInfo(BaseModel):
    id: str
    name: str
    url: str


# File storage
stored_files: dict[str, dict] = {}


@app.get("/v1/models")
def list_models():
    models = [
        {"id": model_id, "object": "model", "owned_by": "postech"}
        for model_id in MODEL_ENDPOINTS.keys()
    ]
    return {"object": "list", "data": models}


@app.post("/v1/files")
async def upload_file(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    file_path = TMP_DIR / file_id
    
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    stored_files[file_id] = {
        "id": file_id,
        "name": file.filename,
        "path": str(file_path),
    }
    
    return {
        "id": file_id,
        "name": file.filename,
        "url": f"{PROXY_HOST}/files/{file_id}",
    }


@app.get("/files/{file_id}")
def get_file(file_id: str):
    if file_id not in stored_files:
        raise HTTPException(status_code=404, detail="File not found")
    
    file_info = stored_files[file_id]
    return FileResponse(
        path=file_info["path"],
        filename=file_info["name"],
    )


def convert_messages_to_prompt(messages: list[Message]) -> str:
    lines = []
    for msg in messages:
        role = msg.role.upper()
        lines.append(f"{role}: {msg.content}")
    return "\n".join(lines)


def call_postech_api(endpoint: str, prompt: str, files: list[FileInfo] = None) -> str:
    url = f"{POSTECH_BASE_URL}/{endpoint}"
    
    payload = {
        "message": prompt,
        "stream": False,
        "files": [f.model_dump() for f in files] if files else [],
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-Api-Key": POSTECH_API_KEY,
    }
    
    response = requests.post(url, json=payload, headers=headers, timeout=120)
    response.raise_for_status()
    
    data = response.json()
    return data.get("replies", "")


async def save_uploaded_file(file: UploadFile) -> FileInfo:
    """Save uploaded file and return FileInfo for POSTECH API."""
    file_id = str(uuid.uuid4())
    file_path = TMP_DIR / file_id

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    stored_files[file_id] = {
        "id": file_id,
        "name": file.filename,
        "path": str(file_path),
    }

    return FileInfo(
        id=file_id,
        name=file.filename or "file",
        url=f"{PROXY_HOST}/files/{file_id}",
    )


def generate_stream_response(reply: str, model: str, completion_id: str):
    """Generate SSE stream chunks for streaming response."""
    created = int(time.time())

    # Send the content in a single chunk (since POSTECH API doesn't support streaming)
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "content": reply,
                },
                "finish_reason": None,
            }
        ],
    }
    yield f"data: {json.dumps(chunk)}\n\n"

    # Send finish chunk
    finish_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
    }
    yield f"data: {json.dumps(finish_chunk)}\n\n"

    # Send done signal
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    model: Optional[str] = Form(None),
    messages: Optional[str] = Form(None),
    stream: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    # Detect content type and parse accordingly
    content_type = request.headers.get("content-type", "")
    is_stream = False

    if "multipart/form-data" in content_type:
        # Form data request
        if not messages:
            raise HTTPException(status_code=400, detail="messages field is required")
        try:
            parsed_messages = [Message(**m) for m in json.loads(messages)]
        except (json.JSONDecodeError, TypeError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid messages format: {e}")
        model = model or DEFAULT_MODEL
        is_stream = stream and stream.lower() == "true"
    else:
        # JSON request
        body = await request.json()
        model = body.get("model", DEFAULT_MODEL)
        parsed_messages = [Message(**m) for m in body.get("messages", [])]
        is_stream = body.get("stream", False)

    # Validate model
    if model not in MODEL_ENDPOINTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid model: {model}. Available: {list(MODEL_ENDPOINTS.keys())}",
        )

    # Handle file upload
    files_for_api: list[FileInfo] = []
    if file and file.filename:
        file_info = await save_uploaded_file(file)
        files_for_api.append(file_info)

    endpoint = MODEL_ENDPOINTS[model]
    prompt = convert_messages_to_prompt(parsed_messages)

    # Call POSTECH API
    try:
        reply = call_postech_api(endpoint, prompt, files_for_api)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"POSTECH API error: {str(e)}")

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # Return streaming response if requested
    if is_stream:
        return StreamingResponse(
            generate_stream_response(reply, model, completion_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    # Build OpenAI-compatible response (non-streaming)
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": reply,
                },
                "finish_reason": "stop",
            }
        ],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)


# POSTECH GenAI OpenAI Bridge

POSTECH 내부 GenAI API를 OpenAI-compatible API로 변환하는 프록시 서버입니다.

JetBrains AI Assistant (BYOK) 등 OpenAI API를 지원하는 도구에서 POSTECH GenAI를 사용할 수 있습니다.

## 지원 모델

| 모델명 | POSTECH 엔드포인트     |
|--------|-------------------|
| `postech-gpt` | GPT 5.1           |
| `postech-gemini` | Gemini 3 Pro      |
| `postech-claude` | Claude Sonnet 4.5 |

## 설치

```bash
uv sync
```

## 설정

```bash
cp .env.example .env
```

`.env` 파일 편집:

```
POSTECH_API_KEY=your-api-key
PROXY_HOST=https://your-public-url  # 파일 업로드 시 필요
```

## 실행

```bash
uv run python main.py
```

또는

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8080
```

서버가 `http://localhost:8080`에서 실행됩니다.

## JetBrains AI Assistant 설정

1. Settings → Tools → AI Assistant
2. Provider: **OpenAI-compatible**
3. Base URL: `http://localhost:8080/v1`
4. API Key: 아무 값
5. Model: `postech-gpt`, `postech-gemini`, `postech-claude` 중 선택

## API 엔드포인트

- `GET /v1/models` - 모델 목록
- `POST /v1/chat/completions` - 채팅 완성
- `POST /v1/files` - 파일 업로드
- `GET /files/{id}` - 파일 다운로드

## 파일 업로드 사용 시

POSTECH API가 파일 URL에 접근해야 하므로, 프록시 서버가 공개적으로 접근 가능해야 합니다.

```bash
# ngrok으로 로컬 서버 노출
ngrok http 8080

# .env에 ngrok URL 설정
PROXY_HOST=https://xxxx.ngrok.io
```


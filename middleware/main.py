from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from middleware.config import settings
from middleware.routes import router

app = FastAPI(title="Marketing Intelligence Copilot API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {
                    "loc": item["loc"],
                    "msg": item["msg"],
                    "type": item["type"],
                }
                for item in error.errors()
            ]
        },
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

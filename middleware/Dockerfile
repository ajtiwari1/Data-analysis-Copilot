FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY middleware ./middleware
COPY chat ./chat

EXPOSE 8000

CMD ["sh", "-c", "alembic -c middleware/alembic.ini upgrade head && uvicorn middleware.main:app --host 0.0.0.0 --port 8000"]

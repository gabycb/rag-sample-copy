# ATLAS-RAG Bot Service Container
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose FastAPI port for Bot Service webhook
EXPOSE 8000

# Run with uvicorn
# Bot Service sends messages to http://{container-app-url}/api/messages
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

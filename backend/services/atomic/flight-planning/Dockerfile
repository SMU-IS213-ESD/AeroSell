FROM python:3.11-slim

WORKDIR /usr/src/app

# Install dependencies first (separate layer for better caching)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

EXPOSE 8004

CMD ["python", "run.py"]
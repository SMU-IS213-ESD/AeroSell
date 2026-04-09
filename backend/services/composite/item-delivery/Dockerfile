FROM python:3-slim
WORKDIR /usr/src/app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
ENV PYTHONUNBUFFERED=1
COPY ./app/ ./app/
WORKDIR /usr/src/app/app
CMD [ "python", "./run.py" ]
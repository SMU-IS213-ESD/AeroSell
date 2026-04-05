FROM python:3-slim
WORKDIR /usr/src/app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY ./app/run.py ./
COPY ./app/drone.sql ./
CMD [ "python", "./run.py" ]
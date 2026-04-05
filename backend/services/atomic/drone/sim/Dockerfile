FROM python:3-slim
WORKDIR /usr/src/app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY simulate_drone.py ./
CMD [ "python", "./simulate_drone.py" ]

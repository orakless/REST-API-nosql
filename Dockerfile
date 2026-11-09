FROM python:3.12.0

WORKDIR /app

COPY . .

RUN pip install -r requirements.txt
RUN pip install gunicorn

EXPOSE 5000

#ENV REDIS_URL=host.docker.internal
#ENV DB_HOST=host.docker.internal
#ENV DB_USER=postgres
#ENV DB_PASSWORD=toto
#ENV DB_PORT=5432
#ENV DB_NAME=API_REST
ENV FLASK_APP=inf349
#ENV FLASK_DEBUG=1

CMD ["flask", "run", "--host", "0.0.0.0"]
#CMD ["gunicorn", "-w", "4", "inf349:app"]

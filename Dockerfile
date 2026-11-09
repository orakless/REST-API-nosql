FROM python:3.15

WORKDIR /app

COPY . .

RUN pip install -r requirements.txt
RUN pip install gunicorn

ENV FLASK_APP=inf349

CMD ["flask", "run", "--host", "0.0.0.0"]
#CMD ["gunicorn", "-w", "4", "inf349:app"]

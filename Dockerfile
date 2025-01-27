FROM python:latest
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt 
EXPOSE 5001 
ENTRYPOINT ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]
ARG ADC_PYTHON_IMAGE=python:3.12-slim-bookworm
FROM ${ADC_PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home adc
COPY backend/ ./
COPY contracts/ /contracts/
ENV CONTRACTS_DIR=/contracts
USER adc
EXPOSE 8000
CMD ["gunicorn","adc.wsgi:application","--bind","0.0.0.0:8000","--workers","2","--timeout","60","--access-logfile","-","--access-logformat","%(m)s %(U)s %(s)s %(L)s"]

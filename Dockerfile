# syntax=docker/dockerfile:1
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    GEOAPI_DATA_DIR=/data

WORKDIR /app

# The pyogrio, shapely, pyproj and rasterio wheels bundle GDAL, GEOS and PROJ, so no system
# geospatial libraries are needed. rasterio's wheel still links against the system libexpat,
# which the slim base image does not include.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# The cache mount keeps downloaded wheels across builds without adding them to the image.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --retries 10 -r requirements.txt

COPY app ./app

RUN useradd --create-home --uid 1000 appuser && mkdir /data && chown appuser /data
USER appuser
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.13-slim

RUN apt-get update \
	&& apt-get install --yes --no-install-recommends poppler-utils \
	&& rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml VERSION API_COMPARISON.md ./
COPY src/ .
RUN pip install --no-cache-dir .
ARG DEPLOY_DATE=unknown
ENV DEPLOY_DATE=$DEPLOY_DATE
ARG PORT
ENV PORT=$PORT

RUN useradd --create-home appuser
USER appuser

EXPOSE $PORT
CMD ["python", "main.py"]

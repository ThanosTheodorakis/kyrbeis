# Kyrbeis collector: keeps a clone of your GitHub repository and collects every day.
# Build and run with docker compose (see the README): docker compose up -d --build
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Athens \
    KYRBEIS_REPO_DIR=/repo \
    GIT_ASKPASS=/usr/local/bin/git-askpass \
    GIT_TERMINAL_PROMPT=0 \
    GIT_AUTHOR_NAME="Kyrbeis bot" \
    GIT_AUTHOR_EMAIL="kyrbeis-bot@users.noreply.github.com" \
    GIT_COMMITTER_NAME="Kyrbeis bot" \
    GIT_COMMITTER_EMAIL="kyrbeis-bot@users.noreply.github.com"

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY scraper/ scraper/
RUN pip install --no-cache-dir .

COPY docker/git-askpass.sh /usr/local/bin/git-askpass
# strip Windows line endings in case the file was edited on Windows
RUN sed -i 's/\r$//' /usr/local/bin/git-askpass && chmod +x /usr/local/bin/git-askpass

# run as an ordinary user; /repo holds the clone (a Docker volume)
RUN useradd --create-home --uid 1000 kyrbeis && mkdir /repo && chown kyrbeis /repo
USER kyrbeis
VOLUME /repo

ENTRYPOINT ["python", "-m", "scraper.runner"]
CMD ["serve"]

FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        texlive-xetex \
        && rm -rf /var/lib/apt/lists/*

# Install tectonic
RUN curl --proto '=https' --tlsv1.2 -sSf https://tectonic-typesetting.github.io/Public/installation-gateway.sh | sh -s -- -bs /usr/local/bin

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ src/
COPY pyproject.toml .

# Install the package
RUN pip install --no-cache-dir -e .

WORKDIR /data

ENTRYPOINT ["jobtailor"]

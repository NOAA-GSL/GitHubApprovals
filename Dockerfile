# Use a lightweight Ubuntu 22.04 base image
FROM ubuntu:22.04

# Set environment variables to avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Denver

# Install Python, nano, and other dependencies
RUN apt-get update && \
    apt-get install -y python3 python3-pip build-essential libssl-dev libffi-dev python3-dev tzdata nano && \
    apt-get install -y libatlas-base-dev && \
    apt-get install -y supervisor && \
    apt-get clean

# Copy requirements files first (for better caching)
COPY requirements.txt /tmp/requirements.txt
COPY requirements-dev.txt /tmp/requirements-dev.txt

# Install the Python dependencies from requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# Install development/testing dependencies (useful for CI/CD)
# These will be available in the container for running tests
RUN pip3 install --no-cache-dir -r /tmp/requirements-dev.txt

# Copy the approvals.py file into the root directory of the container
COPY approvals.py /approvals.py
COPY verification_progress_gif.py /verification_progress_gif.py
#NOTE: flipping this copy you can test a green or blue version of the code
#COPY blue_version.py /approvals.py

# Copy supervisor config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

#Copy the notifications files into the root directory of the container
COPY dependabotalerts.py /dependabotalerts.py
COPY dependabotalerts_runner.py /dependabotalerts_runner.py
COPY lab_sponsors.csv /lab_sponsors.csv

# Copy migration script for database setup
COPY migrate_csv_to_db.py /migrate_csv_to_db.py

# Keep CSV in root for backward compatibility and as migration source
COPY informationowners.csv /informationowners.csv

# Create the necessary directories
RUN mkdir -p /data /templates /images

# Also copy to /data (for new deployments without existing volume data)
# Note: If volume already has this file, the volume mount will overlay this
COPY informationowners.csv /data/informationowners.csv

# Copy the templates and images into the root directory of the container
COPY templates /templates
COPY images /images
#COPY agreement.db /data/agreement.db
#COPY .env /.env

# Expose port 8000
EXPOSE 8000

# Command to run the application
#CMD ["python3", "/approvals.py"]
# Command to run the application
#CMD ["uvicorn", "approvals:app", "--host", "0.0.0.0", "--port", "8000"]
#CMD ["uvicorn", "sponsor_first_test:app", "--host",  "0.0.0.0", "--port", "8000" ]
CMD ["/usr/bin/supervisord"]

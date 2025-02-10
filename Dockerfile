# Use a lightweight Ubuntu 22.04 base image
FROM ubuntu:22.04

# Set environment variables to avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Denver

# Set environment variables to avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install Python and other dependencies
RUN apt-get update && \
    apt-get install -y python3 python3-pip build-essential libssl-dev libffi-dev python3-dev tzdata && \
    apt-get install -y libatlas-base-dev && \
    apt-get clean

# Install the Python dependencies directly
RUN pip3 install fastapi==0.88.0 \
                 uvicorn==0.18.3 \
                 jinja2==3.1.5 \
                 sqlalchemy==1.4.41 \
                 apscheduler==3.9.1 \
                 python-dotenv==0.21.0 \
                 numpy==1.22 \
                 pandas==1.3.5 \
                 pydantic>=1.10.13 \
                 python-multipart==0.0.5

# Copy the approvals.py file into the root directory of the container
COPY approvals.py /approvals.py

# Create the necessary directories
RUN mkdir -p /data /templates /images

# Copy the templates and images into the root directory of the container
COPY templates /templates
COPY images /images
#COPY .env /.env

# Expose port 8000
EXPOSE 8000

# Command to run the application
CMD ["python3", "/approvals.py"]

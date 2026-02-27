# Use a lightweight Python image
FROM python:3.10-slim

# Set the working directory
WORKDIR /app

# Copy all your local files into the container
COPY . /app

# Install the required packages
RUN pip install --no-cache-dir -r requirements.txt

# Run the app using Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "120", "app:app"]

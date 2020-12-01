# Use the Python 3.7.9 image
#FROM python:3.7.9-stretch
FROM ubuntu:20.04

## Install system packages
ENV DEBIAN_FRONTEND=noninteractive
# Install packages for apt repo and dependencies
RUN apt-get -qq update \
    && apt-get upgrade -y \
    && apt-get -qq install --no-install-recommends -y \
        wget \
    && apt-get -qq install --no-install-recommends -y \
        python3-pip \
    && apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && (apt-get autoremove -y; apt-get autoclean -y)

# set the working directory
WORKDIR /app

# Copy the current directory contents into the container at /app
ADD . /app

# Install required python modules
RUN pip3 install -r requirements.txt
 
# run the app
CMD ["python3", "-u", "nvr.py"]
#!/bin/bash
echo "Starting Apex Retail Store Intelligence Pipeline Sighting Stream..."
python "$(dirname "$0")/detect.py" --simulate

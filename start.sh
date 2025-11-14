#!/bin/bash

# Start Flask keep-alive web server on Render's assigned port
gunicorn monsta_sports_bot:app --bind 0.0.0.0:$PORT &

# Start the betting bot loop
python3 monsta_sports_bot.py


@echo off
cd backend
python -m pip install -r requirements.txt
start http://localhost:5000
python app.py

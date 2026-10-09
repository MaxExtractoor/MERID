@echo off
cd /d C:\Dev\MERID
py -m pytest tests/sentiment/test_sentiment_pipeline.py -v
pause

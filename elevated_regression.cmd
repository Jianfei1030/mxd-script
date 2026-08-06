@echo off
cd /d H:\ok-mxd\ok-mxd
set PYTHONIOENCODING=utf-8
"H:\ok-mxd\data\apps\ok-ww\python\python.exe" -m unittest discover tests -v > screenshots\elevated_regression.txt 2>&1

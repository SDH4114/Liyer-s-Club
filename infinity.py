import requests
import time

target = "https://chaosnet.onrender.com/login.html"


while True:
    r = requests.get(target)
    
    time.sleep(600)
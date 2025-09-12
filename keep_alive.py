from flask import Flask
from threading import Thread
import OS 

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    PORT = int(os.environ.get("PORT", 8080)) 
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

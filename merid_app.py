import requests
import tkinter as tk
from tkinter import scrolledtext, Entry, Button
import json

# Local Ollama API
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "gemma3:1b"

# CoinGecko API for BTC price (free, no key)
BTC_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true"

def get_btc_price():
    try:
        data = requests.get(BTC_PRICE_URL, timeout=5).json()
        price = data['bitcoin']['usd']
        change_24h = data['bitcoin']['usd_24h_change']
        return f"Bitcoin is currently ${price:,.2f} USD (24h change: {change_24h:+.2f}%)"
    except:
        return "Sorry, couldn't fetch the latest Bitcoin price right now (check your internet)."

def send_prompt():
    user_input = entry.get().strip()
    if not user_input:
        return
    
    # Display user message
    chat_log.insert(tk.END, "You: " + user_input + "\n")
    entry.delete(0, tk.END)
    
    # Check for Bitcoin price keywords
    lower_input = user_input.lower()
    if any(keyword in lower_input for keyword in ["bitcoin price", "btc price", "bitcoin today", "btc today", "current bitcoin", "current btc"]):
        btc_info = get_btc_price()
        chat_log.insert(tk.END, "MERID: " + btc_info + "\n\n")
        chat_log.see(tk.END)
        return
    
    # Otherwise, use local Ollama model
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": user_input}],
        "stream": False
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=30)
        response.raise_for_status()
        ai_reply = response.json()["message"]["content"]
        chat_log.insert(tk.END, "MERID: " + ai_reply + "\n\n")
    except Exception as e:
        chat_log.insert(tk.END, "MERID: Error connecting to local AI: " + str(e) + "\n\n")
    
    chat_log.see(tk.END)

# GUI Setup
root = tk.Tk()
root.title("MERID v2 - Your Local AI with Real-Time BTC")
root.geometry("700x900")
root.configure(bg="#f0f0f0")

chat_log = scrolledtext.ScrolledText(root, wrap=tk.WORD, state='normal', font=("Arial", 11))
chat_log.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

entry = Entry(root, width=60, font=("Arial", 12))
entry.pack(side=tk.LEFT, padx=10, pady=10, fill=tk.X, expand=True)

send_btn = Button(root, text="Send", command=send_prompt, bg="#4CAF50", fg="white", font=("Arial", 12))
send_btn.pack(side=tk.RIGHT, padx=10, pady=10)

chat_log.insert(tk.END, "MERID v2 is ready! (Local AI + real-time Bitcoin prices)\n")
chat_log.insert(tk.END, "Try asking: 'What's the Bitcoin price today?'\n\n")

root.bind('<Return>', lambda event: send_prompt())  # Enter key sends

root.mainloop()
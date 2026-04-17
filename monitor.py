import requests
import time

def monitor():
    headers = {"merid-access": "O2jbnfBmraDuTGDBTC0lyRBpllrWOFnxjp9qfeUFxm8"}
    while True:
        try:
            # Get portfolio status
            r = requests.get('http://localhost:8000/api/v1/kalshi-grid/matrix', headers=headers)
            if r.status_code == 200:
                data = r.json()
                print(f"Portfolio value: {data.get('total_value', 'N/A')}")
            else:
                print(f"Error getting portfolio: {r.status_code}")
            
            # Get agent performance
            r2 = requests.get('http://localhost:8000/api/v1/kalshi-grid/agents', headers=headers)
            if r2.status_code == 200:
                agents = r2.json()
                for agent in agents:
                    print(f"Agent {agent['name']}: P&L {agent.get('pnl', 'N/A')}")
            else:
                print(f"Error getting agents: {r2.status_code}")
            
        except Exception as e:
            print(f"Error: {e}")
        
        time.sleep(60)  # Monitor every minute

if __name__ == "__main__":
    monitor()

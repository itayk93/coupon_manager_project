import json
import os

def test_parsing():
    json_path = 'scrape_multipass/transactions.json'
    
    if not os.path.exists(json_path):
        print(f"File not found: {json_path}")
        return

    try:
        with open(json_path, 'r') as f:
            all_data = json.load(f)
            
        print(f"Loaded {len(all_data)} items from JSON")
        
        transaction_data_map = {}
        for item in all_data:
            c_num = item.get("card_number")
            if c_num:
                transactions = item.get("transactions", [])
                transaction_data_map[c_num] = transactions
                print(f"Card {c_num}: Found {len(transactions)} transactions")
                
                # Check specifics for the problematic card
                if c_num == "135248764-3074":
                    print(f"Details for 135248764-3074: {transactions}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_parsing()

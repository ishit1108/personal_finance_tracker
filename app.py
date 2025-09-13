import os
import json
import io
from datetime import datetime
import pandas as pd
import yfinance as yf
from flask import Flask, render_template, request, redirect, url_for, send_file, flash

# --- APP SETUP ---
app = Flask(__name__)
app.secret_key = 'your_super_secret_key' # Important for flashing messages

# --- DATA FILE CONFIGURATION ---
DATA_DIR = 'data'
TRANSACTIONS_FILE = os.path.join(DATA_DIR, 'transactions.json')
INVESTMENTS_FILE = os.path.join(DATA_DIR, 'investments.json')

# --- HELPER FUNCTIONS ---
def setup_data_files():
    """Ensure data directory and files exist."""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    if not os.path.exists(TRANSACTIONS_FILE):
        with open(TRANSACTIONS_FILE, 'w') as f:
            json.dump([], f)
    if not os.path.exists(INVESTMENTS_FILE):
        with open(INVESTMENTS_FILE, 'w') as f:
            json.dump([], f)

def load_data(file_path):
    """Load JSON data from a file."""
    with open(file_path, 'r') as f:
        return json.load(f)

def save_data(data, file_path):
    """Save data to a JSON file."""
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=4)

def get_live_price(ticker):
    """Fetch the last closing price for a given ticker."""
    if not ticker or ticker.lower() == 'n/a':
        return 1.0 # For FDs or manual entries
    try:
        stock = yf.Ticker(ticker)
        # Use 'previousClose' or 'regularMarketPrice' for more recent data
        price = stock.info.get('regularMarketPrice', stock.info.get('previousClose'))
        return price if price else 0.0
    except Exception as e:
        print(f"Could not fetch price for {ticker}: {e}")
        return 0.0

def enrich_investments_data(investments):
    """Add calculated fields like current value, gain/loss, etc."""
    enriched = []
    for inv in investments:
        current_price = get_live_price(inv['ticker'])
        purchase_price = float(inv['purchase_price'])
        units = float(inv['units'])
        
        current_value = units * current_price if current_price else 0
        gain_loss = current_value - (units * purchase_price)
        
        # Calculate holding period in months
        purchase_date = datetime.strptime(inv['purchase_date'], '%Y-%m-%d')
        holding_months = (datetime.now().year - purchase_date.year) * 12 + datetime.now().month - purchase_date.month
        
        # Determine tax status (simplified for Indian context)
        tax_status = "N/A"
        if inv['type'] == 'Stock':
            tax_status = "LTCG" if holding_months > 12 else "STCG"
        elif inv['type'] == 'Mutual Fund': # Assuming Equity funds
            tax_status = "LTCG" if holding_months > 36 else "STCG"
            
        inv_copy = inv.copy()
        inv_copy.update({
            'current_price': round(current_price, 2),
            'current_value': round(current_value, 2),
            'gain_loss': round(gain_loss, 2),
            'holding_months': holding_months,
            'tax_status': tax_status
        })
        enriched.append(inv_copy)
    return enriched

# --- FLASK ROUTES ---

@app.route('/')
def dashboard():
    """Main dashboard page."""
    transactions = load_data(TRANSACTIONS_FILE)
    investments = load_data(INVESTMENTS_FILE)
    
    # --- Calculations ---
    df_trans = pd.DataFrame(transactions)
    total_income = df_trans[df_trans['type'] == 'Income']['amount'].sum() if not df_trans.empty else 0
    total_spends = df_trans[df_trans['type'] != 'Income']['amount'].sum() if not df_trans.empty else 0
    
    enriched_investments = enrich_investments_data(investments)
    portfolio_value = sum(inv['current_value'] for inv in enriched_investments)
    
    # This is a simplification; a real bank balance would need an opening balance.
    bank_balance = total_income - total_spends
    net_worth = bank_balance + portfolio_value

    # For the spending chart
    spend_categories = {}
    if not df_trans.empty:
        spends_df = df_trans[df_trans['type'] != 'Income']
        category_summary = spends_df.groupby('category')['amount'].sum().abs().to_dict()
        spend_categories = json.dumps(category_summary)

    return render_template('dashboard.html',
                           net_worth=net_worth,
                           bank_balance=bank_balance,
                           portfolio_value=portfolio_value,
                           spend_categories_data=spend_categories)

@app.route('/transactions', methods=['GET', 'POST'])
def transactions_page():
    """Page to view and add transactions."""
    transactions = load_data(TRANSACTIONS_FILE)
    
    if request.method == 'POST':
        new_trans = {
            'date': request.form['date'],
            'description': request.form['description'],
            'category': request.form['category'],
            'type': request.form['type'],
            'amount': float(request.form['amount'])
        }
        transactions.append(new_trans)
        save_data(transactions, TRANSACTIONS_FILE)
        flash('Transaction added successfully!', 'success')
        return redirect(url_for('transactions_page'))
        
    # Sort transactions by date for display
    sorted_transactions = sorted(transactions, key=lambda x: x['date'], reverse=True)
    return render_template('transactions.html', transactions=sorted_transactions)

@app.route('/investments', methods=['GET', 'POST'])
def investments_page():
    """Page to view and add investments."""
    investments = load_data(INVESTMENTS_FILE)
    
    if request.method == 'POST':
        amount = float(request.form['amount_invested'])
        price = float(request.form['purchase_price'])
        units = amount / price if price > 0 else 0
        
        new_inv = {
            'purchase_date': request.form['purchase_date'],
            'name': request.form['name'],
            'ticker': request.form['ticker'].upper(),
            'type': request.form['type'],
            'amount_invested': amount,
            'purchase_price': price,
            'units': units
        }
        investments.append(new_inv)
        save_data(investments, INVESTMENTS_FILE)
        flash('Investment added successfully!', 'success')
        return redirect(url_for('investments_page'))
        
    enriched_investments = enrich_investments_data(investments)
    return render_template('investments.html', investments=enriched_investments)

@app.route('/export')
def export_excel():
    """Export all data to an Excel file."""
    transactions = load_data(TRANSACTIONS_FILE)
    investments = load_data(INVESTMENTS_FILE)
    enriched_investments = enrich_investments_data(investments)

    # Use BytesIO to create the Excel file in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame(transactions).to_excel(writer, sheet_name='Transactions', index=False)
        pd.DataFrame(enriched_investments).to_excel(writer, sheet_name='Investment_Portfolio', index=False)
    output.seek(0)
    
    return send_file(output,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     download_name='financial_report.xlsx',
                     as_attachment=True)

# --- INITIALIZATION ---
if __name__ == '__main__':
    setup_data_files()
    app.run(debug=True)

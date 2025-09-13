import os
import json
import io
import uuid
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf
import requests
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, jsonify

# --- APP SETUP ---
app = Flask(__name__)
app.secret_key = 'your_super_secret_key_for_flashing' # Important for flashing messages

# --- DATA FILE CONFIGURATION ---
DATA_DIR = 'data'
TRANSACTIONS_FILE = os.path.join(DATA_DIR, 'transactions.json')
INVESTMENTS_FILE = os.path.join(DATA_DIR, 'investments.json')

# --- PREDEFINED CATEGORIES ---
TRANSACTION_CATEGORIES = [
    "Salary", "Freelance", "Investment Income", "Other Income",
    "Rent", "Groceries", "Utilities", "Transportation", "Dining Out",
    "Entertainment", "Shopping", "Health & Wellness", "Education", "Travel",
    "Investment", "Charity", "Other Expense"
]

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

def get_historical_price(ticker, date_str):
    """Fetch the closing price for a given ticker on a specific date."""
    if not ticker or ticker.lower() == 'n/a':
        return 1.0 # For FDs, where price is the amount
    try:
        start_date = datetime.strptime(date_str, '%Y-%m-%d')
        end_date = start_date + timedelta(days=2) 
        
        stock_history = yf.download(ticker, start=start_date.strftime('%Y-%m-%d'), end=end_date.strftime('%Y-%m-%d'), progress=False)
        
        if stock_history.empty:
            prev_day_start = start_date - timedelta(days=4)
            stock_history = yf.download(ticker, start=prev_day_start.strftime('%Y-%m-%d'), end=end_date.strftime('%Y-%m-%d'), progress=False)
            if stock_history.empty:
                return None
            return float(stock_history['Close'].iloc[-1])
        
        return float(stock_history['Close'].iloc[0])
    except Exception as e:
        print(f"Could not fetch historical price for {ticker} on {date_str}: {e}")
        return None

def get_live_price(ticker):
    """Fetch the last closing price for a given ticker."""
    if not ticker or ticker.lower() == 'n/a':
        return 1.0
    try:
        stock = yf.Ticker(ticker)
        price = stock.info.get('previousClose', stock.info.get('regularMarketPrice'))
        return float(price) if price else 0.0
    except Exception as e:
        print(f"Could not fetch price for {ticker}: {e}")
        return 0.0

def enrich_investments_data(investments):
    """Add calculated fields like current value, gain/loss, etc."""
    enriched = []
    for inv in investments:
        current_price = get_live_price(inv['ticker'])
        units = float(inv.get('units', 0))
        
        current_value = units * current_price if current_price else 0
        gain_loss = current_value - inv['amount_invested']
        
        purchase_date = datetime.strptime(inv['purchase_date'], '%Y-%m-%d')
        holding_months = (datetime.now().year - purchase_date.year) * 12 + datetime.now().month - purchase_date.month
        
        tax_status = "N/A"
        if inv['type'] == 'Stock':
            tax_status = "LTCG" if holding_months > 12 else "STCG"
        elif inv['type'] == 'Mutual Fund':
            tax_status = "LTCG" if holding_months > 12 else "STCG"
            
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

# --- API ROUTE FOR TICKER SEARCH ---
@app.route('/api/search')
def search_ticker():
    """API endpoint to search for tickers based on a query string."""
    query = request.args.get('q', '')
    if not query or len(query) < 2:
        return jsonify([])

    search_url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        response = requests.get(search_url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        results = []
        for item in data.get('quotes', []):
            if item.get('longname') and item.get('symbol'):
                results.append({
                    'name': item.get('longname', item.get('shortname', '')),
                    'ticker': item['symbol']
                })
        return jsonify(results)
    except requests.exceptions.RequestException as e:
        print(f"API request failed: {e}")
        return jsonify({"error": "Failed to fetch search results"}), 500

# --- FLASK ROUTES ---

@app.route('/')
def dashboard():
    """Main dashboard page."""
    transactions = load_data(TRANSACTIONS_FILE)
    investments = load_data(INVESTMENTS_FILE)
    
    df_trans = pd.DataFrame(transactions) if transactions else pd.DataFrame()
    total_income = df_trans[df_trans['type'] == 'Income']['amount'].sum() if not df_trans.empty and 'type' in df_trans.columns else 0
    total_spends = df_trans[df_trans['type'] != 'Income']['amount'].sum() if not df_trans.empty and 'type' in df_trans.columns else 0
    
    enriched_investments = enrich_investments_data(investments)
    portfolio_value = sum(inv['current_value'] for inv in enriched_investments)
    
    bank_balance = total_income - total_spends
    net_worth = bank_balance + portfolio_value

    spend_categories = {}
    if not df_trans.empty and 'type' in df_trans.columns:
        spends_df = df_trans[df_trans['type'] != 'Income']
        if not spends_df.empty:
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
    today_date = datetime.now().strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        new_trans = {
            'id': str(uuid.uuid4()),
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
        
    sorted_transactions = sorted(transactions, key=lambda x: x['date'], reverse=True)
    return render_template('transactions.html', 
                           transactions=sorted_transactions, 
                           categories=TRANSACTION_CATEGORIES,
                           today_date=today_date)

@app.route('/investments', methods=['GET', 'POST'])
def investments_page():
    """Page to view and add investments."""
    investments = load_data(INVESTMENTS_FILE)
    today_date = datetime.now().strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        purchase_date = request.form['purchase_date']
        ticker = request.form['ticker'].upper()
        amount_invested = float(request.form['amount_invested'])

        purchase_price = get_historical_price(ticker, purchase_date)
        
        if purchase_price is None:
            flash(f'Error: Could not find historical price for "{ticker}" on {purchase_date}.', 'danger')
            return redirect(url_for('investments_page'))

        units = amount_invested / purchase_price if purchase_price > 0 else 0
        
        new_inv = {
            'id': str(uuid.uuid4()),
            'purchase_date': purchase_date,
            'name': request.form['name'],
            'ticker': ticker,
            'type': request.form['type'],
            'amount_invested': amount_invested,
            'purchase_price': purchase_price,
            'units': units
        }
        investments.append(new_inv)
        save_data(investments, INVESTMENTS_FILE)
        flash('Investment added successfully!', 'success')
        return redirect(url_for('investments_page'))
        
    enriched_investments = enrich_investments_data(investments)
    return render_template('investments.html', 
                           investments=enriched_investments,
                           today_date=today_date)

@app.route('/consolidated_view')
def consolidated_view():
    """A consolidated view of all financial data with date filtering."""
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    start_date = datetime.strptime(start_date_str, '%Y-%m-%d') if start_date_str else None
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d') if end_date_str else None

    transactions = load_data(TRANSACTIONS_FILE)
    investments = load_data(INVESTMENTS_FILE)
    
    filtered_transactions = [
        t for t in transactions if (
            (not start_date or datetime.strptime(t['date'], '%Y-%m-%d') >= start_date) and
            (not end_date or datetime.strptime(t['date'], '%Y-%m-%d') <= end_date)
        )
    ]
    
    filtered_investments = [
        i for i in investments if (
            (not start_date or datetime.strptime(i['purchase_date'], '%Y-%m-%d') >= start_date) and
            (not end_date or datetime.strptime(i['purchase_date'], '%Y-%m-%d') <= end_date)
        )
    ]

    all_activities = []
    total_income = 0
    total_expenses = 0
    total_invested = 0

    for t in filtered_transactions:
        all_activities.append({
            'id': t.get('id'),
            'source': 'transaction',
            'date': t['date'],
            'description': t['description'],
            'category': t['category'],
            'type': t['type'],
            'amount': t['amount']
        })
        if t['type'] == 'Income':
            total_income += t['amount']
        else:
            total_expenses += t['amount']

    for i in filtered_investments:
        all_activities.append({
            'id': i.get('id'),
            'source': 'investment',
            'date': i['purchase_date'],
            'description': i['name'],
            'category': 'Investment',
            'type': 'Investment',
            'amount': -i['amount_invested']
        })
        total_invested += i['amount_invested']
    
    all_activities.sort(key=lambda x: x['date'], reverse=True)
    
    return render_template('consolidated_view.html', 
                           activities=all_activities,
                           total_income=total_income,
                           total_expenses=abs(total_expenses),
                           total_invested=total_invested,
                           start_date=start_date_str,
                           end_date=end_date_str)

# --- DELETE ROUTES ---

@app.route('/delete_transaction/<transaction_id>', methods=['POST'])
def delete_transaction(transaction_id):
    """Delete a specific transaction by its ID."""
    transactions = load_data(TRANSACTIONS_FILE)
    transactions = [t for t in transactions if t.get('id') != transaction_id]
    save_data(transactions, TRANSACTIONS_FILE)
    flash('Transaction deleted successfully.', 'success')
    return redirect(request.referrer or url_for('transactions_page'))

@app.route('/delete_investment/<investment_id>', methods=['POST'])
def delete_investment(investment_id):
    """Delete a specific investment by its ID."""
    investments = load_data(INVESTMENTS_FILE)
    investments = [i for i in investments if i.get('id') != investment_id]
    save_data(investments, INVESTMENTS_FILE)
    flash('Investment deleted successfully.', 'success')
    return redirect(request.referrer or url_for('investments_page'))

@app.route('/export')
def export_excel():
    """Export all data to an Excel file."""
    transactions = load_data(TRANSACTIONS_FILE)
    investments = load_data(INVESTMENTS_FILE)
    enriched_investments = enrich_investments_data(investments)

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


import os, datetime, math, requests
from flask import Flask, jsonify, render_template
from dotenv import load_dotenv
load_dotenv()
app = Flask(__name__)
BASE = 'https://eodhd.com/api'
SYMBOLS = ['NPN.JSE','AGL.JSE','BHP.JSE','SOL.JSE','SHP.JSE','CPI.JSE','FSR.JSE','SBK.JSE','GFI.JSE','ANG.JSE']
COST = 0.002

def fetch(symbol):
    token = os.getenv('EODHD_API_TOKEN', '').strip()
    if not token: return None, ('EODHD_API_TOKEN ontbreek op Render.', 503)
    try:
        response = requests.get(f'{BASE}/eod/{symbol}', params={'api_token':token,'fmt':'json','period':'d','from':(datetime.date.today()-datetime.timedelta(days=1500)).isoformat()}, timeout=25)
    except requests.RequestException: return None, ('Kan nie EODHD bereik nie.', 502)
    errors = {401:'Ongeldige API-sleutel.',403:'Geen toegang tot hierdie data in jou EODHD-pakket nie.',404:'Simbool nie gevind nie.',429:'API-limiet bereik.'}
    if response.status_code in errors: return None, (errors[response.status_code],response.status_code)
    if not response.ok: return None, (f'EODHD HTTP {response.status_code}',502)
    try: rows=response.json()
    except ValueError: return None, ('Ongeldige JSON van EODHD.',502)
    if not isinstance(rows,list): return None, ('EODHD het nie ' + 'n geldige pryslys teruggestuur nie.',502)
    try:
        rows=sorted([{'date':str(r['date']),'open':float(r['open']),'close':float(r['close']),'adjusted_close':float(r.get('adjusted_close') or r['close']),'volume':float(r.get('volume') or 0)} for r in rows if float(r.get('open') or 0)>0 and float(r.get('close') or 0)>0 and float(r.get('adjusted_close') or r.get('close') or 0)>0],key=lambda r:r['date'])
    except (KeyError,ValueError,TypeError): return None, ('Ongeldige prysdata ontvang.',502)
    if len(rows)<260: return None, ('Minstens 260 geldige handelsdae benodig.',422)
    return rows,None

def sma(v,n): return sum(v[-n:])/n if len(v)>=n else None

def rsi_wilder(v,n=14):
    if len(v)<n+1: return None
    changes=[v[i]-v[i-1] for i in range(1,len(v))]
    gain=sum(max(x,0) for x in changes[:n])/n
    loss=sum(max(-x,0) for x in changes[:n])/n
    for change in changes[n:]:
        gain=(gain*(n-1)+max(change,0))/n
        loss=(loss*(n-1)+max(-change,0))/n
    if loss==0: return 50.0 if gain==0 else 100.0
    return 100-100/(1+gain/loss)

def metrics(v):
    p=v[-1]; ma50=sma(v,50); ma200=sma(v,200); ri=rsi_wilder(v)
    mo=p/v[-64]-1
    score=50+(15 if p>ma50 else -15)+(15 if ma50>ma200 else -15)+(15 if mo>0 else -15)+(5 if 40<=ri<=70 else -5)
    score=max(0,min(100,score))
    return {'score':score,'rsi':ri,'momentum':mo,'ma50':ma50,'ma200':ma200}

def backtest(rows):
    # Decision at close i, execution at next session open i+1.
    # Trade signals use only adjusted closes up to i; exposure uses raw open-to-open prices.
    adj=[r['adjusted_close'] for r in rows]
    equity=1.0; peak=1.0; maxdd=0.0; position=False; entry_index=None; trades=0; completed=0; wins=0
    entry_equity=None
    start=220
    for i in range(start,len(rows)-1):
        m=metrics(adj[:i+1]); score=m['score']
        target=position
        if position and (score<50 or i-entry_index>=63): target=False
        elif not position and score>=80: target=True
        if target!=position:
            equity*=1-COST
            trades+=1
            if target:
                entry_index=i+1; entry_equity=equity
            else:
                completed+=1
                if entry_equity and equity>entry_equity: wins+=1
                entry_index=None; entry_equity=None
            position=target
        # From next open to following open; last available interval instead uses next open to next close.
        if position:
            next_open=rows[i+1]['open']
            if i+2<len(rows):
                equity*=rows[i+2]['open']/next_open
            else:
                equity*=rows[i+1]['close']/next_open
        peak=max(peak,equity)
        maxdd=min(maxdd,equity/peak-1)
    # Liquidate any remaining position at end-of-data, charging exit cost.
    if position:
        equity*=1-COST; trades+=1; completed+=1
        if entry_equity and equity>entry_equity: wins+=1
        maxdd=min(maxdd,equity/peak-1)
    # Buy-and-hold on same period, using raw opening prices and terminal close.
    initial=rows[start+1]['open']; terminal=rows[-1]['close']
    hold=terminal/initial-1
    hold_peak=1.0; hold_dd=0.0
    for r in rows[start+1:]:
        val=r['close']/initial
        hold_peak=max(hold_peak,val)
        hold_dd=min(hold_dd,val/hold_peak-1)
    return {'start_date':rows[start+1]['date'],'end_date':rows[-1]['date'],'strategy_return_pct':round((equity-1)*100,2),'buy_hold_return_pct':round(hold*100,2),'max_drawdown_pct':round(maxdd*100,2),'buy_hold_max_drawdown_pct':round(hold_dd*100,2),'trades':trades,'completed_positions':completed,'win_rate_pct':round(100*wins/completed,1) if completed else None,'no_trades':trades==0}

def calc(rows):
    v=[r['adjusted_close'] for r in rows]
    m=metrics(v); score=m['score']; bt=backtest(rows)
    last=rows[-1]
    stale=(datetime.date.today()-datetime.date.fromisoformat(last['date'])).days>5
    return {'date':last['date'],'price':round(last['adjusted_close'],2),'raw_close':round(last['close'],2),'currency_note':'EODHD-pryseenheid moet teen die JSE-notering bevestig word (ZAR teenoor ZAc).','score':score,'signal':'KOOP' if score>=80 else ('VERKOOP / VERMY' if score<50 else 'HOU'),'rsi':round(m['rsi'],1),'momentum_3m_pct':round(m['momentum']*100,1),'ma50':round(m['ma50'],2),'ma200':round(m['ma200'],2),'observations':len(rows),'stale_data':stale,'warning':'Historiese einddagdata, nie intyds nie. Backtest is illustratief, gebruik volgende-dag opening, 0.2% per transaksie, maar geen belasting of slippage. Geen dividende in ruwe-prys backtest nie.','backtest':bt,**bt}

@app.get('/')
def home(): return render_template('index.html',symbols=SYMBOLS)

@app.get('/api/stock/<symbol>')
def stock(symbol):
    symbol=symbol.upper()
    if symbol not in SYMBOLS: return jsonify(error='Simbool nie toegelaat nie.'),400
    rows,error=fetch(symbol)
    if error: return jsonify(error=error[0]),error[1]
    return jsonify(symbol=symbol,**calc(rows))

@app.get('/health')
def health(): return jsonify(status='ok',api_key_configured=bool(os.getenv('EODHD_API_TOKEN')))

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT','5000')))

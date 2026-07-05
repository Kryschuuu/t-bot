import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import logging
from decimal import Decimal, ROUND_HALF_UP
# Logging konfigurieren
logger = logging.getLogger(__name__)
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from decimal import Decimal, ROUND_HALF_UP
import numpy as np
import logging

logger = logging.getLogger(__name__)

class Backtesting:
    @staticmethod
    def calculate_indicators(prices, idx):
        """Berechnet Indikatoren an Index idx (ab idx >= 2)."""
        current_price = prices[idx]
        prev_price_1 = prices[idx - 1]
        prev_price_2 = prices[idx - 2]

        current_da = current_price - prev_price_1
        current_nda = (current_da / current_price * Decimal(100)).quantize(Decimal('1e-8'), rounding=ROUND_HALF_UP) if current_price != 0 else Decimal(0)

        prev_da = prev_price_1 - prev_price_2
        prev_nda = (prev_da / prev_price_1 * Decimal(100)).quantize(Decimal('1e-8'), rounding=ROUND_HALF_UP) if prev_price_1 != 0 else Decimal(0)

        dva = (current_nda - prev_nda).quantize(Decimal('1e-8'), rounding=ROUND_HALF_UP)
        div_DVA_prev_NDA = (dva / prev_nda).quantize(Decimal('1e-8'), rounding=ROUND_HALF_UP) if prev_nda != 0 else Decimal(0)
        deltadelta = ((current_nda + prev_nda) / Decimal(2)).quantize(Decimal('1e-8'), rounding=ROUND_HALF_UP)
        return div_DVA_prev_NDA, deltadelta, current_nda

    @staticmethod
    def compute_indicator_series(prices):
        """Berechnet Indikatorserien ab Index 2."""
        indices = []
        acc_series = []
        deltadelta_series = []
        nda_series = []
        for i in range(2, len(prices)):
            a, d, n = Backtesting.calculate_indicators(prices, i)
            indices.append(i)
            acc_series.append(a)
            deltadelta_series.append(d)
            nda_series.append(n)
        return indices, acc_series, deltadelta_series, nda_series

    @staticmethod
    def simulate_trading_detailed(prices, acc_threshold, nda_threshold, deltadelta_threshold, simulation_params):
        """Führt die Handelssimulation durch."""
        capital = simulation_params.get('start_capital', Decimal('1000'))
        trade_amount = simulation_params.get('trade_amount', Decimal('100'))
        take_profit = simulation_params.get('take_profit', Decimal('5'))
        fee_percentage = simulation_params.get('fee_percentage', Decimal('0.1'))

        position_open = False
        buy_price = None
        trades = []

        for i in range(2, len(prices)):
            div_DVA_prev_NDA, deltadelta, current_nda = Backtesting.calculate_indicators(prices, i)
            current_price = prices[i]

            if not position_open and (div_DVA_prev_NDA > acc_threshold and current_nda > nda_threshold and deltadelta > deltadelta_threshold):
                if capital >= trade_amount:
                    buy_price = current_price
                    position_open = True
                    fee = (trade_amount * fee_percentage / Decimal(100)).quantize(Decimal('1e-8'), rounding=ROUND_HALF_UP)
                    capital_before = capital
                    capital -= (trade_amount + fee)
                    trades.append({
                        'type': 'buy', 'price': current_price, 'index': i,
                        'capital_before': capital_before, 'capital_after': capital
                    })

            if position_open:
                price_increase = (current_price - buy_price) / buy_price * Decimal(100)
                if price_increase >= take_profit:
                    fee = (trade_amount * fee_percentage / Decimal(100)).quantize(Decimal('1e-8'), rounding=ROUND_HALF_UP)
                    capital_before = capital
                    capital += (trade_amount * (1 + take_profit / Decimal(100)) - fee)
                    trades.append({
                        'type': 'sell', 'price': current_price, 'index': i,
                        'capital_before': capital_before, 'capital_after': capital,
                        'profit_percentage': price_increase
                    })
                    position_open = False
                    buy_price = None

        if position_open:
            price_increase = (prices[-1] - buy_price) / buy_price * Decimal(100)
            fee = (trade_amount * fee_percentage / Decimal(100)).quantize(Decimal('1e-8'), rounding=ROUND_HALF_UP)
            capital_before = capital
            capital += (trade_amount * (1 + price_increase / Decimal(100)) - fee)
            trades.append({
                'type': 'sell', 'price': prices[-1], 'index': len(prices)-1,
                'capital_before': capital_before, 'capital_after': capital,
                'profit_percentage': price_increase
            })

        report = {
            'final_capital': capital, 'trades': trades, 'num_trades': len(trades),
            'num_buys': sum(1 for t in trades if t['type'] == 'buy'),
            'num_sells': sum(1 for t in trades if t['type'] == 'sell'),
            'profitable_trades': sum(1 for t in trades if t['type'] == 'sell' and t.get('profit_percentage', Decimal(0)) >= take_profit),
            'unprofitable_trades': sum(1 for t in trades if t['type'] == 'sell') - sum(1 for t in trades if t['type'] == 'sell' and t.get('profit_percentage', Decimal(0)) >= take_profit)
        }
        return capital, report

    @staticmethod
    def create_plot_for_symbol(historical_prices, report):
        """Erstellt ein Diagramm mit Preis und Indikatoren."""
        prices_float = [float(p) for p in historical_prices]
        indices, acc_series, deltadelta_series, nda_series = Backtesting.compute_indicator_series(historical_prices)
        acc_float = [float(a) for a in acc_series]
        deltadelta_float = [float(d) for d in deltadelta_series]
        nda_float = [float(n) for n in nda_series]

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.6, 0.4])
        fig.add_trace(go.Scatter(x=list(range(len(prices_float))), y=prices_float, mode='lines', name='Preis', line=dict(color='blue')), row=1, col=1)
        fig.add_trace(go.Scatter(x=indices, y=acc_float, mode='lines', name='div_DVA_prev_NDA', line=dict(color='purple')), row=2, col=1)
        fig.add_trace(go.Scatter(x=indices, y=deltadelta_float, mode='lines', name='Deltadelta', line=dict(color='orange')), row=2, col=1)
        fig.add_trace(go.Scatter(x=indices, y=nda_float, mode='lines', name='NDA', line=dict(color='green')), row=2, col=1)

        buy_trades_x, buy_trades_y = [], []
        sell_trades_x, sell_trades_y = [], []
        if 'trades' in report:
            for trade in report['trades']:
                if trade['type'] == 'buy':
                    buy_trades_x.append(trade['index'])
                    buy_trades_y.append(float(trade['price']))
                elif trade['type'] == 'sell':
                    sell_trades_x.append(trade['index'])
                    sell_trades_y.append(float(trade['price']))

        fig.add_trace(go.Scatter(x=buy_trades_x, y=buy_trades_y, mode='markers', marker=dict(symbol='triangle-up', size=12, color='green'), name='Kaufsignale'), row=1, col=1)
        fig.add_trace(go.Scatter(x=sell_trades_x, y=sell_trades_y, mode='markers', marker=dict(symbol='triangle-down', size=12, color='red'), name='Verkaufssignale'), row=1, col=1)

        fig.update_layout(
            title='Preis- und Indikatorendiagramm mit Trades',
            xaxis_title='Zeitindex',
            yaxis_title='Preis (USDT)',
            xaxis_rangeslider_visible=True,
            height=600,
            autosize=True,
            yaxis2=dict(title='Indikatorwert', overlaying='y', side='right')
        )
        return fig

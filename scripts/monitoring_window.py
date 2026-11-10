"""One inclusive planning window for discovery, source parsing and display."""
import json
from datetime import date, timedelta
from pathlib import Path


def scope_config():
    return json.loads((Path(__file__).resolve().parents[1]/'config/monitoring-scope.json').read_text(encoding='utf8'))


def window_end(today, scope=None):
    scope = scope if scope is not None else scope_config()
    months = scope.get('monitoring_complete_months')
    if months is None:
        return today + timedelta(days=int(scope.get('monitoring_horizon_days', 90)))
    if type(months) is not int or not 1 <= months <= 12:
        raise ValueError('monitoring_complete_months must be between 1 and 12')
    # The first day AFTER the target month, minus one day. Handles leap years
    # and December without clamping today's day into a shorter month.
    year, month = divmod(today.year*12 + today.month-1 + months+1, 12)
    return date(year, month+1, 1) - timedelta(days=1)


def window_metadata(today, scope=None):
    scope = scope if scope is not None else scope_config()
    end = window_end(today, scope)
    months = scope.get('monitoring_complete_months')
    return {'monitoring_horizon_days':(end-today).days,
            'monitoring_complete_months':months,
            'monitoring_window':{'start_at':today.isoformat(),'end_at':end.isoformat(),
                'policy':'current_month_remainder_plus_complete_months' if months is not None else 'rolling_days',
                'complete_future_months':months,'inclusive':True}}


def future_months(today, scope=None):
    scope = scope if scope is not None else scope_config()
    result=[]
    for offset in range(1,scope.get('monitoring_complete_months',0)+1):
        year,month=divmod(today.year*12+today.month-1+offset,12)
        result.append(date(year,month+1,1))
    return result

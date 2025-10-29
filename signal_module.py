import pandas as pd
from typing import Dict, Optional
from model_logic import QXRange

class QXSignalGenerator:
    """
    Standalone QX Range signal generator for ES futures.
    Computes DR/IDR, detects confirmation signals, and outputs signal dicts.
    Designed for use in Jupyter or as a module.
    """
    def __init__(self, mode_retrace_sd: pd.DataFrame, mode_ext_sd: pd.DataFrame, global_sd: float):
        self.qxrange = QXRange(mode_retrace_sd, mode_ext_sd, global_sd)
        self.bounds = None
        self.confirmations = None

    def compute_boundaries(self, df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """Compute DR/IDR boundaries for all sessions."""
        self.bounds = self.qxrange.compute_boundaries(df)
        return self.bounds

    def detect_confirmations(self, df: pd.DataFrame) -> pd.DataFrame:
        """Detect confirmation signals for all sessions."""
        if self.bounds is None:
            self.compute_boundaries(df)
        self.confirmations = self.qxrange.detect_confirmations(df, self.bounds)
        return self.confirmations

    def get_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Return a DataFrame of all confirmation signals (one per session per day).
        Columns: ['date', 'session', 'bias', 'confirmation_time']
        """
        if self.confirmations is None:
            self.detect_confirmations(df)
        signals = []
        for date in pd.unique(df.index.date):
            for session in ['rdr', 'odr', 'adr']:
                for bias in ['bullish', 'bearish']:
                    conf_col = f'{session}_confirmed_{bias}'
                    time_col = f'{session}_confirmation_time'
                    if conf_col in self.confirmations.columns:
                        conf_times = self.confirmations[self.confirmations[conf_col]].index
                        if len(conf_times) > 0:
                            conf_time = conf_times[0]
                            signals.append({
                                'date': date,
                                'session': session,
                                'bias': bias,
                                'confirmation_time': conf_time
                            })
        return pd.DataFrame(signals)

    def get_signal_for_datetime(self, dt: pd.Timestamp) -> Optional[Dict]:
        """
        Get the signal dict for a specific datetime (if a confirmation occurred at that time).
        """
        if self.confirmations is None:
            return None
        for session in ['rdr', 'odr', 'adr']:
            for bias in ['bullish', 'bearish']:
                conf_col = f'{session}_confirmed_{bias}'
                if conf_col in self.confirmations.columns:
                    if self.confirmations.at[dt, conf_col]:
                        return {
                            'datetime': dt,
                            'session': session,
                            'bias': bias
                        }
        return None 
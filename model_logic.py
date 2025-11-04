import pandas as pd
import numpy as np
from datetime import time

class QXRange:
    def __init__(self, mode_retrace_sd: pd.DataFrame, mode_ext_sd: pd.DataFrame, global_sd: float):
        self.mode_retrace_sd = mode_retrace_sd
        self.mode_ext_sd = mode_ext_sd
        self.global_sd = global_sd

        # DR session windows (Eastern Time) - RANGE SESSIONS for DR/IDR calculation
        # These are the time windows where we calculate DR/IDR levels
        self.rdr_start = time(9, 30)   # 9:30 AM
        self.rdr_end = time(10, 25)    # 10:25 AM (ends at 10:25 close, before 10:30)
        self.odr_start = time(3, 0)    # 3:00 AM  
        self.odr_end = time(3, 55)     # 3:55 AM (ends at 3:55 close, before 4:00)
        self.adr_start = time(19, 30)  # 7:30 PM
        self.adr_end = time(20, 25)    # 8:25 PM (ends at 8:25 close, before 8:30)

    def compute_boundaries(self, df: pd.DataFrame, session_name: str = None, target_date: pd.Timestamp = None) -> dict:
        """
        Compute DR/IDR boundaries for a specific session and date.
        - DR: High/Low of time range (using 'high'/'low' columns - includes wicks)
        - IDR: Body High/Body Low (using max/min of 'open'/'close' - excludes wicks)
        
        IDR focuses on candle bodies only:
        - IDR High = highest point where any candle body reached (max of open/close per bar)
        - IDR Low = lowest point where any candle body reached (min of open/close per bar)
        
        Args:
            df: DataFrame with bars
            session_name: 'rdr', 'odr', or 'adr' - if None, processes all (for backwards compat)
            target_date: Date to process - if None, processes all dates
        """
        # Data is already in Eastern Time - no timezone conversion needed
        df = df.copy()
        
        boundaries = {}
        
        # Session definitions with correct end times
        sessions = {
            'rdr': (self.rdr_start, self.rdr_end),
            'odr': (self.odr_start, self.odr_end), 
            'adr': (self.adr_start, self.adr_end)
        }
        
        # If session_name specified, only process that session
        sessions_to_process = {session_name: sessions[session_name]} if session_name and session_name in sessions else sessions
        
        for session, (start_time, end_time) in sessions_to_process.items():
            # OPTIMIZED: Use groupby instead of nested loops
            df['date'] = df.index.date
            daily_groups = df.groupby('date')
            
            # Process each day
            daily_results = []
            
            for date, day_data in daily_groups:
                # If target_date specified, only process that date
                if target_date is not None and date != target_date.date():
                    # Fill with NaN for this date
                    day_data = day_data.copy()
                    day_data['dr_high'] = np.nan
                    day_data['dr_low'] = np.nan
                    day_data['idr_high'] = np.nan
                    day_data['idr_low'] = np.nan
                    day_data['dr_end'] = pd.NaT
                    daily_results.append(day_data[['dr_high', 'dr_low', 'idr_high', 'idr_low', 'dr_end']])
                    continue
                
                # Filter to session time range - RANGE SESSIONS for DR/IDR calculation
                time_mask = (
                    (day_data.index.time >= start_time) & 
                    (day_data.index.time <= end_time)
                )
                
                session_data = day_data[time_mask]
                
                if not session_data.empty and len(session_data) >= 5:
                    # Calculate DR levels (High/Low of time range - includes wicks)
                    dr_high = session_data['high'].max()
                    dr_low = session_data['low'].min()
                    
                    # Calculate IDR levels (Body High/Body Low - excludes wicks)
                    # IDR High = highest point where any candle body reached (max of open/close)
                    # IDR Low = lowest point where any candle body reached (min of open/close)
                    session_data_copy = session_data.copy()
                    session_data_copy['body_high'] = session_data_copy[['open', 'close']].max(axis=1)
                    session_data_copy['body_low'] = session_data_copy[['open', 'close']].min(axis=1)
                    idr_high = session_data_copy['body_high'].max()
                    idr_low = session_data_copy['body_low'].min()
                    
                    # Only print debug for current session/date
                    if session_name and target_date and date == target_date.date():
                        print(f"[{session.upper()}] {date} | Range: {session_data.index[0].strftime('%H:%M')}-{session_data.index[-1].strftime('%H:%M')} | DR: {dr_high:.2f}/{dr_low:.2f} | IDR: {idr_high:.2f}/{idr_low:.2f}")
                    
                    # DR session end time for confirmation detection
                    dr_end_time = session_data.index[-1]
                else:
                    # No valid session data for this date
                    dr_high = dr_low = idr_high = idr_low = np.nan
                    dr_end_time = pd.NaT
                
                # OPTIMIZED: Apply to all bars for this date using vectorized assignment
                day_data = day_data.copy()
                day_data['dr_high'] = dr_high
                day_data['dr_low'] = dr_low
                day_data['idr_high'] = idr_high
                day_data['idr_low'] = idr_low
                day_data['dr_end'] = dr_end_time
                
                daily_results.append(day_data[['dr_high', 'dr_low', 'idr_high', 'idr_low', 'dr_end']])
            
            # OPTIMIZED: Combine all daily results at once
            if daily_results:
                session_df = pd.concat(daily_results)
                boundaries[session] = session_df.reindex(df.index, fill_value=np.nan)
            else:
                # No session data found
                boundaries[session] = pd.DataFrame({
                    'dr_high': [np.nan] * len(df),
                    'dr_low': [np.nan] * len(df),
                    'idr_high': [np.nan] * len(df),
                    'idr_low': [np.nan] * len(df),
                    'dr_end': [pd.NaT] * len(df)
                }, index=df.index)
        
        return boundaries

    def detect_confirmations(self, df: pd.DataFrame, bounds: dict) -> pd.DataFrame:
        """
        Detect DR confirmations using the computed boundaries
        
        Confirmation occurs when price closes above DR High (bullish) or below DR Low (bearish)
        ONLY during the trading session time window, after the DR session has formed.
        
        Trading Sessions:
        - ODR Trading: 04:00-08:00 (after ODR session forms at 03:55)
        - RDR Trading: 10:30-16:00 (after RDR session forms at 10:25)  
        - ADR Trading: 20:30-01:00 (after ADR session forms at 20:25)
        """
        # Data is already in Eastern Time
        df = df.copy()

        confirmations = pd.DataFrame(index=df.index)
        
        # Trading session definitions (when we look for confirmations)
        trading_sessions = {
            'odr': (time(4, 0), time(8, 0)),      # 4:00 AM - 8:00 AM
            'rdr': (time(10, 30), time(16, 0)),   # 10:30 AM - 4:00 PM
            'adr': (time(20, 30), time(1, 0))     # 8:30 PM - 1:00 AM (next day)
        }
        
        for session in ['rdr', 'odr', 'adr']:
            session_bounds = bounds[session]
            
            # Initialize confirmation columns
            confirmations[f'{session}_confirmation_time'] = pd.NaT
            confirmations[f'{session}_confirmation_bias'] = None
            
            # OPTIMIZED: Use groupby instead of nested loops
            df['date'] = df.index.date
            daily_groups = df.groupby('date')
            
            # For each date, find the first confirmation during trading session
            for date, day_data in daily_groups:
                # Get DR boundaries for this date
                day_bounds = session_bounds.loc[day_data.index]
                if day_bounds.empty:
                    continue
                
                # Get the first non-NaN boundary values for this date
                valid_bounds = day_bounds.dropna(subset=['dr_high', 'dr_low'])
                if valid_bounds.empty:
                    continue
                
                dr_high = valid_bounds['dr_high'].iloc[0]
                dr_low = valid_bounds['dr_low'].iloc[0]
                dr_end = valid_bounds['dr_end'].iloc[0]
                
                if pd.isna(dr_end) or pd.isna(dr_high) or pd.isna(dr_low):
                    continue
                
                # Get trading session start and end times
                trading_start, trading_end = trading_sessions[session]
                
                # Handle ADR trading session crossing midnight
                if session == 'adr':
                    # ADR trading starts at 20:30 on current day, ends at 01:00 next day
                    trading_start_time = pd.Timestamp.combine(date, trading_start).tz_localize('America/New_York')
                    trading_end_time = pd.Timestamp.combine(date + pd.Timedelta(days=1), trading_end).tz_localize('America/New_York')
                else:
                    # ODR and RDR trading sessions are on the same day
                    trading_start_time = pd.Timestamp.combine(date, trading_start).tz_localize('America/New_York')
                    trading_end_time = pd.Timestamp.combine(date, trading_end).tz_localize('America/New_York')
                
                # Filter to trading session time window ONLY
                trading_mask = (
                    (day_data.index >= trading_start_time) & 
                    (day_data.index <= trading_end_time)
                )
                trading_data = day_data[trading_mask]
                
                if trading_data.empty:
                    continue
                
                # Look for confirmations during trading session ONLY
                # Confirmation must happen after DR session has formed
                post_dr_trading_mask = trading_data.index > dr_end
                post_dr_trading_data = trading_data[post_dr_trading_mask]
                
                if post_dr_trading_data.empty:
                    continue
                
                # Check for DR breaks during trading session
                bullish_mask = post_dr_trading_data['close'] > dr_high
                bearish_mask = post_dr_trading_data['close'] < dr_low
                
                first_bullish = post_dr_trading_data.index[bullish_mask].min() if bullish_mask.any() else pd.NaT
                first_bearish = post_dr_trading_data.index[bearish_mask].min() if bearish_mask.any() else pd.NaT
                
                # Determine which confirmation came first during trading session
                if pd.notna(first_bullish) and pd.notna(first_bearish):
                    if first_bullish < first_bearish:
                        conf_time, bias = first_bullish, 'bullish'
                    else:
                        conf_time, bias = first_bearish, 'bearish'
                elif pd.notna(first_bullish):
                    conf_time, bias = first_bullish, 'bullish'
                elif pd.notna(first_bearish):
                    conf_time, bias = first_bearish, 'bearish'
                else:
                    conf_time, bias = pd.NaT, None
                
                # Apply confirmation to all bars for this date
                confirmations.loc[day_data.index, f'{session}_confirmation_time'] = conf_time
                confirmations.loc[day_data.index, f'{session}_confirmation_bias'] = bias
        
        return confirmations 
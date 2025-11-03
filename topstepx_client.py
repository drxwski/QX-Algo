import os
import requests

TOPSTEPX_AUTH_URL_KEY = "https://api.topstepx.com/api/Auth/loginKey"
TOPSTEPX_AUTH_URL_APP = "https://api.topstepx.com/api/Auth/loginApp"

# Bar time unit constants
BAR_UNIT_TICK = 1
BAR_UNIT_MINUTE = 2
BAR_UNIT_HOUR = 3
BAR_UNIT_DAY = 4
BAR_UNIT_WEEK = 5
BAR_UNIT_MONTH = 6

# Order side constants
ORDER_SIDE_SELL = 1  # Ask
ORDER_SIDE_BUY = 2   # Bid

# Order type constants
ORDER_TYPE_MARKET = 2

class TopstepXAuthError(Exception):
    pass

def authenticate_with_key(username=None, api_key=None):
    """
    Authenticate with TopstepX using API key method (loginKey).
    Username and API key can be passed or read from environment variables.
    
    Environment variables:
    - TOPSTEPX_USERNAME
    - TOPSTEPX_API_KEY
    """
    if username is None:
        username = os.getenv("TOPSTEPX_USERNAME")
    if api_key is None:
        # Support both names
        api_key = os.getenv("TOPSTEPX_APIKEY") or os.getenv("TOPSTEPX_API_KEY")
    if not username or not api_key:
        raise TopstepXAuthError("Missing TopstepX username or API key. Set TOPSTEPX_USERNAME and TOPSTEPX_API_KEY.")

    payload = {"userName": username, "apiKey": api_key}
    headers = {"accept": "text/plain", "Content-Type": "application/json"}
    try:
        resp = requests.post(TOPSTEPX_AUTH_URL_KEY, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise TopstepXAuthError(f"Failed to connect to TopstepX: {e}")

    if not data.get("success") or data.get("errorCode", 1) != 0:
        raise TopstepXAuthError(f"TopstepX auth failed: {data.get('errorMessage', 'Unknown error')}")

    token = data.get("token")
    if not token:
        raise TopstepXAuthError("No session token returned from TopstepX.")
    print("[TopstepX] Authenticated successfully with API key. Session token acquired.")
    return token

def authenticate_with_app(username=None, password=None, device_id=None, app_id=None, verify_key=None):
    """
    Authenticate with TopstepX using application credentials (loginApp).
    For authorized applications/firms only.
    
    Parameters can be passed or read from environment variables.
    
    Environment variables:
    - TOPSTEPX_APP_USERNAME
    - TOPSTEPX_APP_PASSWORD
    - TOPSTEPX_APP_DEVICE_ID
    - TOPSTEPX_APP_ID
    - TOPSTEPX_APP_VERIFY_KEY
    """
    if username is None:
        username = os.getenv("TOPSTEPX_APP_USERNAME")
    if password is None:
        password = os.getenv("TOPSTEPX_APP_PASSWORD")
    if device_id is None:
        device_id = os.getenv("TOPSTEPX_APP_DEVICE_ID")
    if app_id is None:
        app_id = os.getenv("TOPSTEPX_APP_ID")
    if verify_key is None:
        verify_key = os.getenv("TOPSTEPX_APP_VERIFY_KEY")
    
    if not all([username, password, device_id, app_id, verify_key]):
        raise TopstepXAuthError(
            "Missing application credentials. Set TOPSTEPX_APP_USERNAME, "
            "TOPSTEPX_APP_PASSWORD, TOPSTEPX_APP_DEVICE_ID, TOPSTEPX_APP_ID, "
            "and TOPSTEPX_APP_VERIFY_KEY."
        )

    payload = {
        "userName": username,
        "password": password,
        "deviceId": device_id,
        "appId": app_id,
        "verifyKey": verify_key
    }
    headers = {"accept": "text/plain", "Content-Type": "application/json"}
    try:
        resp = requests.post(TOPSTEPX_AUTH_URL_APP, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise TopstepXAuthError(f"Failed to connect to TopstepX: {e}")

    if not data.get("success") or data.get("errorCode", 1) != 0:
        raise TopstepXAuthError(f"TopstepX auth failed: {data.get('errorMessage', 'Unknown error')}")

    token = data.get("token")
    if not token:
        raise TopstepXAuthError("No session token returned from TopstepX.")
    print("[TopstepX] Authenticated successfully with application credentials. Session token acquired.")
    return token

def authenticate(username=None, api_key=None):
    """
    Authenticate with TopstepX and return the session token.
    Auto-detects authentication method based on available environment variables.
    
    Priority:
    1. Application credentials (if TOPSTEPX_APP_ID is set)
    2. API key credentials (if TOPSTEPX_API_KEY is set)
    
    For backwards compatibility, this defaults to API key authentication.
    """
    # Check if application credentials are available
    if os.getenv("TOPSTEPX_APP_ID") or os.getenv("TOPSTEPX_APP_USERNAME"):
        try:
            return authenticate_with_app()
        except TopstepXAuthError:
            # Fall back to API key if app auth fails
            pass
    
    # Default to API key authentication
    return authenticate_with_key(username, api_key)

def topstepx_request(method, endpoint, token=None, base_url="https://api.topstepx.com", **kwargs):
    """
    Make an authenticated request to TopstepX API.
    - method: 'GET', 'POST', etc.
    - endpoint: e.g., '/api/Account/info'
    - token: session token (if None, will call authenticate())
    - kwargs: passed to requests.request
    
    Returns: tuple of (response_data, token) where token may be refreshed on 401
    """
    if token is None:
        token = authenticate()
    url = base_url.rstrip("/") + endpoint
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    headers.setdefault("accept", "application/json")
    resp = requests.request(method, url, headers=headers, timeout=20, **kwargs)
    if resp.status_code == 401:
        # Retry once with fresh token
        print("[TopstepX] Token expired (401), re-authenticating...")
        token = authenticate()
        headers["Authorization"] = f"Bearer {token}"
        resp = requests.request(method, url, headers=headers, timeout=20, **kwargs)
    try:
        resp.raise_for_status()
        return resp.json(), token  # Return both response and (possibly refreshed) token
    except Exception as e:
        print(f"[TopstepX] Request failed: {e}\nResponse: {getattr(resp,'text', '')}")
        raise

def get_account_info(token=None):
    """
    Example: Get account info from TopstepX.
    """
    endpoint = "/api/Account/info"
    resp, _ = topstepx_request("GET", endpoint, token=token)
    return resp

def validate_token(token=None):
    """
    Validate the current session token. Returns True if valid, else False.
    """
    endpoint = "/api/Auth/validate"
    try:
        resp, _ = topstepx_request("POST", endpoint, token=token)
        print("[TopstepX] Token validation response:", resp)
        return resp.get("success", False)
    except Exception as e:
        print("[TopstepX] Token validation failed:", e)
        return False

def search_accounts(token=None, only_active=True):
    """
    Retrieve a list of active accounts linked to the user.
    Returns a list of accounts.
    """
    endpoint = "/api/Account/search"
    payload = {"onlyActiveAccounts": only_active}
    resp, _ = topstepx_request("POST", endpoint, token=token, json=payload)
    print("[TopstepX] Accounts response:", resp)
    return resp.get("accounts") or resp

def search_contracts(token=None, live=True, searchText="ES"):
    """Search contracts by text; defaults to ES.*. Uses /api/Contract/search."""
    endpoint = "/api/Contract/search"
    payload = {"live": bool(live), "searchText": searchText}
    resp, _ = topstepx_request("POST", endpoint, token=token, json=payload)
    print("[TopstepX] Contracts response:", resp)
    # Return empty list if no contracts found, not the full response dict
    contracts = resp.get("contracts")
    return contracts if contracts is not None else []

def place_order(account_id, contract_id, size=1, side=1, order_type=2, price=None, token=None, return_token=False):
    """
    Place an order on TopstepX.
    - account_id: int
    - contract_id: str
    - size: int
    - side: 1=Buy (Ask), 2=Sell (Bid)
    - order_type: 1=Limit, 2=Market
    - price: float (required for limit orders)
    - return_token: bool - if True, returns (response, token) tuple
    Returns the order response (or tuple of response and token if return_token=True).
    """
    endpoint = "/api/Order/place"
    payload = {
        "accountId": account_id,
        "contractId": contract_id,
        "type": order_type,
        "side": side,
        "size": size
    }
    
    # Add price for limit orders
    if price is not None:
        payload["price"] = price
    
    resp, new_token = topstepx_request("POST", endpoint, token=token, json=payload)
    print("[TopstepX] Place order response:", resp)
    if return_token:
        return resp, new_token
    return resp

def retrieve_bars(contract_id, start_time, end_time, unit=BAR_UNIT_MINUTE, unit_number=5, 
                  limit=1000, live=False, include_partial_bar=False, token=None):
    """
    Retrieve historical bars from TopstepX.
    
    Parameters:
    - contract_id: str - Contract ID (e.g., "CON.F.US.RTY.Z24")
    - start_time: str or datetime - Start time in ISO format (e.g., "2024-12-01T00:00:00Z")
    - end_time: str or datetime - End time in ISO format (e.g., "2024-12-31T21:00:00Z")
    - unit: int - Time unit (use BAR_UNIT_* constants)
        BAR_UNIT_TICK (1), BAR_UNIT_MINUTE (2), BAR_UNIT_HOUR (3),
        BAR_UNIT_DAY (4), BAR_UNIT_WEEK (5), BAR_UNIT_MONTH (6)
    - unit_number: int - Number of units per bar (e.g., 5 for 5-minute bars)
    - limit: int - Maximum number of bars to retrieve
    - live: bool - Whether to use live or simulated data
    - include_partial_bar: bool - Whether to include incomplete bars
    - token: str - Session token (if None, will authenticate)
    
    Returns:
    - dict with 'bars' array containing OHLCV data
    
    Bar format:
    {
        "t": "2024-12-20T14:00:00+00:00",  # Timestamp
        "o": 2208.100000000,                # Open
        "h": 2217.000000000,                # High
        "l": 2206.700000000,                # Low
        "c": 2210.100000000,                # Close
        "v": 87                              # Volume
    }
    
    Example:
        from topstepx_client import retrieve_bars, BAR_UNIT_HOUR
        bars = retrieve_bars("CON.F.US.ES.H25", "2024-12-01T00:00:00Z",
                           "2024-12-31T23:59:59Z", unit=BAR_UNIT_HOUR)
    """
    from datetime import datetime as dt
    
    # Convert datetime objects to ISO format strings if needed
    if isinstance(start_time, dt):
        start_time = start_time.isoformat() + "Z" if start_time.tzinfo is None else start_time.isoformat()
    if isinstance(end_time, dt):
        end_time = end_time.isoformat() + "Z" if end_time.tzinfo is None else end_time.isoformat()
    
    endpoint = "/api/History/retrieveBars"
    payload = {
        "contractId": contract_id,
        "live": live,
        "startTime": start_time,
        "endTime": end_time,
        "unit": unit,
        "unitNumber": unit_number,
        "limit": limit,
        "includePartialBar": include_partial_bar
    }
    resp, _ = topstepx_request("POST", endpoint, token=token, json=payload)
    print(f"[TopstepX] Retrieved {len(resp.get('bars', []))} bars")
    return resp

if __name__ == "__main__":
    """
    Demo script showing authentication and order placement.
    
    Authentication Methods:
    
    1. API Key Authentication (individual users):
       Set environment variables:
       - TOPSTEPX_USERNAME
       - TOPSTEPX_API_KEY
       
    2. Application Authentication (authorized firms):
       Set environment variables:
       - TOPSTEPX_APP_USERNAME
       - TOPSTEPX_APP_PASSWORD
       - TOPSTEPX_APP_DEVICE_ID
       - TOPSTEPX_APP_ID
       - TOPSTEPX_APP_VERIFY_KEY
    
    The authenticate() function will auto-detect which method to use.
    You can also call authenticate_with_key() or authenticate_with_app() directly.
    """
    try:
        # Auto-detect authentication method based on environment variables
        token = authenticate()
        print("Session token:", token[:20] + "..." if len(token) > 20 else token)
        
        print("\n[TopstepX] Validating token...")
        valid = validate_token(token)
        print("Token valid?", valid)
        
        print("\n[TopstepX] Searching for active accounts...")
        accounts = search_accounts(token)
        if not accounts or len(accounts) == 0:
            print("No accounts found!")
            exit(1)
        account_id = accounts[0].get("id") if isinstance(accounts[0], dict) else accounts[0]["id"]
        print("Using account_id:", account_id)
        
        print("\n[TopstepX] Searching for available contracts...")
        contracts = search_contracts(token, live=False)
        if not contracts or len(contracts) == 0:
            print("No contracts found!")
            exit(1)
        contract_id = contracts[0].get("id") if isinstance(contracts[0], dict) else contracts[0]["id"]
        print("Using contract_id:", contract_id)
        
        # Place a test order on E-Mini S&P 500 (ES), 1 contract, market order, sell
        print("\n[TopstepX] Placing test order on E-Mini S&P 500 (ES)...")
        es_contract_id = None
        for c in contracts:
            if c.get("name") == "ESU5" or c.get("description", "").startswith("E-Mini S&P 500"):
                es_contract_id = c["id"]
                break
        if not es_contract_id:
            print("E-Mini S&P 500 contract not found in contracts list!")
            exit(1)
        
        # Example: Retrieve historical bars
        print("\n[TopstepX] Retrieving historical bars...")
        from datetime import datetime, timedelta
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=24)
        
        bars_resp = retrieve_bars(
            contract_id=es_contract_id,
            start_time=start_time,
            end_time=end_time,
            unit=BAR_UNIT_HOUR,  # Hour bars
            unit_number=1,  # 1-hour bars
            limit=24,  # Last 24 hours
            live=False,
            token=token
        )
        
        if bars_resp.get('success'):
            bars = bars_resp.get('bars', [])
            print(f"Retrieved {len(bars)} bars")
            if bars:
                print("Latest bar:")
                latest = bars[0]
                print(f"  Time: {latest['t']}")
                print(f"  Open: {latest['o']:.2f}")
                print(f"  High: {latest['h']:.2f}")
                print(f"  Low: {latest['l']:.2f}")
                print(f"  Close: {latest['c']:.2f}")
                print(f"  Volume: {latest['v']}")
        
        # Example order placement (commented out for safety)
        print("\n[TopstepX] Order placement example (disabled)...")
        print("To place a live order, uncomment the code below:")
        print(f"# order_resp = place_order(")
        print(f"#     account_id={account_id},")
        print(f"#     contract_id='{es_contract_id}',")
        print(f"#     size=1,")
        print(f"#     side=ORDER_SIDE_SELL,  # or ORDER_SIDE_BUY")
        print(f"#     order_type=ORDER_TYPE_MARKET,")
        print(f"#     token=token")
        print(f"# )")
        print(f"\n# Available constants:")
        print(f"# ORDER_SIDE_SELL={ORDER_SIDE_SELL}, ORDER_SIDE_BUY={ORDER_SIDE_BUY}")
        print(f"# ORDER_TYPE_MARKET={ORDER_TYPE_MARKET}")
        print(f"# BAR_UNIT_MINUTE={BAR_UNIT_MINUTE}, BAR_UNIT_HOUR={BAR_UNIT_HOUR}, BAR_UNIT_DAY={BAR_UNIT_DAY}")
        
    except Exception as e:
        print("Workflow failed:", e) 
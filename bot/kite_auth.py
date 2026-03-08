"""
Zerodha Kite Connect Authentication Module
"""
import hashlib
import requests
from kiteconnect import KiteConnect


def get_kite_client(api_key: str, access_token: str = None) -> KiteConnect:
    kite = KiteConnect(api_key=api_key)
    if access_token:
        kite.set_access_token(access_token)
    return kite


def generate_login_url(api_key: str) -> str:
    kite = KiteConnect(api_key=api_key)
    return kite.login_url()


def generate_access_token(api_key: str, api_secret: str, request_token: str) -> str:
    kite = KiteConnect(api_key=api_key)
    data = kite.generate_session(request_token, api_secret=api_secret)
    return data["access_token"]


def get_profile(kite: KiteConnect) -> dict:
    try:
        return kite.profile()
    except Exception as e:
        return {"error": str(e)}


def get_margins(kite: KiteConnect) -> dict:
    try:
        return kite.margins()
    except Exception as e:
        return {"error": str(e)}

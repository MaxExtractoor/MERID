import os
import jwt
from typing import Optional, Dict, Any

# JWT rotation utilities for MERID backend
PRIMARY = os.getenv("JWT_SECRET_KEY")
NEXT = os.getenv("JWT_SECRET_KEY_NEXT")

def sign_access(payload: Dict[str, Any]) -> str:
    """Sign access token with new key if available, else primary"""
    key = NEXT or PRIMARY
    if not key:
        raise ValueError("No JWT secret key configured")
    return jwt.encode(payload, key, algorithm="HS256")

def verify_access(token: str) -> Dict[str, Any]:
    """Verify token using either primary or next key"""
    for key in filter(None, [PRIMARY, NEXT]):
        try:
            return jwt.decode(token, key, algorithms=["HS256"])
        except jwt.InvalidTokenError:
            continue
    raise jwt.InvalidTokenError("invalid token")

def is_rotation_active() -> bool:
    """Check if rotation is in progress (both keys present)"""
    return bool(PRIMARY and NEXT)

def get_key_status() -> Dict[str, bool]:
    """Get status of JWT keys for debugging"""
    return {
        "primary_configured": bool(PRIMARY),
        "next_configured": bool(NEXT),
        "rotation_active": is_rotation_active()
    }

# Example usage in FastAPI endpoint:
@app.post("/auth/login")
async def login(credentials: AuthCredentials):
    payload = {
        "sub": credentials.email,
        "role": "trader",
        "exp": datetime.utcnow() + timedelta(minutes=15)  # Short-lived
    }
    access_token = sign_access(payload)
    refresh_token = create_refresh_token(payload)
    
    return {
        "access": access_token,
        "refresh": refresh_token
    }

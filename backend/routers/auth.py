from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas import LoginRequest, TokenResponse
from security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: LoginRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    if db.query(User).filter_by(username=payload.username).one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username already exists")
    db.add(User(username=payload.username, password_hash=hash_password(payload.password), role="USER"))
    return {"username": payload.username}


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter_by(username=payload.username).one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    return TokenResponse(access_token=create_access_token(user.username, user.role), role=user.role)

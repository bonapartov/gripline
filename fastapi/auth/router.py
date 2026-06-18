from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db
from models.user import AuthUser, UserProfile
from auth.jwt import verify_password, create_access_token, decode_token
from jose import JWTError

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _build_token(user: AuthUser, profile: UserProfile | None) -> dict:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "roles": profile.roles if profile else [],
        "driver_id": profile.driver_id if profile else None,
        "team_id": profile.team_id if profile else None,
    })


@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Авторизация: username + password → JWT на 7 дней."""
    user = db.query(AuthUser).filter(
        AuthUser.username == form_data.username,
        AuthUser.is_active == True,
    ).first()

    if not user or not verify_password(form_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )

    profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    token = _build_token(user, profile)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/refresh")
def refresh_token(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """Обновление токена: принимает действующий JWT → выдаёт новый с обновлённым сроком."""
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError):
        raise HTTPException(status_code=401, detail="Невалидный токен")

    user = db.query(AuthUser).filter(AuthUser.id == user_id, AuthUser.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    token = _build_token(user, profile)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
def get_me(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """Профиль текущего пользователя (все роли)."""
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError):
        raise HTTPException(status_code=401, detail="Невалидный токен")

    user = db.query(AuthUser).filter(AuthUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()

    return {
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "roles": profile.roles if profile else [],
        "driver_id": profile.driver_id if profile else None,
        "team_id": profile.team_id if profile else None,
        "verified": profile.verified if profile else False,
    }

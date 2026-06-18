from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db
from models.race import PushToken
from auth.jwt import decode_token
from jose import JWTError

router = APIRouter(prefix="/push", tags=["push"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class PushRegisterRequest(BaseModel):
    token: str


def get_current_user_id(token: str = Depends(oauth2_scheme)):
    try:
        payload = decode_token(token)
        return int(payload.get("sub"))
    except (JWTError, TypeError):
        raise HTTPException(status_code=401, detail="Невалидный токен")


@router.post("/register")
def register_push_token(
    body: PushRegisterRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Регистрация FCM-токена устройства. Повторная регистрация того же токена игнорируется."""
    existing = db.query(PushToken).filter(PushToken.token == body.token).first()
    if existing:
        # Токен уже зарегистрирован — обновляем владельца если нужно
        if existing.user_id != user_id:
            existing.user_id = user_id
            db.commit()
        return {"status": "ok"}

    push = PushToken(user_id=user_id, token=body.token)
    db.add(push)
    db.commit()
    return {"status": "registered"}


@router.delete("/register")
def unregister_push_token(
    body: PushRegisterRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Удаление FCM-токена при выходе из приложения."""
    db.query(PushToken).filter(
        PushToken.token == body.token,
        PushToken.user_id == user_id,
    ).delete()
    db.commit()
    return {"status": "ok"}

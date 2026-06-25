from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.race import Team, TeamMembership
from models.driver import Driver

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("")
def list_teams(db: Session = Depends(get_db)):
    """Список команд."""
    teams = db.query(Team).order_by(Team.name).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "slug": t.slug,
            "description": t.description,
        }
        for t in teams
    ]


@router.get("/{team_id}")
def get_team(team_id: int, db: Session = Depends(get_db)):
    """Профиль команды с активными пилотами."""
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Команда не найдена")

    memberships = (
        db.query(TeamMembership, Driver)
        .join(Driver, TeamMembership.driver_id == Driver.id)
        .filter(TeamMembership.team_id == team_id, TeamMembership.is_active == True)
        .all()
    )

    pilots = [
        {
            "id": driver.id,
            "name": f"{driver.first_name} {driver.last_name}",
            "slug": driver.slug,
            "city": driver.city,
            "class_id": m.race_class_id,
        }
        for m, driver in memberships
    ]

    return {
        "id": team.id,
        "name": team.name,
        "slug": team.slug,
        "description": team.description,
        "manager_name": team.manager_name,
        "manager_email": team.manager_email,
        "pilots": pilots,
    }

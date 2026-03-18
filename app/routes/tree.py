from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_auth
from app.database import get_db
from app.models.person import Person, Visibility
from app.models.relationships import ParentChild, Partnership
from app.schemas import (
    ParentChildResponse,
    PartnershipResponse,
    PersonSummary,
    TreeResponse,
    person_to_summary,
)

router = APIRouter(prefix="/api", tags=["tree"])


@router.get("/tree", response_model=TreeResponse)
async def get_tree(
    current_user: Person = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    # Get root person
    result = await db.execute(select(Person).where(Person.is_root == True))
    root = result.scalar_one_or_none()
    root_id = root.id if root else ""

    # Get all visible persons
    result = await db.execute(
        select(Person).where(Person.visibility != Visibility.hidden.value)
    )
    persons = result.scalars().all()
    visible_person_ids = {person.id for person in persons}

    # Get all parent-child relationships
    result = await db.execute(select(ParentChild))
    parent_children = [
        relationship
        for relationship in result.scalars().all()
        if relationship.parent_id in visible_person_ids
        and relationship.child_id in visible_person_ids
    ]

    # Get all partnerships
    result = await db.execute(select(Partnership))
    partnerships = [
        relationship
        for relationship in result.scalars().all()
        if relationship.person_a_id in visible_person_ids
        and relationship.person_b_id in visible_person_ids
    ]

    return TreeResponse(
        root_id=root_id,
        persons=[person_to_summary(p) for p in persons],
        parent_child=[ParentChildResponse.model_validate(pc) for pc in parent_children],
        partnerships=[PartnershipResponse.model_validate(p) for p in partnerships],
    )

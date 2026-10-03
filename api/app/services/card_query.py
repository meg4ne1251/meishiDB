"""Shared text search for the card list and exports."""

from sqlalchemy import or_
from app.models.card import Card, CardField
from app.services import search_index

SEARCH_FIELDS = (
    "person_name",
    "person_name_kana",
    "company",
    "department",
    "title",
    "email",
    "phone",
    "mobile",
    "address",
)


async def apply_search(base, viewer_id, query):
    ids = await search_index.search_card_ids(viewer_id, query)
    if ids is not None:
        return base.where(Card.id.in_(ids))
    escaped = query.replace("~", "~~").replace("%", "~%").replace("_", "~_")
    like = f"%{escaped}%"
    return base.join(CardField, CardField.card_id == Card.id, isouter=True).where(
        or_(*(getattr(CardField, name).ilike(like, escape="~") for name in SEARCH_FIELDS))
    )

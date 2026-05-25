"""
Plan loader utilities — async DB-backed replacement for the static PLANS dict.

Usage:
    plan = await get_plan(session, "basic")
    plans = await get_visible_plans(session)
    all_plans = await get_all_plans(session)
"""
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plan import Plan


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

async def get_plan(session: AsyncSession, code: str) -> dict | None:
    """Return a single plan as dict, or None if not found."""
    result = await session.execute(select(Plan).where(Plan.code == code))
    plan = result.scalar_one_or_none()
    return plan.to_dict() if plan else None


async def get_visible_plans(session: AsyncSession) -> list[dict]:
    """Return all visible plans sorted by sort_order (for user-facing keyboards)."""
    result = await session.execute(
        select(Plan)
        .where(Plan.is_visible.is_(True))
        .order_by(Plan.sort_order.asc(), Plan.id.asc())
    )
    return [p.to_dict() for p in result.scalars().all()]


async def get_all_plans(session: AsyncSession) -> list[dict]:
    """Return all plans (including hidden) sorted by sort_order (for admin)."""
    result = await session.execute(
        select(Plan).order_by(Plan.sort_order.asc(), Plan.id.asc())
    )
    return [p.to_dict() for p in result.scalars().all()]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    """Convert a plan name to a safe lowercase code slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s]", "", slug)
    slug = re.sub(r"\s+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "plan"

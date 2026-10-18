"""Default ship dates for the supported Katy warehouse."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

SHIPPER_TIMEZONE = ZoneInfo("America/Chicago")


def default_ship_date(now: datetime | None = None) -> str:
    local = datetime.now(SHIPPER_TIMEZONE) if now is None else now.astimezone(SHIPPER_TIMEZONE)
    day = local.date()
    if local.time() >= time(17):
        day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()

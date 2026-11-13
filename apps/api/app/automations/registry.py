from typing import Any

from app.automations.base import Service
from app.automations.digest import Digest
from app.automations.followup import FollowupService
from app.automations.lead_reminders import LeadReminders
from app.automations.stock import Stock

SERVICES: dict[str, Service[Any]] = {
    service.kind: service for service in (Digest(), Stock(), FollowupService(), LeadReminders())
}

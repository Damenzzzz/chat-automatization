import uuid

import pytest

from app.channels.instagram import InstagramAdapter
from app.channels.registry import get_adapters
from app.channels.types import ChannelAdapter, ChannelConfig, ChannelError, OutgoingMessage

CONFIG = ChannelConfig(id=uuid.uuid4(), tenant_id=uuid.uuid4(), type="instagram", status="pending")


def test_every_channel_type_has_adapter_with_matching_type() -> None:
    adapters = get_adapters()
    assert set(adapters) == {"telegram", "whatsapp", "web", "instagram"}
    assert all(adapter.type == name for name, adapter in adapters.items())


def test_stub_satisfies_adapter_interface() -> None:
    adapter: ChannelAdapter = InstagramAdapter()
    assert adapter.parse(CONFIG, {"entry": [{"messaging": [{}]}]}) == []


async def test_stub_refuses_to_send_instead_of_silently_dropping() -> None:
    with pytest.raises(ChannelError):
        await InstagramAdapter().send(CONFIG, "1", OutgoingMessage(text="x"))


async def test_stub_check_explains_status() -> None:
    result = await InstagramAdapter().check(CONFIG)
    assert not result.ok
    assert result.error is not None and "App Review" in result.error

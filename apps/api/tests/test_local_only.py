import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[3] / "infra" / "docker-compose.yml"


def test_every_published_port_listens_on_localhost_only() -> None:
    ports = re.findall(r'^\s+- "([^"\s]*:\d+)"$', COMPOSE.read_text(), flags=re.MULTILINE)
    assert len(ports) >= 7
    exposed = [port for port in ports if not port.startswith("127.0.0.1:")]
    assert exposed == [], f"порт открыт в сеть: {exposed}"

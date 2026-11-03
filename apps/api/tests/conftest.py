import os

_TEST_ENV = {
    "ENV": "test",
    "DATABASE_URL": "postgresql+asyncpg://satushy:satushy@localhost:5432/satushy_test",
    "REDIS_URL": "redis://localhost:6379/1",
    "S3_ENDPOINT_URL": "http://localhost:9000",
    "S3_ACCESS_KEY": "test",
    "S3_SECRET_KEY": "test",
    "FERNET_KEY": "test",
    "JWT_SECRET": "test",
}
for key, value in _TEST_ENV.items():
    os.environ.setdefault(key, value)

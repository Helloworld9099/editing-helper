"""Shared, atomic quota utilities for the guest demo endpoint."""
import os

# Use a Redis Cluster hash tag so all keys in the atomic script share a slot.
QUOTA_SCRIPT = """
for i = 1, #KEYS do
  local used = tonumber(redis.call('GET', KEYS[i]) or '0')
  if used >= tonumber(ARGV[i]) then return 0 end
end
for i = 1, #KEYS do
  local count = redis.call('INCR', KEYS[i])
  if count == 1 then redis.call('EXPIRE', KEYS[i], tonumber(ARGV[#KEYS + i])) end
end
return 1
"""


def positive_limit(name: str, default: int, max_value: int = 100000) -> int:
    value = os.environ.get(name, str(default))
    try:
        n = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"{name} must be a positive integer.") from None
    if n < 1 or n > max_value:
        raise ValueError(f"{name} must be between 1 and {max_value}.")
    return n

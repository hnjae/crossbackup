import secrets
import string
from typing import List

_ASCII: List[str] = list(f"{string.ascii_letters}{string.digits}")


def get_random_str(length: int, groups=_ASCII) -> str:
    return "".join(secrets.choice(groups) for _ in range(length))

from dataclasses import dataclass


@dataclass
class AlertResult:
    delivered: bool
    suppressed: bool
    detail: str

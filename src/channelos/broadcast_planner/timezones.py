"""Pinned IANA rules and explicit local-clock gap/fold resolution."""
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
from importlib import resources
from zoneinfo import ZoneInfo


@lru_cache(maxsize=128)
def get_zone(name):
    if not isinstance(name, str) or name.startswith('/') or any(part in ('', '.', '..') for part in name.split('/')) or '\\' in name:
        raise ValueError('invalid IANA time-zone name')
    # Use the same packaged rules on Windows and Unix, rather than depending on
    # whichever version an operating system happens to have installed.
    path = resources.files('tzdata.zoneinfo').joinpath(*name.split('/'))
    with path.open('rb') as handle:
        return ZoneInfo.from_file(handle, key=name)


def local_instant(day, clock, zone, *, fold='first', gap='next_valid'):
    hour, minute = map(int, clock.split(':'))
    if hour == 24:
        day, hour = day + timedelta(days=1), 0
    naive = datetime.combine(day, time(hour, minute))

    def candidates(value):
        result = set()
        for number in (0, 1):
            instant = value.replace(tzinfo=zone, fold=number).astimezone(timezone.utc)
            if instant.astimezone(zone).replace(tzinfo=None) == value:
                result.add(instant)
        return sorted(result)

    choices = candidates(naive)
    if choices:
        return choices[-1] if fold == 'second' else choices[0]
    if gap == 'skip':
        return None
    # Covers hour changes as well as historical skipped calendar dates.
    for _ in range(2881):
        naive += timedelta(minutes=1)
        choices = candidates(naive)
        if choices:
            return choices[-1] if fold == 'second' else choices[0]
    raise ValueError('no valid local time within two days of this clock change')

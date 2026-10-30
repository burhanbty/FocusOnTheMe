"""04:00 gün sınırı ve üst üste gün serisi (streak) hesaplama modülü."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

from app.config import LOGICAL_DAY_BOUNDARY_HOUR


def get_logical_date(dt: datetime | None = None, boundary_hour: int = LOGICAL_DAY_BOUNDARY_HOUR) -> str:
    """Verilen zaman damgası için mantıksal günü YYYY-MM-DD biçiminde döndürür.

    Gün sınırı varsayılan olarak 04:00'tür. Örneğin saat 03:59 hala bir önceki
    takvim gününe dahildir; 04:00 itibarıyla yeni mantıksal gün başlar.
    """
    current = dt if dt is not None else datetime.now()
    shifted = current - timedelta(hours=boundary_hour)
    return shifted.date().isoformat()


def parse_logical_date(date_str: str) -> date:
    """YYYY-MM-DD biçimindeki mantıksal gün dizgesini date nesnesine çevirir."""
    return date.fromisoformat(date_str.strip())


def calculate_streak(
    completed_dates: Iterable[str],
    reference_logical_date: str | None = None,
) -> int:
    """Tamamlanmış mantıksal gün kümesine göre aktif üst üste gün serisini hesaplar.

    Kurallar:
    - Eğer `reference_logical_date` (bugün) tamamlanmışsa seri bugünden geriye doğru sayılır.
    - Eğer bugün henüz tamamlanmamış ama dün tamamlanmışsa seri dünden geriye doğru sayılır.
    - Hem bugün hem dün tamamlanmamışsa seri 0'dır.
    """
    completed_set: set[date] = set()
    for item in completed_dates:
        if not item:
            continue
        try:
            completed_set.add(parse_logical_date(item))
        except ValueError:
            continue

    if not completed_set:
        return 0

    ref_str = reference_logical_date or get_logical_date()
    ref_date = parse_logical_date(ref_str)

    if ref_date in completed_set:
        cursor = ref_date
    elif (ref_date - timedelta(days=1)) in completed_set:
        cursor = ref_date - timedelta(days=1)
    else:
        return 0

    streak = 0
    while cursor in completed_set:
        streak += 1
        cursor -= timedelta(days=1)

    return streak

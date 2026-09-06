"""The committed cohort must stay customer-free and match the declared schema."""
import re

from sellthrough import paths
from sellthrough.cohort import FIELDS, read_cohort

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")


def test_committed_cohort_is_clean():
    p = paths.cohort_path()
    text = p.read_text()
    assert text.splitlines()[0] == ",".join(FIELDS)
    assert not EMAIL.search(text) and not PHONE.search(text)
    rows = read_cohort(p)
    assert len(rows) > 1000
    assert all(r.days >= 0 for r in rows)
    assert all((r.event == 1) == (r.first_sale_at is not None) for r in rows)
    assert all(r.snapshot == rows[0].snapshot for r in rows)

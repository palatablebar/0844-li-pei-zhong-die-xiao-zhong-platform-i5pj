from app.catalog import SPEC
from app.domain.calculate import calculate_rows
from app.domain.decision import decide_rows
from app.domain.prepare import prepare_rows
from app.intake.service import load

CLEAN = [{'claim_id': 'K1',
  'member_id': 'M1',
  'service_date': '2026-11-01',
  'payer': 'MEDICARE',
  'billed_cents': '10000',
  'approved_cents': '8000',
  'deductible_cents': '1000'},
 {'claim_id': 'K2',
  'member_id': 'M1',
  'service_date': '2026-11-01',
  'payer': 'PRIVATE',
  'billed_cents': '6000',
  'approved_cents': '2000',
  'deductible_cents': '0'},
 {'claim_id': 'K3',
  'member_id': 'M2',
  'service_date': '2026-11-02',
  'payer': 'PRIVATE',
  'billed_cents': '5000',
  'approved_cents': '4500',
  'deductible_cents': '500'},
 {'claim_id': 'K4',
  'member_id': 'M3',
  'service_date': '2026-11-03',
  'payer': 'MEDICARE',
  'billed_cents': '8000',
  'approved_cents': '5000',
  'deductible_cents': '1000'},
 {'claim_id': 'K5',
  'member_id': 'M3',
  'service_date': '2026-11-03',
  'payer': 'SELF',
  'billed_cents': '8000',
  'approved_cents': '3000',
  'deductible_cents': '0'}]


def row(**changes):
    item = dict(CLEAN[0])
    item.update(changes)
    return item


def calc(rows):
    items, issues = prepare_rows(rows)
    return calculate_rows(items), issues


def run(rows):
    items, issues = prepare_rows(rows)
    return decide_rows(calculate_rows(items)), issues


def run_profile(profile):
    return run(load(profile)["rows"])

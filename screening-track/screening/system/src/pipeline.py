"""The whole route: alerts and hits -> fact cards -> decisions -> output lines.

ALERT -> find the customer -> merge their records -> customer picture ---+
                                                                         +-> compare -> output line
HIT  ------------------------------------------------> hit picture ------+

Every hit always gets a line. If anything fails for a hit it is answered
REVIEW / INSUFFICIENT_DATA, the safe side; the failure is logged to stderr.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

from customer_facts import build_customer_facts
from decide import decide
from explain import explain, explain_ambiguous, explain_no_customer
from hit_facts import build_hit_facts
from load import Data, load, screened
from resolve_customer import resolve
from schema import Decision, FactCard

SAFETY_NET_REASON = ("The system could not assemble enough verified facts about the customer "
                     "and the hit to settle this match, so it is left for a human to review.")


def safety_net(alert_id: str, hit_id: str, why: str = SAFETY_NET_REASON) -> Decision:
    return Decision(alert_id=alert_id, hit_id=hit_id, decision="REVIEW",
                    reason_code="INSUFFICIENT_DATA", evidence_ids=[],
                    resolved_customer_id=None, explanation=why)


class Pipeline:
    """Holds the loaded data and caches the customer side per alert, since an
    alert's hits all share the same customer."""

    def __init__(self, data: Data, log=sys.stderr):
        self.data = data
        self.log = log
        self._customers: dict[str, list] = {}

    def customer_cards(self, alert: dict):
        aid = alert["alert_id"]
        if aid not in self._customers:
            cands = resolve(self.data, alert)
            self._customers[aid] = [build_customer_facts(self.data, c.record_ids, c.link).facts for c in cands]
        return self._customers[aid]

    def decide_one(self, alert: dict | None, hit: dict) -> Decision:
        hit_id = hit["hit_id"]
        if alert is None:
            return safety_net(hit.get("alert_id"), hit_id,
                              "The hit's alert is not in alerts.jsonl, so the customer cannot be resolved.")
        alert_id = alert["alert_id"]
        customers = self.customer_cards(alert)
        hit_facts = build_hit_facts(self.data, hit)
        if not customers:
            s = screened(alert)
            link = "account" if alert.get("account_ref") else "login" if alert.get("login_handle") \
                else "email" if alert.get("email") else "none"
            return explain_no_customer(alert_id, hit_id, s.get("name") or "the screened customer", link)
        results = []
        for cust in customers:
            card = FactCard(alert_id=alert_id, hit_id=hit_id, screened_at=alert.get("screened_at"),
                            customer=cust, hit=hit_facts)
            decision, assessment = decide(card, self.data.variants)
            results.append((explain(card, decision, assessment), card))
        if len(results) == 1:
            return results[0][0]
        return explain_ambiguous(alert_id, hit_id, results)

    def decide_all(self) -> list[Decision]:
        decisions: list[Decision] = []
        for hit_id in self.data.hit_order:
            hit = self.data.hits[hit_id]
            try:
                decisions.append(self.decide_one(self.data.alerts.get(hit.get("alert_id")), hit))
            except Exception:  # fail closed: a crash must never clear a hit
                print(f"[warn] {hit_id}: {traceback.format_exc().splitlines()[-1]}", file=self.log)
                decisions.append(safety_net(hit.get("alert_id"), hit_id))
        return decisions


def write_output(decisions: list[Decision], out_path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for d in decisions:
            f.write(json.dumps(d.to_output_line(), ensure_ascii=False) + "\n")


def run(data_dir, out_path, log=sys.stderr) -> list[Decision]:
    t0 = time.time()
    data = load(data_dir)
    print(f"[info] loaded {len(data.alerts)} alerts, {len(data.hits)} hits, "
          f"{len(data.customers)} customers in {time.time() - t0:.1f}s", file=log)
    decisions = Pipeline(data, log).decide_all()
    write_output(decisions, out_path)
    counts: dict[str, int] = {}
    for d in decisions:
        counts[d.decision] = counts.get(d.decision, 0) + 1
    print(f"[info] wrote {len(decisions)} lines to {out_path} in {time.time() - t0:.1f}s: {counts}", file=log)
    return decisions

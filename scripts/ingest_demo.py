from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.schemas import IngestTextRequest
from app.service import get_service


def main() -> None:
    svc = get_service()
    docs = [
        IngestTextRequest(
            doc_id="lit_meta_2024_001",
            title="Meta-analysis of ASM efficacy",
            doc_type="literature",
            text=(
                "Systematic review evidence suggests that some anti-seizure medications can reduce seizure frequency "
                "in focal epilepsy during a 12-week observation window."
                "Combination therapy should monitor interaction risk and cumulative adverse effects."
            ),
            metadata={"year": 2024, "type": "meta-analysis"},
        ),
        IngestTextRequest(
            doc_id="cli_followup_2025_013",
            title="Epilepsy Follow-up Case",
            doc_type="clinical",
            text=(
                "A 26-year-old patient reported seizure frequency increasing from monthly to weekly in the last 3 months."
                "The patient had partial adherence and poor sleep patterns."
                "Recommendation: reinforce adherence, manage triggers, keep a seizure diary, and follow up with EEG review."
            ),
            metadata={"setting": "outpatient"},
        ),
    ]

    for doc in docs:
        out = svc.ingest_text(doc)
        print(
            f"ingested doc_id={out.doc_id}, parents={out.inserted_parents}, "
            f"children={out.inserted_children}"
        )
    print(f"knowledge base count={svc.kb_count()}")


if __name__ == "__main__":
    main()

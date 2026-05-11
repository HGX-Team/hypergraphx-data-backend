"""
Shared license inference rules for dataset configs.

These rules support:
- `scripts/maintenance/populate_licenses.py`: infer license fields from the config `source`.
- `scripts/maintenance/verify_licenses.py`: validate config license fields for consistency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class LicenseRule:
    pattern: str
    license_id: str
    license_url: str
    license_note: Optional[str] = None
    confidence: str = "high"  # "high" | "medium" | "low"
    evidence_url: Optional[str] = None


LICENSE_ID_ALIASES = {
    # Prefer SPDX identifiers.
    "GPL-3.0": "GPL-3.0-only",
}


SOURCE_LICENSE_RULES: list[LicenseRule] = [
    LicenseRule(
        pattern="sociopatterns.org/datasets/sfhh-conference-data-set",
        license_id="CC0-1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        license_note="SFHH conference data set is CC0 per SocioPatterns terms on the dataset page.",
        confidence="high",
        evidence_url="http://www.sociopatterns.org/datasets/sfhh-conference-data-set/",
    ),
    LicenseRule(
        pattern="sociopatterns.org/datasets/contacts-in-a-workplace",
        license_id="CC0-1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        license_note="Contacts in a workplace is CC0 per SocioPatterns terms on the dataset page.",
        confidence="high",
        evidence_url="http://www.sociopatterns.org/datasets/contacts-in-a-workplace/",
    ),
    LicenseRule(
        pattern="sociopatterns.org",
        license_id="CC-BY-NC-SA-3.0",
        license_url="https://creativecommons.org/licenses/by-nc-sa/3.0/",
        license_note="SocioPatterns data is licensed under CC-BY-NC-SA 3.0. Non-commercial use only.",
        confidence="high",
        evidence_url="http://www.sociopatterns.org/datasets/",
    ),
    LicenseRule(
        pattern="archive.ics.uci.edu",
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        license_note=None,
        confidence="high",
        evidence_url="https://archive.ics.uci.edu/",
    ),
    LicenseRule(
        pattern="github.com/jianhao2016/AllSet",
        license_id="MIT",
        license_url="https://opensource.org/licenses/MIT",
        license_note="Data sourced from AllSet repository (MIT license). Original data may have different terms.",
        confidence="medium",
        evidence_url="https://github.com/jianhao2016/AllSet",
    ),
    LicenseRule(
        pattern="kaggle.com/datasets/csanhueza/the-marvel-universe-social-network",
        license_id="CC-BY-3.0",
        license_url="https://creativecommons.org/licenses/by/3.0/",
        license_note=None,
        confidence="medium",
        evidence_url="https://www.kaggle.com/datasets/csanhueza/the-marvel-universe-social-network",
    ),
    LicenseRule(
        pattern="github.com/lingcheng99/Flavor-Network",
        license_id="GPL-3.0-only",
        license_url="https://www.gnu.org/licenses/gpl-3.0.html",
        license_note="Repository is GPL-3.0; verify whether the specific data files impose additional terms.",
        confidence="medium",
        evidence_url="https://github.com/lingcheng99/Flavor-Network",
    ),
    LicenseRule(
        pattern="cloud.google.com/bigquery/public-data",
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        license_note="Bitcoin blockchain data is public; this project treats these BigQuery public dataset sources as CC-BY-4.0.",
        confidence="medium",
        evidence_url="https://cloud.google.com/bigquery/public-data",
    ),
    LicenseRule(
        pattern="docs.cloud.google.com/bigquery/public-data",
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        license_note="Bitcoin blockchain data is public; this project treats these BigQuery public dataset sources as CC-BY-4.0.",
        confidence="medium",
        evidence_url="https://docs.cloud.google.com/bigquery/public-data",
    ),
    LicenseRule(
        pattern="royalsocietypublishing.org",
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        license_note="Supplementary data may be CC-BY-4.0 for Open Access articles; verify on the article page.",
        confidence="low",
        evidence_url="https://royalsocietypublishing.org/",
    ),
    LicenseRule(
        pattern="static-content.springer.com",
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        license_note="Supplementary data may be CC-BY-4.0 for Open Access articles; verify on the article page.",
        confidence="low",
        evidence_url="https://static-content.springer.com/",
    ),
]


def normalize_license_id(license_id: str) -> str:
    license_id = (license_id or "").strip()
    return LICENSE_ID_ALIASES.get(license_id, license_id)


def iter_matching_rules(
    source_url: str, rules: Iterable[LicenseRule] = SOURCE_LICENSE_RULES
) -> Iterable[LicenseRule]:
    source_lower = (source_url or "").lower()
    for rule in rules:
        if rule.pattern.lower() in source_lower:
            yield rule


def first_matching_rule(
    source_url: str, rules: Iterable[LicenseRule] = SOURCE_LICENSE_RULES
) -> Optional[LicenseRule]:
    return next(iter_matching_rules(source_url, rules), None)

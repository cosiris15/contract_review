"""Baseline texts for FIDIC Silver Book 2017 key clauses.

Important:
- These are working baselines for engineering review workflows.
- They are not guaranteed to be verbatim official FIDIC text.
- Replace with licensed official text where strict legal redline precision is required.
"""

from __future__ import annotations

FIDIC_SILVER_BOOK_2017_BASELINE: dict[str, str] = {
    "1.1": """1.1 Definitions and Interpretation
In these Conditions, including the Particular Conditions and General Conditions, defined terms
carry the meanings assigned to them in this clause and throughout the Contract.
Words denoting one gender include all genders; singular includes plural where the context requires.
References to agreements, laws, and approvals include amendments and replacements.
Headings do not limit interpretation. The Contract is interpreted as a whole and all documents are
read together unless a stated priority requires otherwise.
""",
    "1.5": """1.5 Priority of Documents
The Contract documents are mutually explanatory. For interpretation and consistency, the following
priority generally applies: Contract Agreement, Particular Conditions Part A, Particular Conditions
Part B, General Conditions, Employer's Requirements, Schedules, and other forming documents.
Where ambiguity or discrepancy appears, the Engineer/Employer representative may issue clarifications
consistent with the Contract mechanism and applicable law.
""",
    "4.1": """4.1 Contractor's General Obligations
The Contractor shall design (to the extent required), execute, complete, and remedy defects in the Works
in accordance with the Contract. The Contractor provides all Contractor's Documents, personnel,
contractor's equipment, temporary works, materials, and management resources necessary to deliver the Works.
The Contractor is responsible for means, methods, sequencing, and compliance with quality, safety,
and statutory requirements except to the extent risks are expressly allocated elsewhere in the Contract.
""",
    "4.12": """4.12 Unforeseeable Physical Conditions
If the Contractor encounters physical conditions that were not reasonably foreseeable at the Base Date,
the Contractor shall promptly give notice and continue performance while mitigation and assessment proceed.
After proper substantiation, entitlement may include extension of time and/or Cost as provided by the Contract.
The determination process considers records, site data, and whether an experienced contractor could have
reasonably anticipated such conditions.
""",
    "8.2": """8.2 Time for Completion
The Contractor shall complete the Works (and each Section, if any) within the Time for Completion,
including achieving conditions required for taking-over.
The Time for Completion may be adjusted only under Contract mechanisms such as Employer delay,
Variations, unforeseeable conditions, or other entitlement clauses.
Delay management, progress reporting, and mitigation obligations continue throughout execution.
""",
    "14.1": """14.1 The Contract Price
Unless otherwise stated, the Contract Price is the accepted lump sum amount subject to adjustments
expressly permitted by the Contract.
The Contractor bears taxes, duties, and fees allocated to the Contractor except where adjustment
for legal change or other explicit entitlement applies.
Interim payment valuation, deductions, and final accounting follow the payment clause sequence.
""",
    "14.2": """14.2 Advance Payment
If advance payment is agreed, the Employer shall pay the advance in the amount, currency,
and timing stated in the Contract Data or Particular Conditions, usually against an advance payment guarantee.
The advance is amortized through interim payments using the agreed deduction method.
Failure to provide or maintain required security may suspend or limit advance payment entitlement.
""",
    "14.7": """14.7 Payment
The Employer shall pay amounts certified within the payment period stated in the Contract,
subject to valid withholding rights and set-off expressly permitted.
Late payment may trigger financing charges where provided.
Payment administration must follow notice, certification, and documentary requirements,
including supporting records for measured work and adjustments.
""",
    "17.6": """17.6 Limitation of Liability
Except for excluded matters stated in the Contract, each Party's total liability to the other
arising out of or in connection with the Contract is limited to the agreed cap.
Liability limitations do not typically protect against fraud, deliberate default,
or categories expressly carved out in the Particular Conditions.
Consequential or indirect loss treatment follows the Contract wording and governing law.
""",
    "18.1": """18.1 Insurance Requirements
The Contractor shall procure and maintain insurances required by the Contract,
including minimum cover amounts, insured parties, policy periods, and evidence of placement.
Required insurances commonly include works/property damage, third-party liability,
and workers/employer liability. Failure to maintain insurance is a contractual non-compliance
that may permit remedial actions under the Contract.
""",
    "20.1": """20.1 Contractor's Claims
If the Contractor considers itself entitled to extension of time and/or additional payment,
it shall give notice describing the event or circumstance as soon as practicable and within
any contractual deadline (commonly 28 days from awareness or deemed awareness).
The Contractor shall then submit detailed particulars and maintain contemporary records.
Failure to comply with mandatory time-bar requirements may reduce or extinguish entitlement
subject to governing law and contract wording.
""",
    "20.2": """20.2 Claims by Employer
Where the Employer seeks payment, extension of Defects Notification Period, set-off,
or other remedy under the Contract, it shall issue notice and particulars in accordance
with contractual procedures. Any determination follows the agreed mechanism and supports
fair opportunity for response by the Contractor.
The clause operates together with dispute resolution provisions if disagreement persists.
""",
}

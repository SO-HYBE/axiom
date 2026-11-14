# Research motivation

## Question

Under which trace-mutation conditions can a runtime monitor still issue trustworthy verdicts about evidence-grounding properties in an AI research assistant, and when must it abstain?

AXIOM separates two questions that are often conflated: whether the research assistant's answer is supported by scientific evidence, and whether the assurance pipeline observed enough trustworthy events to certify its own process. The deterministic monitor addresses the second. The applicability engine compares documented experiment conditions to user-provided conditions, but a match is only within documented scope, never proof of physical transferability. Scientific claim validity still needs source-level review.

The terminology of unreliable channels and trustworthy verdicts is informed by Kauffman, Havelund and Fischmeister, “What Can We Monitor Over Unreliable Channels?”, *International Journal on Software Tools for Technology Transfer*, 23 (2021), 579–600, [doi:10.1007/s10009-021-00625-z](https://doi.org/10.1007/s10009-021-00625-z). The bibliographic record was checked against the [publisher record](https://link.springer.com/article/10.1007/s10009-021-00625-z) and an authors' publication listing. AXIOM is an independent, application-oriented prototype. It does not reproduce CritLab algorithms, tools, or theoretical results and claims no affiliation or endorsement.

The experimental design compares reference and mutated finite traces, reporting conclusive correctness, false-conclusive outcomes and abstention with explicit denominators. Integrity ON/OFF ablation exposes the cost in coverage when the monitor refuses to trust damaged observations. The central limitation is semantic: reliable event bookkeeping cannot prove that a real paper supports a generated scientific claim.

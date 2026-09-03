# Stage-aware feature admission

Use this gate for every new feature, feature expansion, revived removed behavior, roadmap proposal, and “next implementation” recommendation.

## Start with the product stage

Read the current objective, release stop conditions, accepted decisions, and live roadmap. State:

- the user or business outcome that matters now;
- the target segment and journey;
- the scarcest constraint (for example reliability, trust, supply density, traffic, data, operations, or engineering capacity);
- what work would be displaced if this candidate starts.

A release date is a constraint, not evidence of value. A roadmap item is an option, not a commitment. When an older idea container conflicts with a newer release umbrella or accepted decision, surface the conflict and follow source precedence.

## Require an admission brief

Do not recommend implementation until the available evidence answers these questions. Unknown answers lower confidence; they do not become optimistic assumptions.

1. **Outcome:** What user behavior, harm, or business result should change?
2. **Evidence:** Which observed users, incidents, funnel data, requests, or contractual duties show the problem exists, and how often?
3. **Why now:** Why is this important in the current stage rather than merely useful someday?
4. **Metric:** Which current metric or release condition should move, and what result would count as success?
5. **Alternatives:** Can removal, copy, support, concierge service, an admin operation, instrumentation, or a reversible experiment achieve enough of the outcome first?
6. **Dependencies:** Does the feature require marketplace density, interaction data, payment/legal decisions, operational ownership, or infrastructure that does not yet exist?
7. **Cost of delay vs. cost of build:** What happens if it waits, and which higher-value work would wait if it does not?
8. **Failure and exit:** How can it be disabled or removed, and when should the team stop investing?

## Choose exactly one disposition

### `BUILD NOW`

Use only when evidence shows at least one of these and implementation is the smallest adequate response:

- it removes a current release stop condition;
- it prevents material legal, security, privacy, financial, or data-integrity harm;
- it repairs a broken core journey needed by the current target users;
- it directly advances the current acquisition, activation, retention, revenue, or learning constraint with a measurable result;
- delaying it creates greater near-term harm or cost than the work it displaces.

The product rule must be decided, dependencies ready, and acceptance evidence possible.

### `FIX/REMOVE NOW`

Use when partial, misleading, unsafe, or unsupported behavior creates more risk than value. Removing unused complexity is a valid product outcome. Sunk engineering effort is not a reason to keep it.

### `VALIDATE CHEAPLY`

Use when the problem could be valuable but evidence or willingness to pay is weak. Prefer interviews with the target segment, a manual/concierge workflow, fake-door test, instrumented prototype, or bounded paid pilot. Define the hypothesis, metric, cohort, timebox, and stop condition before the test.

### `DEFER WITH TRIGGER`

Use when the outcome may matter later but the current stage, volume, density, data, or dependencies are insufficient. Record a measurable reopen trigger such as repeated requests from the target segment, manual workload exceeding an agreed envelope, recurring lost bookings, sufficient active supply in a local cluster, or enough interactions to beat a simple baseline. A calendar date alone is not a trigger.

### `REJECT`

Use when the proposal has no credible target outcome, depends on fantasy future behavior, duplicates a safer path, creates disproportionate complexity, conflicts with accepted direction, or exists mainly for visual completeness, competitor parity, or feature count.

## Manual operation is a product option

At low volume, a named founder/admin process can be better than self-service automation when it is safe, discoverable enough for affected users, reversible, auditable where needed, and has an acceptable response time. Record the owner and the trigger for automation.

Do not use a manual workaround to evade a legal/privacy duty, tolerate security or data-integrity risk, hide a broken high-frequency core journey, or create an unowned operational promise. Escalate unresolved legal or policy semantics rather than assuming that self-service is required or that manual handling is sufficient.

## Dependency-sensitive examples

- Waitlists need observed capacity-constrained demand and meaningful cancellation-fill opportunity; being theoretically useful for a full lesson is not enough.
- Recommendation engines need enough active inventory and interaction data plus a measurable simple baseline; an empty dashboard is not evidence for personalization.
- Communities, content marketplaces, and paid distribution need existing participants, traffic, or repeated demand; building the venue does not create the audience.
- Account lifecycle automation can wait during very low volume only when a safe manual path can fulfill accepted user and legal obligations; volume, missed response targets, complex reservation/payment dependencies, or unacceptable risk should reopen it.

Always apply the exact current decisions in `memory/DECISIONS.md`; these examples explain the reasoning pattern and do not override later accepted behavior.

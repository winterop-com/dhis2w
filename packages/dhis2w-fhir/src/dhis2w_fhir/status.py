"""The IG life-cycle status and the publication flags every generated artifact derives from it.

`[ig] status` is the single dial: it is the `status` of `sushi-config.yaml`, the
publication `status` of every generated definitional artifact, and - through
`experimental_for_status` - their `experimental` flag. This module is a leaf so
every emitter can import it without reaching for `dhis2w_fhir.config`.
"""

from __future__ import annotations

from typing import Literal

#: Where the IG is in its life cycle: `draft` while it is being built, `active` in production.
IgStatus = Literal["draft", "active"]

#: What the project is: a `guide` of forms, or a `package` published for guides to depend on.
#:
#: The two are asked apart wherever the answer is "does this project publish forms at all", which
#: is every form-side generate target and most of the scaffold. What a package holds is a separate
#: question, answered by `PackageContent`, so a second kind of package is a new content value
#: rather than a new project kind.
ProjectKind = Literal["guide", "package"]

#: What a package publishes. One value today; a huge shared CodeSystem would be the next.
#:
#: This is the discriminator every package-specific binding hangs off - which resources the guide
#: reads out of the package, which directory a checkout keeps them in, and which generate targets
#: the package itself runs.
PackageContent = Literal["organisation-units"]

#: The package content a guide depends on through `[generate.organisation_units.registry]`.
ORGANISATION_UNIT_PACKAGE: PackageContent = "organisation-units"


def experimental_for_status(status: IgStatus) -> bool:
    """Whether artifacts generated under `status` are experimental - a draft IG's are, an active IG's are not."""
    return status == "draft"

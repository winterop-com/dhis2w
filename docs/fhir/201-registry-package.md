# Publish the organisation units as a registry package

A guide publishes its organisation-unit registry inline by default: every unit in
the selection becomes an `Organization` and a `Location` under
`ig/input/resources/registry/`, and the guide's forms reference them as
`Location/<id>`. That is the right shape for a district guide and for most
national ones. This page is for the guide where it is not: the hierarchy has
grown large enough to dominate the build, or it changes on a different cadence
from the forms, and you want it published as a package of its own that the
guide depends on.

Nothing here is on by default. A `fhir.toml` without a
`[generate.organisation_units.registry]` table behaves exactly as before.

## When to split

Measured on a national instance, publishing four of its five hierarchy levels:

| | Inline registry |
| --- | --- |
| Organisation units published | 2,349 |
| Registry instances | 4,698 of the guide's 5,739 resources (82 percent) |
| Pre-built JSON | 30 MB |
| Rendered output | 55,743 files, 1.4 GB |
| Publisher heap used | 7.66 GB |

The registry is most of the guide by every measure except the one that matters
to a reader, who came for the forms. It also changes monthly, while the forms
change yearly, so every facility rename rebuilds and republishes the forms.

Split it when:

- the artifacts page and the output tree are mostly registry;
- the build no longer fits the heap you can give one container, and the levels
  you want to publish are deeper than the ones you can afford to build beside
  the forms;
- the units and the forms need separate version numbers.

Keep it inline when the guide is small, or when the people consuming the
registry are the people consuming the forms and one package is simpler for
them.

## The two projects

The registry becomes a project of its own, scaffolded with `--kind registry`.
It publishes the organisation-unit registry and nothing else: the
`D2Organization` and `D2Location` profiles, the level extension and its
CodeSystem and ValueSet, the organisation-unit NamingSystems, the attribute-value
extension a unit's DHIS2 attributes ride on, the registry examples, and the
Registry page with a per-unit intro where DHIS2 holds a description. Its site is
Home, Registry, Artifacts.

```bash
d2w fhir init example-registry --kind registry \
    --id dhis2.fhir.example.registry \
    --canonical http://example.org/fhir/registry \
    --profile myserver
cd example-registry
d2w fhir generate
make build
```

`d2w fhir generate` in a registry package runs three targets - the foundation
slice its instances name, the organisation units, and the pages - and the
form-side targets refuse:

```
error: dhis2.fhir.example.registry is a registry package ([ig] kind = "registry" in
fhir.toml), which publishes the organisation-unit registry and nothing else, so
`d2w fhir generate questionnaires` has nothing to write here.
```

The guide then names the package. Either scaffold it with the registry flags or
add the table to an existing guide's `fhir.toml` and refresh:

```toml
[generate.organisation_units]
max_level = 4

[generate.organisation_units.registry]
id = "dhis2.fhir.example.registry"
canonical = "http://example.org/fhir/registry"
version = "0.1.0"
# A local checkout of the registry project, whose build `make build` installs.
path = "../example-registry"
```

```bash
d2w fhir init --refresh .
d2w fhir generate
make build
```

The refresh lands the `dependencies:` block in `ig/sushi-config.yaml` and the
three `REGISTRY_*` knobs in the Makefile. The guide's selection under
`[generate.organisation_units]` stays: it is the set of units the guide's
forms may refer to, and it should match the registry's.

## What changes in the guide

With the table present, `d2w fhir generate`:

- writes no `Organization`, no `Location`, no registry profile, no registry
  example and no level terminology; `ig/input/fsh/organization/` and
  `ig/input/resources/registry/` are emptied, which also clears what an earlier
  inline run left there;
- reads the selection once, as `id,code,name`, instead of walking the hierarchy
  with its geometry - the same identity stems as the registry resolves, so
  every reference lands on a unit the package holds;
- references every unit by its absolute URL,
  `http://example.org/fhir/registry/Location/<id>`, in the examples, the
  assignment Lists and the capture page. A relative `Location/<id>` does not
  resolve across a package dependency in the IG publisher, an absolute one does;
- types `D2OrganisationUnit` and every `D2Responses` subject with the registry's
  profile by canonical URL,
  `http://example.org/fhir/registry/StructureDefinition/d2-location`;
- leaves the level extension and the organisation-unit NamingSystems to the
  package, and keeps everything else of the foundation as before;
- raises one `registry-dependency` note naming the package, its version and the
  number of units it resolved.

The Registry page of the guide states the package instead of tabulating the
hierarchy.

## Building with the dependency

SUSHI and the IG publisher resolve a dependency from their package cache, the
docker volume `fhir-ig-cache` every scaffolded project shares. `make build` in
the guide runs `make registry-install` first, which streams the registry's
`package.tgz` into the cache under `<id>#<version>/package/`, then the
publisher. `REGISTRY_TGZ` defaults to `<registry.path>/ig/output/package.tgz`
when `path` is set and can be named on the command line:

```bash
make build REGISTRY_TGZ=/downloads/dhis2.fhir.example.registry-0.1.0.tgz
```

The two builds never share a container. Each project has its own Makefile and
its own `JAVA_HEAP`, so the registry's depth is a dial on the registry project
rather than on the guide - which is what lets the registry reach a level the
forms never had room for beside them.

Measured on the same national instance, the same selection built three ways:

| | Inline guide | Registry package | Depending guide |
| --- | ---: | ---: | ---: |
| Published resources | 5,739 | 4,708 | 1,032 |
| Peak heap | 7.66 GB | 4.13 GB | 6.99 GB |
| Output | 1.4 GB, 55,743 files | 607 MB, 43,555 | 903 MB, 13,339 |

Read the heap column honestly. The depending guide's peak drops by two thirds
of a gigabyte, not by the registry's whole share, because the publisher loads
the dependency package alongside the guide. What the split moves out of the
guide's build is the registry's validation and rendering - 43,555 of the 56,894
output files - into a container the guide's build never pays for, and into a
project that can be rebuilt, versioned and republished on its own cadence.

Publishing the registry package to a package server, so a guide resolves it
without a local build, is not part of this toolkit yet; the tarball is the
hand-off.

## What the publisher needs, verified

Two throwaway projects built with the same `fhir-ig` image settled the shape:

- a `Location/<id>` reference from the guide into the registry package is an
  error, `Unable to resolve resource`; the absolute
  `<registry canonical>/Location/<id>` resolves;
- the `dependencies:` entry's `uri` is the registry's ImplementationGuide
  canonical, `<canonical>/ImplementationGuide/<id>`, not the package canonical;
- the registry's Locations and Organizations land in the package's
  `package/` directory as they are, from `input/resources/registry/*`, with no
  per-resource `exampleBoolean` entries in `sushi-config.yaml`.

## What stays with the inline registry for now

`d2w fhir serve` and `d2w fhir check-artifacts` read the guide's own
`ig/input/resources/registry/`. A guide depending on a package therefore serves
no `Location` yet and its artifact check does not compare the two selections;
serve the registry project, or the inline guide, until the facade reads a
registry package.

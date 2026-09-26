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

Scaffold both at once, which is the shortest correct route:

```bash
d2w fhir init example --with-registry \
    --id dhis2.fhir.example \
    --canonical http://example.org/fhir \
    --profile myserver
```

That writes `example/registry/` and `example/guide/`, wired to each other, plus
a Makefile that drives them in the order that resolves and a README describing
the pair. Both identities derive from the one `--id` and `--canonical`, so the
four values the two projects share cannot disagree - which is the failure the
rest of this section describes how to avoid by hand. `d2w fhir init --refresh`
on that directory refreshes both projects, rewrites the Makefile from the
current scaffold, and writes the README only when the current render reproduces
every line already in it, so what you add to it stays. `make update` in that
directory moves both projects to the current release and then does that refresh.
`make refresh` there wipes both projects' build output, rebuilds the shared docker
image once, regenerates both, validates both without stopping on their findings,
and builds the registry and then the guide; the caches stay, as they do in each
project's own `make refresh`.

The two halves, spelled out. The registry becomes a project of its own,
scaffolded with `--publishes organisation-units`.
It carries `kind = "package"` and `publishes = "organisation-units"` under `[ig]`,
and holds the organisation-unit registry and nothing else: the
`D2Organization` and `D2Location` profiles, the level extension and its
CodeSystem and ValueSet, the organisation-unit NamingSystems, the attribute-value
extension a unit's DHIS2 attributes ride on, the registry examples, and the
Registry page with a per-unit intro where DHIS2 holds a description. Its site is
Home, Registry, Artifacts.

The registry examples are the one published pair that is not an organisation
unit. Both profiles require the two DHIS2 identifier slices, so the worked
`D2Organization` / `D2Location` pair has to state a UID and a code; it states
`d2-example` on each, under the name "Example organisation unit". No DHIS2 UID
can be that value, so an identifier search over the package answers with exactly
one resource per unit - which is the whole job of a package whose only task is
to say what each unit is. Its level and position are taken from the selection's
own root unit, so the publisher still validates the profiles against shapes the
instance really holds.

```bash
d2w fhir init example-registry --publishes organisation-units \
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
error: dhis2.fhir.example.registry is a package ([ig] publishes = "organisation-units"
in fhir.toml), which publishes the organisation-unit registry and nothing else, so
`d2w fhir generate questionnaires` has nothing to write here.
```

`d2w fhir serve` in a registry package serves the places it publishes and no
capture surface at all. The banner says which project it is - `as a FHIR
endpoint publishing organisation units and no forms` - the CapabilityStatement
declares no `QuestionnaireResponse` and no `$generate`, and the base URL and a
posted submission both answer with the same sentence:

```
This project is a package: it publishes organisation units for guides to depend
on, and no form. Captures are made in a guide that depends on it, not here.
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

An archive that is not there is caught before any of that. `make registry-present`
is two `test` calls, it runs ahead of the volume the cache lives in, and it
refuses naming the registry's own `make build`:

```console
$ make sushi
../registry/ig/output/package.tgz: no such file - build the registry first: make -C ../registry build
  Only a compile needs it. 'd2w fhir serve --live' and 'd2w fhir forward' read the two projects as they stand, so neither needs a build of either one.
```

Which is the way out worth knowing here: serving live and forwarding read the
projects as they stand, so neither pair-half has to be compiled at all to fill a
form in and send it to DHIS2.

The root Makefile runs its own targets one at a time, so `make -j2 build` and a
`-j` reaching it through `MAKEFLAGS` build the registry to completion before the
guide starts - a guide started beside the registry finds no `package.tgz`, or
installs the one the last build left. Each `make -C` it runs is a make of its
own and parallelises its own recipes as usual. The cost is `make generate`: its
two reads of the instance are independent, but a `-j` on the root Makefile buys
nothing, so the two take their two turns. Run `make generate-registry` and `make
generate-guide` in two shells when that matters.

The two builds never share a container. Each project has its own Makefile and
its own publisher run, so the registry's depth is a dial on the registry project
rather than on the guide - which is what lets the registry reach a level the
forms never had room for beside them. Each sizes its heap from the memory the
same docker reports, and `JAVA_HEAP` on the root Makefile reaches both at once
whenever you want a particular ceiling - make carries a command-line or
environment variable into both sub-makes itself.

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

## Generating, serving, forwarding and checking a depending guide

The guide publishes no `Location` of its own, so the four commands that need
the registry find it in the package instead. All four read the same two sources
in the same order: the checkout `path` names, then a package given on the
command line.

```bash
# The everyday case - the checkout beside the guide answers, no build needed.
d2w fhir serve

# The hand-off case - no checkout, so name the archive the registry build wrote.
d2w fhir generate --registry-package ../dist/package.tgz
d2w fhir serve --registry-package ../dist/package.tgz
d2w fhir check-artifacts --registry-package ../dist/package.tgz
d2w fhir forward --registry-package ../dist/package.tgz
```

A guide scaffolded without `path` does this through its Makefile: once
`REGISTRY_TGZ` names an archive that is on disk, `make generate`, `make build`
(whose artifact scan runs first), `make serve` and `make forward` pass it as
`--registry-package`, so `make build REGISTRY_TGZ=../dist/package.tgz` needs
nothing else.

A `package.tgz` is read where it lies; nothing is unpacked onto your disk. An
already-extracted package directory works too. Only the resources at the
package's top level are read: the worked `d2-example` pair under
`package/example/` names no organisation unit, so a guide serves the same units
from the archive as from the checkout.

Reaching neither source is refused rather than worked around, and for `serve`
the refusal lands while settings resolve, so you get one line instead of a
starting banner followed by an empty hierarchy:

```
error: dhis2.fhir.example depends on the organisation-unit registry package
dhis2.fhir.example.registry 0.1.0, and neither source for it is readable. Either
set `path` in [generate.organisation_units.registry] to a checkout of the
registry project, or name the package the registry's `make build` wrote with
`--registry-package <package.tgz>`.
```

`--live` reads the registry the same way. A live run over a depending guide
serves the package's `Location` and `Organization` resources and walks no
hierarchy on the instance: publishing units of its own would put a second
identity for every place at this guide's base URL, which is an address the
published guide resolves nothing at. Reaching neither source refuses a live run
with the line above, before the banner, exactly as it refuses a compiled one.

`d2w fhir forward` has the same two halves and reads the registry in both. A
project that has run SUSHI has its guide read off disk; a project captured
through `d2w fhir serve --live` has never run it, so the drain builds the guide
off the instance instead - and either way the places a receipt's
`Location/<id>` resolves against come out of the registry package. The live
half walks no hierarchy, and a drain that can reach neither source prints the
line above and stops before it opens a connection, rather than translating
against places this guide does not publish.

The absolute references the guide carries are read as the units they name
wherever the facade needs one. An assignment `List` naming
`<registry canonical>/Location/<id>` narrows the capture UI's **Reporting
from** control to that unit, `Questionnaire/{id}/$generate` draws its draft
inside it, and a submission is graded against it on receipt - the same reading
a guide publishing its own registry gets from `Location/<id>`. A submission
names its own unit in the same spelling: the example responses the generator
writes for a depending guide name their subject, their `D2OrganisationUnit`
extension and their organisation-unit answers absolutely, which is the body the
guide's capture page documents, and `d2w fhir serve` accepts it and names the
unit it resolves on the receipt.

Which authority published the unit is checked. A reference is admitted under a
canonical this project publishes organisation units at - the guide's own, or
the registry package's - and a reference under any other authority is refused
saying which one it named and which one was expected, because the same DHIS2
uid under somebody else's registry is a different organisation unit.

`d2w fhir check-artifacts` additionally compares the unit references already on
disk against what the registry publishes, and reports each one the package does
not carry as a `registry` finding. That is the check for two projects whose
selections have drifted apart - it stays offline, reads no instance, and runs
inside `make build`, so a dangling reference is named in seconds instead of by
the publisher after it has rendered everything else.

`d2w fhir generate` counts the same gap as it writes the references, against the
`Location-<id>.json` files the checkout named by
`[generate.organisation_units.registry] path` published. It reads those files
rather than the two `[generate.naming] source` literals, because the literals are
not the fact: `code-or-id` falls back to the id for every unit whose code cannot
serve as a stem, so a registry stating it beside a guide stating `id` can publish
exactly the stems the guide references and nothing dangles - and a registry that
code-stems some units and falls back on others produces a partial mismatch two
literals have no shape for. The note states how many of how many references
dangle, names the first few, and says nothing at all when none does.

### Why the refusal matters more than it looks

A missing registry is not a quiet degradation, and the reason is worth stating.
A `Location/<id>` reference resolves to a DHIS2 organisation unit through the
published `Location`. With none loaded, resolution falls back to reading the id
as the UID itself. Under the default `naming.source = "id"` the identity stem
*is* the UID, so capture and forward would keep working by accident. Under
`naming.source = "code"` the stem is the unit's DHIS2 code, and the same
fall-back would resolve confidently to the wrong organisation unit. Refusing up
front is what keeps those two projects behaving the same way.

## What the guide reads out of the package

The instances, and only those: `Location` and `Organization`. The package also
ships its profiles, its level terminology and its own ImplementationGuide, and
the guide resolves those by canonical against the published registry rather
than serving copies. Loading them would put a second ImplementationGuide inside
a facade that answers for one guide.

Publishing the registry package to a package server, so a guide resolves it
without a local build or a handed-over archive, is still not part of this
toolkit; the tarball is the hand-off.

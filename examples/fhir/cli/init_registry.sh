#!/usr/bin/env bash
# d2w fhir init --kind registry / --registry-* — split the organisation-unit registry into a package.
set -euo pipefail

# Opt-in, and two projects. The registry package publishes the organisation-unit registry and
# nothing else: `d2w fhir generate` in it runs the foundation slice its instances name, the
# organisation units, and the pages, and refuses the form-side targets by name.
d2w fhir init demo-registry --kind registry \
    --id dhis2.fhir.registrydemo.registry \
    --canonical http://example.org/fhir/registry-demo/registry \
    --publisher "Demo Org" \
    --max-level 4

# `kind = "registry"` under [ig] is what says so; the site is Home, Registry, Artifacts.
grep -n 'kind = "registry"' demo-registry/fhir.toml
grep -A3 '^menu:' demo-registry/ig/sushi-config.yaml

# The guide names the package. It then writes no Organization or Location of its own,
# references every unit by its absolute URL under the package's canonical, and declares the
# package under `dependencies:` - which `make build` installs from the registry's own build
# (`REGISTRY_TGZ`, defaulting to <registry-path>/ig/output/package.tgz) before the publisher
# runs. The two builds never share a container, so each gets its own heap.
d2w fhir init demo-guide \
    --id dhis2.fhir.registrydemo \
    --canonical http://example.org/fhir/registry-demo \
    --publisher "Demo Org" \
    --data-set BfMAe6Itzgt \
    --max-level 4 \
    --registry-id dhis2.fhir.registrydemo.registry \
    --registry-canonical http://example.org/fhir/registry-demo/registry \
    --registry-path ../demo-registry

grep -A4 'organisation_units.registry' demo-guide/fhir.toml
grep -A3 '^dependencies:' demo-guide/ig/sushi-config.yaml
grep '^REGISTRY_' demo-guide/Makefile

# A guide without the table is untouched by any of this: no dependency, no knobs, the registry
# inline under ig/input/resources/registry/ as before.
d2w fhir init demo-inline --id dhis2.fhir.inlinedemo --canonical http://example.org/fhir/inline-demo
! grep -q '^dependencies:' demo-inline/ig/sushi-config.yaml
! grep -q '^REGISTRY_' demo-inline/Makefile

rm -rf demo-registry demo-guide demo-inline

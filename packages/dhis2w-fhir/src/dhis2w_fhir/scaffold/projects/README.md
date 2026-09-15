# The bundled template payloads

Three project templates ride the wheel: `aggregate-minimal`, `event-program`
and `patient-summary`. Each is a directory holding two things -
`selection.toml`, the `[generate]` and `[ips]` tables `d2w fhir init --template`
appends to the scaffolded `fhir.toml`, and `ig/input/`, the tree
`d2w fhir generate` wrote from exactly that selection. `manifest.toml` beside
them names all three and is the only file that does.

The payload is a build artifact that happens to be committed, which is the one
thing to keep in mind here: it is what the generator produced on the day it ran,
and the generator moves. Regenerate all three whenever a generator change alters
what a guide publishes, and in the same pull request as that change.

## The instance they are cut from

The DHIS2 demo database - the Sierra Leone dataset every `play.im.dhis2.org`
server and the seeded local stack both carry. Every UID the three
`selection.toml` files name exists there:

| Kind | UID | What it is |
| --- | --- | --- |
| Data set | `TuL8IOPzpHh` | EPI Stock, twelve data elements on the default category combination |
| Event program | `VBqh0ynB2wv` | Malaria case registration - one stage, three questions (`aggregate-minimal`, `patient-summary`) |
| Event program | `lxAQ7Zs9VYR` | Antenatal care visit - the story of `event-program` |
| Tracker program | `IpHINAT79UW` | Child Programme - a registration form and two stage forms |
| Option set | `hiQ3QFheQ3O` | Sex |
| Category | `GLevLNI9wkl` | The DHIS2 built-in `default` category |
| Categories | `yY2bQYqNt0o`, `Qzh0MSUx4RM` | The two axes `event-program` disaggregates by |
| District | `PMa2VCrupOd` / `bL4ooGhyHRQ` / `qhqAxPSTUXp` | Kambia, Pujehun, Koinadugu - one per template, to level 4 |

## Regenerating one

From a checkout, against any DHIS2 demo instance a profile names - `play43`
below:

```bash
# 1. Scaffold a project with the template's own identity, in a scratch directory.
uv run d2w fhir init /tmp/aggregate-minimal \
  --id dhis2.fhir.examples.aggregate-minimal \
  --canonical http://example.org/fhir/examples/aggregate-minimal \
  --name ExamplesAggregateMinimal \
  --title "Minimal aggregate example guide" \
  --publisher "dhis2w examples" \
  --profile play43

# 2. Give it the template's selection, which is the file beside this one.
cat packages/dhis2w-fhir/src/dhis2w_fhir/scaffold/projects/aggregate-minimal/selection.toml \
  >> /tmp/aggregate-minimal/fhir.toml

# 3. Generate.
cd /tmp/aggregate-minimal && uv run --project /path/to/dhis2w d2w fhir generate
```

The identity comes off `manifest.toml`: `ig_id`, `canonical`, `name` and `title`
of the template's table. It has to, because the payload states that canonical in
full several hundred times and scaffolding rewrites those to the project's own -
a payload generated under a different address would be rewritten from a stem it
does not carry.

Then replace the payload with what step 3 wrote, minus the three files the
scaffold itself writes under `ig/input/` - `fsh/aliases.fsh`,
`pagecontent/index.md` and `ignoreWarnings.txt`. A template payload never lands
on one of those, so they stay out of it:

```bash
rm -rf packages/dhis2w-fhir/src/dhis2w_fhir/scaffold/projects/aggregate-minimal/ig/input
rsync -a --exclude 'fsh/aliases.fsh' --exclude 'pagecontent/index.md' \
  --exclude 'ignoreWarnings.txt' \
  /tmp/aggregate-minimal/ig/input/ \
  packages/dhis2w-fhir/src/dhis2w_fhir/scaffold/projects/aggregate-minimal/ig/input/
```

`packages/dhis2w-fhir/tests/test_fhir_template_payloads.py` is what catches a
payload nobody regenerated: it builds one Location from a fixture organisation
unit with today's emitter and asserts the bundled files carry the same shape.
It runs offline, so CI answers the question a regeneration run needs an instance
to ask.

Naming other UIDs is a selection change like any other: edit the template's
`selection.toml`, regenerate from it, and update the table above.

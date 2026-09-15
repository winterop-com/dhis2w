import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

/**
 * What a form says it will not accept, and what its DHIS2 instance will not accept after that.
 *
 * THREE PLACES A VALUE IS GRADED, and this walks all three on the real server. The form publishes
 * the range each of its questions admits, so a value outside one is caught under the cursor and
 * Submit refuses with the fact stated. The form publishes the conditions each of its questions is
 * asked under, so a question the answers close is not rendered and carries no answer. And the form
 * publishes the DHIS2 program rules its instance evaluates on import, which nothing here can check -
 * so it names them where it describes itself, and reads a rejection citing one back as its name.
 *
 * WHERE THE FACTS COME FROM. The fixture project publishes each on the form that would really carry
 * it (packages/dhis2w-fhir-serve/tests/fixture_project.py): the temporal event form carries a range
 * of calendar days and a condition, its coverage question already carried a numeric range, and the
 * antenatal visit stage lists the three program rules its instance holds - two that only warn, and
 * one that computes a question's value itself.
 */

const TEMPORAL_FORM = 'PrTemporal1'
const STAGE_FORM = 'PsAncVisit1'
const FHIR_JSON = 'application/fhir+json'

/** The bounded date question of the temporal form, by the DHIS2 uid its control is keyed on. */
const VISIT_DATE_QUESTION = 'DeVisitDate1'

/** The bounds the temporal form publishes, and the coverage above which it asks for a link. */
const COVERAGE_MAXIMUM = '100'
const OUTBREAK_LAST_DAY = '2026-12-31'
const COVERAGE_LINK_THRESHOLD = 50

/** The three rules the antenatal visit stage lists, as the fixture's instance names them. */
const HAEMOGLOBIN_RULE = 'The haemoglobin value cannot be above 99'
const VISIT_ORDER_RULE = 'A visit is filed in the order it happened'
const ASSIGNED_PRESSURE_RULE = 'The systolic blood pressure is worked out from the visit number'
const HAEMOGLOBIN_RULE_CONDITION = '#{DeAncVisNo1} > 99'

/** How many of them the panel counts - every rule the instance holds for the form, whatever it does. */
const STAGE_RULE_COUNT = 3

/** The question the ASSIGN rule works out, by the DHIS2 uid its control is keyed on and by its words. */
const ASSIGNED_QUESTION = 'DeAncBpSys1'
const ASSIGNED_QUESTION_TEXT = 'ANC systolic blood pressure'

/** How many of the stage's three questions anybody fills in - the third is the one DHIS2 works out. */
const STAGE_ANSWERABLE_QUESTIONS = 2

/** Open one form and wait for the skeleton, which is what puts the drafted values in the controls. */
async function openForm(page: Page, questionnaireId: string): Promise<void> {
    const opened = page.waitForResponse((response) => response.url().includes('$generate'))
    await page.goto(`/#/forms/${questionnaireId}`)
    await opened
}

test('a value above what the form accepts refuses Submit, and says which value that is', async ({ page }) => {
    await openForm(page, TEMPORAL_FORM)

    await page.getByLabel('Coverage').fill('137')

    // The fact and nothing else: what was typed, which end of the range it passed, and the value the
    // form accepts. Nobody is told what to type instead.
    await expect(page.getByText(`137 is above ${COVERAGE_MAXIMUM}, the highest value this form accepts`)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Submit' })).toBeDisabled()
    await expect(page.getByText('1 answer is outside what this form accepts')).toBeVisible()
})

test('a value back inside the range lets Submit go again', async ({ page }) => {
    await openForm(page, TEMPORAL_FORM)

    await page.getByLabel('Coverage').fill('137')
    await expect(page.getByRole('button', { name: 'Submit' })).toBeDisabled()

    await page.getByLabel('Coverage').fill('58.3')

    await expect(page.getByText('the highest value this form accepts')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Submit' })).toBeEnabled()
})

test('a calendar day outside the range the form publishes refuses Submit too', async ({ page }) => {
    await openForm(page, TEMPORAL_FORM)

    // By uid rather than by label: this programme states no word for its event date, so the capture
    // context's own control falls back to "Visit date" and the question happens to be called that
    // too. The uid is what every control here is keyed on and the one name that means one thing.
    await page.locator(`#${VISIT_DATE_QUESTION}`).fill('2027-03-04')

    await expect(
        page.getByText(`2027-03-04 is above ${OUTBREAK_LAST_DAY}, the highest value this form accepts`),
    ).toBeVisible()
    await expect(page.getByRole('button', { name: 'Submit' })).toBeDisabled()
})

test('a question its conditions close is not asked, and its answer goes with it', async ({ page }) => {
    await openForm(page, TEMPORAL_FORM)

    // Above the threshold the form asks for the link, and it takes an answer.
    await page.getByLabel('Coverage').fill(String(COVERAGE_LINK_THRESHOLD + 10))
    const link = page.getByLabel('Visit link')
    await expect(link).toBeVisible()
    await link.fill('https://example.org/visit/1')

    // Below it the form stops asking - and the answer typed a moment ago is gone rather than held
    // out of sight, because a value under a question nobody is being asked describes nothing.
    await page.getByLabel('Coverage').fill(String(COVERAGE_LINK_THRESHOLD - 10))
    await expect(page.getByLabel('Visit link')).toHaveCount(0)

    await page.getByLabel('Coverage').fill(String(COVERAGE_LINK_THRESHOLD + 10))
    await expect(page.getByLabel('Visit link')).toHaveValue('')
})

test('a form names the DHIS2 program rules its instance enforces after the submission leaves', async ({ page }) => {
    await openForm(page, STAGE_FORM)

    const statement = page.getByText(
        `This DHIS2 instance enforces ${STAGE_RULE_COUNT} further rules on import, beyond the ones this form checks`,
    )
    await expect(statement).toBeVisible()

    // Folded away by default: the names are what a person reads, and the DHIS2 expression behind
    // each is the exact statement of what it does rather than the first thing anyone needs.
    await expect(page.getByText(HAEMOGLOBIN_RULE)).toBeHidden()
    await statement.click()

    await expect(page.getByText(HAEMOGLOBIN_RULE)).toBeVisible()
    await expect(page.getByText(VISIT_ORDER_RULE)).toBeVisible()
    await expect(page.getByText(HAEMOGLOBIN_RULE_CONDITION)).toBeVisible()

    // The ASSIGN rule is listed with the two that only warn. It is the one of the three that
    // rewrites what a submission carries - DHIS2 computes the value and answers E1307 to a document
    // disagreeing with it - so leaving it out would hide the rule with the most to say about what
    // happens after the submission leaves.
    // Exactly, because the rule's name is also inside the sentence the control it computes states
    // further down the page - two places saying one thing, which is the point of naming the rule.
    await expect(page.getByText(ASSIGNED_PRESSURE_RULE, { exact: true })).toBeVisible()

    // What each rule does is on its own row, and the ASSIGN rule names the question it works out -
    // which is the control that takes no answer further down the same page.
    await expect(page.getByText('Works out an answer')).toBeVisible()
    await expect(page.getByText('Warns', { exact: true })).toBeVisible()
    await expect(page.getByText('Refuses the submission', { exact: true })).toBeVisible()
    await expect(
        page.getByText(`It works out the answer to ${ASSIGNED_QUESTION_TEXT}, so this form leaves it empty.`),
    ).toBeVisible()
})

test('a question this DHIS2 instance works out itself takes no answer and is not counted as one', async ({ page }) => {
    await openForm(page, STAGE_FORM)

    // Read-only, and saying why in the same sentence the receipt carries: the rule is named because
    // somebody who wants the value changed has to find it in Maintenance.
    const computed = page.locator(`#${ASSIGNED_QUESTION}`)
    await expect(computed).toBeDisabled()
    await expect(
        page.getByText(
            `This DHIS2 instance works this answer out on import, under the program rule ` +
                `${ASSIGNED_PRESSURE_RULE}. It is sent empty: DHIS2 refuses the whole submission when the ` +
                `answer is neither empty nor the value it calculated, with E1307.`,
        ),
    ).toBeVisible()

    // Two of the three questions, not three: a control nobody can type into is not work left to do,
    // so it leaves the denominator as well as the numerator.
    await expect(page.getByText(`0 of ${String(STAGE_ANSWERABLE_QUESTIONS)} questions answered`)).toBeVisible()

    // And a fill draws for the two it asks, leaving the computed one empty - the only value DHIS2
    // accepts whatever the rule works out.
    const filled = page.waitForResponse((response) => response.url().includes('$generate'))
    await page.getByRole('button', { name: 'Fill with test data' }).click()
    await filled
    await expect(computed).toHaveValue('')
    const asked = String(STAGE_ANSWERABLE_QUESTIONS)
    await expect(page.getByText(`${asked} of ${asked} questions answered`)).toBeVisible()
})

test('a form its instance holds no rules for says nothing about rules', async ({ page }) => {
    await openForm(page, TEMPORAL_FORM)

    await expect(page.getByText('when the submission is imported')).toHaveCount(0)
})

test('$generate answers inside the bounds and asks nothing its own answers closed', async ({ request }) => {
    const drawn = await Promise.all([1, 2, 3, 6, 11].map((seed) => generated(request, TEMPORAL_FORM, seed)))

    for (const response of drawn) {
        const answered = new Map(
            (response.item ?? [])
                .filter((item) => item.answer !== undefined)
                .map((item) => [item.linkId, item.answer ?? []]),
        )
        const coverage = answered.get('DeCoverage01')?.[0].valueDecimal ?? 0
        const visitDate = answered.get('DeVisitDate1')?.[0].valueDate ?? ''

        expect(coverage).toBeGreaterThanOrEqual(0)
        expect(coverage).toBeLessThanOrEqual(Number(COVERAGE_MAXIMUM))
        expect(visitDate <= OUTBREAK_LAST_DAY).toBe(true)
        // The draw is filtered against the very conditions the capture screen evaluates, so a
        // generated response never answers a question its own answers hid.
        expect(answered.has('DeVisitLink1')).toBe(coverage >= COVERAGE_LINK_THRESHOLD)
    }
})

/** One answered item of a generated response, as far as this spec reads one. */
interface GeneratedItem {
    linkId: string
    answer?: { valueDecimal?: number; valueDate?: string }[]
}

/** The response `$generate` draws for one form and one seed. */
async function generated(
    request: APIRequestContext,
    questionnaireId: string,
    seed: number,
): Promise<{ item?: GeneratedItem[] }> {
    const response = await request.get(`/Questionnaire/${questionnaireId}/$generate?seed=${String(seed)}`, {
        headers: { Accept: FHIR_JSON },
    })
    expect(response.status(), await response.text()).toBe(200)
    return (await response.json()) as { item?: GeneratedItem[] }
}

import { describe, expect, it } from 'vitest'

import { reportingScopeSentence } from '@/components/ReportingUnitPicker'

/**
 * How wide the reporting choice is, said the same way on both of the two forms a project has.
 *
 * The two branches state one fact - how many organisation units this form may be reported from - and
 * a reader meeting them on two forms in one session reads them as one sentence with a number in it.
 * So both count through the same helper, and a count of one is singular on both sides.
 */
describe('the reporting scope sentence', () => {
    it('agrees with a count of one on an assigned form', () => {
        expect(reportingScopeSentence(1, true)).toBe(
            '1 organisation unit is assigned to this form. A capture outside the form\'s assigned ' +
                'organisation units is refused when it reaches this DHIS2 instance.',
        )
    })

    it('agrees with a count of one on a form assigned everywhere', () => {
        expect(reportingScopeSentence(1, false)).toBe(
            'This form is assigned everywhere, so any of the 1 published organisation unit may report it.',
        )
    })

    it('agrees with a count of many on both', () => {
        expect(reportingScopeSentence(14, true)).toContain('14 organisation units are assigned to this form.')
        expect(reportingScopeSentence(14, false)).toContain('any of the 14 published organisation units')
    })
})

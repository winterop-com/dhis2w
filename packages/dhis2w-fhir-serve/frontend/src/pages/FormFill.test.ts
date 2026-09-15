import { describe, expect, it } from 'vitest'

import { UNCAPTURABLE_FORM_STATUS, uncapturableReason } from '@/pages/FormFill'

/**
 * What a form nothing capturable can be made for says on screen.
 *
 * `$generate` answers 422 with the whole reason in its `diagnostics` - every attribute option combo
 * restricted away from every organisation unit the form admits, or closed for the period it reports
 * for. The page renders that sentence in place of the "no submission context yet" block, so what a
 * reader gets is the fact rather than a wait that never ends.
 */
describe('the reason a form takes no capture', () => {
    it('drops the part that only repeats which form is on screen', () => {
        const message =
            '`Questionnaire/lyLU2wR22tC` cannot be generated against: none of the 64 attribute option ' +
            'combo(s) of `http://example.org/fhir/m3/ValueSet/d2-aoc-O4VaNks6tta-vs` may be captured at ' +
            'any of the 1 organisation unit(s) this form admits'

        expect(uncapturableReason(message, 'lyLU2wR22tC')).toBe(
            'none of the 64 attribute option combo(s) of ' +
                '`http://example.org/fhir/m3/ValueSet/d2-aoc-O4VaNks6tta-vs` may be captured at any of the ' +
                '1 organisation unit(s) this form admits',
        )
    })

    it('reads the date axis back whole, naming the period nothing is open for', () => {
        const message =
            '`Questionnaire/lyLU2wR22tC` cannot be generated against: none of the 64 attribute option ' +
            'combo(s) of `http://example.org/fhir/m4/ValueSet/d2-aoc-O4VaNks6tta-vs` is open for the ' +
            'period `202608`: DHIS2 opens a category option for a calendar window and refuses a capture ' +
            'whose period the window does not cover with E8032'

        expect(uncapturableReason(message, 'lyLU2wR22tC')).toContain('is open for the period `202608`')
        expect(uncapturableReason(message, 'lyLU2wR22tC')).toContain('E8032')
    })

    it('shows a message shaped some other way verbatim, rather than trimming the wrong head off it', () => {
        expect(uncapturableReason('the server refused this read', 'lyLU2wR22tC')).toBe(
            'the server refused this read',
        )
        expect(uncapturableReason('`Questionnaire/other` cannot be generated against: why', 'lyLU2wR22tC')).toBe(
            '`Questionnaire/other` cannot be generated against: why',
        )
    })

    it('reads the refusal off the one status the operation states it with', () => {
        expect(UNCAPTURABLE_FORM_STATUS).toBe(422)
    })
})

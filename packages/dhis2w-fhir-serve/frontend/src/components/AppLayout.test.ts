import { describe, expect, it } from 'vitest'

import { offeredNavItems, palettePages } from '@/components/AppLayout'
import { DEFAULT_UI_CONFIG, ORGANISATION_UNIT_PACKAGE, type UiConfig } from '@/lib/uiconfig'

/**
 * Which pages this run leads to, for the two shapes a served project can have.
 *
 * A NAVIGATION ENTRY IS A PROMISE. The rail and the command palette read one array, so a page that
 * answers a refusal has to be absent from both or present in both - and the four capture pages
 * answer a refusal on a package, whose server declares no QuestionnaireResponse, holds no
 * Questionnaire, and refuses a submission 405. The pages a package really has stay: it publishes
 * organisation units, the terminology under them, and a CapabilityStatement about itself.
 */
const PACKAGE: UiConfig = {
    basemaps: [],
    dhis2_base_url: null,
    tracked_entities: null,
    publishes: ORGANISATION_UNIT_PACKAGE,
}

const paths = (config: UiConfig): string[] => offeredNavItems(config).map((item) => item.path)

describe('the navigation a package offers', () => {
    it('leads to no page that has nothing on it', () => {
        expect(paths(PACKAGE)).not.toContain('forms')
        expect(paths(PACKAGE)).not.toContain('responses')
        expect(paths(PACKAGE)).not.toContain('evaluate')
        expect(paths(PACKAGE)).not.toContain('playground')
    })

    it('leads to the pages a package really publishes', () => {
        expect(paths(PACKAGE)).toContain('')
        expect(paths(PACKAGE)).toContain('organisation-units')
        expect(paths(PACKAGE)).toContain('terminology')
        expect(paths(PACKAGE)).toContain('server')
    })

    it('offers the command palette exactly what the rail offers, so neither leads where the other does not', () => {
        expect(palettePages(PACKAGE).map((page) => page.path)).toEqual(paths(PACKAGE))
    })
})

describe('the navigation a guide offers', () => {
    it('keeps every capture page, which is what a guide is for', () => {
        expect(paths(DEFAULT_UI_CONFIG)).toContain('forms')
        expect(paths(DEFAULT_UI_CONFIG)).toContain('responses')
        expect(paths(DEFAULT_UI_CONFIG)).toContain('evaluate')
        expect(paths(DEFAULT_UI_CONFIG)).toContain('playground')
    })
})

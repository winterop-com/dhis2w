import { expect, test, type Page } from '@playwright/test'

/**
 * The organisation units page under `[generate.organisation_units] geometry`.
 *
 * The fixture registry is generated with the default `full`, so each case here tells the browser
 * what a project generated under another setting would have served: `/facade/uiconfig` states the
 * setting, and the Location reads come back with the geometry that setting leaves out removed.
 * Everything else is the real server's answer.
 */

/** How long the engine gets to fetch, paint, and settle - the same allowance orgunits.spec uses. */
const MAP_READY_TIMEOUT = 15_000

/** The extension a Location's boundary travels on - see `lib/orgunits.ts`. */
const BOUNDARY_EXTENSION_URL = 'http://hl7.org/fhir/StructureDefinition/location-boundary-geojson'

interface LocationEntry {
    resource?: { position?: unknown; extension?: { url?: string }[] }
}

/** Serve the page as a project generated under `geometry` would have been served. */
async function serveGeneratedUnder(page: Page, geometry: 'position' | 'none'): Promise<void> {
    await page.route('**/uiconfig', async (route) => {
        const response = await route.fetch()
        const settings = (await response.json()) as Record<string, unknown>
        await route.fulfill({ response, json: { ...settings, organisation_unit_geometry: geometry } })
    })
    await page.route('**/Location**', async (route) => {
        const response = await route.fetch()
        const bundle = (await response.json()) as { entry?: LocationEntry[] }
        for (const entry of bundle.entry ?? []) {
            const resource = entry.resource
            if (resource === undefined) continue
            resource.extension = (resource.extension ?? []).filter(
                (extension) => extension.url !== BOUNDARY_EXTENSION_URL,
            )
            if (geometry === 'none') delete resource.position
        }
        await route.fulfill({ response, json: bundle })
    })
}

test('a project publishing points draws them and says it publishes no boundaries', async ({ page }) => {
    await serveGeneratedUnder(page, 'position')
    await page.goto('/#/organisation-units')

    const map = page.getByTestId('org-unit-map')
    await expect(map).toHaveAttribute('data-map-ready', 'true', { timeout: MAP_READY_TIMEOUT })
    await expect(page.getByTestId('org-unit-map-points-only')).toHaveText(
        'This guide publishes organisation units as points, without boundaries.',
    )
})

test('a project publishing no geometry gets no map, and the details take its place', async ({ page }) => {
    await serveGeneratedUnder(page, 'none')
    await page.goto('/#/organisation-units')

    await expect(page.getByRole('heading', { name: 'Hierarchy' })).toBeVisible()
    await expect(page.getByRole('complementary', { name: 'Organisation unit details' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Map', exact: true })).toHaveCount(0)
    await expect(page.getByTestId('org-unit-map')).toHaveCount(0)
})

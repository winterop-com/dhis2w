import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { PageHeader } from '@/components/PageState'
import { Card, CardContent } from '@/components/ui/card'
import { useUiConfig } from '@/hooks/use-ui-config'
import { isPackage, packageStatement, packageSubject } from '@/lib/uiconfig'

/** What every address a package does not lead anywhere from is headed. */
export const PACKAGE_PAGE_TITLE = 'This project publishes no forms'

/**
 * The four capture addresses on a server that serves a package, and the guide's own pages on one that does not.
 *
 * A PACKAGE IS NOT A GUIDE WITH AN EMPTY FORM CATALOGUE. `[ig] publishes` says the project holds no
 * Questionnaire and never will, and the API half of this server already knows it: the
 * CapabilityStatement declares no QuestionnaireResponse, `GET /Questionnaire` is answered 404, and a
 * submission is refused 405. Rendering the capture screens over those answers turns each of them
 * into a red card about a read that failed, which reads as this server being broken rather than as
 * this project being a package.
 *
 * So the four addresses answer with what the project is. They still answer - a link somebody kept
 * from a guide is not silently redirected somewhere else, which is the rule `App.tsx` states for an
 * unknown address - and the way on is the hierarchy, because the organisation units are what a
 * package publishes and the one page of this app it really has.
 *
 * The sentence is the server's. `packageStatement` composes the words
 * `dhis2w_fhir_serve.errors.package_statement` answers a client with, so the screen and the endpoint
 * say the same thing about the same project.
 */
export function PackagePage({ children }: { children: ReactNode }) {
    const { config, loading } = useUiConfig()
    // The page waits for the answer rather than mounting on the guess and being replaced. Mounting
    // first would run the wrapped page's own reads, which on a package are the very refusals this
    // wrapper exists to keep off the screen - and the wait is one same-origin read of a few hundred
    // bytes, against a page that would otherwise render and then vanish.
    if (loading) return null
    if (!isPackage(config)) return <>{children}</>
    return (
        <>
            <PageHeader
                title={PACKAGE_PAGE_TITLE}
                description={`This server publishes ${packageSubject(config) ?? 'no forms'} and nothing to capture against.`}
            />
            <Card>
                <CardContent className="py-8 text-sm">
                    <p data-testid="package-statement">
                        {packageStatement(config)}{' '}
                        <Link to="/organisation-units" className="interactive-link">
                            Open the hierarchy
                        </Link>
                        .
                    </p>
                </CardContent>
            </Card>
        </>
    )
}

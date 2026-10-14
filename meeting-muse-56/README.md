# Meeting Muse

Redesign the current Meeting Mind interface with a much stronger visual identity. The previous design is too generic, too centered, too white, and resembles a default SaaS landing page template. Do not make another variation of the same layout.

Creative direction: Editorial Tech meets Intelligent Workspace

Create a distinctive, premium technology product with confident typography, asymmetric composition, rich visual contrast, and purposeful motion.

The design must look intentionally art-directed, not like a generic AI-generated dashboard.

1. Break away from the current layout

Remove the centered hero with a small badge, centered heading, subtitle, and large white form card.

Avoid placing every element inside rounded rectangles.

Avoid excessive thin borders and repetitive cards.

Do not use the same three-tab upload bar and large form layout from the current version.

Use a more editorial, asymmetric composition with a clear focal point.

Give the page depth through background layers, typography, spacing, and carefully controlled color.

2. Establish a stronger visual identity

Use:

Warm ivory or soft stone as the main light background.

Deep ink/navy for strong text contrast.

A confident cobalt blue as the signature color.

A small amount of electric blue or lavender for interactive details.

A refined display typeface for headlines, paired with a highly readable sans-serif for the interface.

Use large typography, deliberate whitespace, subtle gradients, and selective visual contrast. Make the brand recognizable even without its logo.

Do not make the entire website dark. Use a light editorial landing experience and a more focused workspace for analysis results.

3. Reimagine the upload screen

Design the initial screen as a product experience, not a form.

Use an asymmetric two-part composition:

The left side introduces the product with a large, distinctive headline: “Every meeting leaves a trail. Find what matters.”

A concise supporting line explains that Meeting Mind tracks decisions, changes, and evidence in Vietnamese meeting transcripts.

The right side contains a visually integrated transcript input workspace.

Make the transcript input feel like a real editor: clean typography, visible speaker labels when present, a comfortable writing area, and a refined toolbar.

Include:

Paste transcript.

Upload .txt.

Try a sample.

Do not expand all input methods at once. Keep the controls compact and context-sensitive.

When the user clicks “Try a sample”, open a small, animated dropdown with these five descriptive options:

Standard Sprint Planning

Decision Change

Chaotic Discussion

Implicit Agreement

Sarcasm and Conflicting Statements

Do not number them or display them as five large cards. Connect them to the actual existing sample files.

4. Add one memorable product visualization

Instead of decorative AI illustrations, create a small but meaningful visual showing how Meeting Mind works.

For example, display a compact, elegant decision timeline:

PROPOSED → MODIFIED → CONFIRMED

Use sample content such as PostgreSQL being superseded by MongoDB, clearly identified as an illustrative example.

The visualization should demonstrate the product's distinctive ability to trace decision changes. Use fine connecting lines, small status markers, restrained motion, and strong typography.

Keep it secondary to the transcript input. Do not fill the screen with meaningless charts or fake analytics.

5. Make interactions feel deliberate

Add subtle, polished motion:

Smooth reveal of the sample dropdown.

A gentle focus transition when entering the transcript.

Small hover movements and color transitions on buttons.

A short, elegant transition into the analysis state.

A purposeful loading animation during the real pipeline execution.

Use short transitions, generally around 150–250 ms. Avoid constant floating animations, excessive glow, large animated gradients, or unnecessary visual effects.

6. Transform the results into a real intelligent workspace

After analysis, transition into a distinct workspace rather than keeping the landing-page layout.

Make the following features visually clear:

Overview.

Decisions & History.

Actions & Issues.

Evidence Review.

Export JSON.

Use a compact navigation system and an editorial hierarchy. Make the decision timeline and evidence inspector the most distinctive components.

Use actual data from the existing Python pipeline and JSON schema. Show superseded decisions, confirmed outcomes, unresolved discussions, and needs_review warnings only when supported by real output.

Evidence quotes should be visually connected to their source utterances. The user should understand why the system produced a result.

7. Preserve the actual implementation

Inspect the existing code before changing it.

Keep the existing Preprocessor, Extractor, Resolver, Validator, Gemini integration, sample transcripts, CLI, and JSON export.

Do not replace working functionality with mockups. Do not fabricate analysis results, benchmark statistics, or progress percentages. Keep API keys secure.

The existing website should be visually redesigned, not replaced with a disconnected frontend.

Final requirement

The current design is too generic. The new design must have a clearly different composition, stronger typographic character, more memorable branding, richer visual depth, and subtle purposeful animation.

Do not simply change colors or add shadows to the existing layout. Rethink the art direction and composition while keeping the workflow simple and the product functionality intact.

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/dc42b0be-0e8e-4e8c-8fa1-12d9d29c9500).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```

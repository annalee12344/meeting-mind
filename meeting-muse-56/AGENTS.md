<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->

## Application structure
- Keep Meeting Mind input at `/` and its results in a dedicated workspace component so the input experience and analysis hierarchy remain distinct.
- Render results from the MeetingResult schema and retain unmodified source JSON for export; sample expected output is explicitly labeled and never presented as a live pipeline run.
- Keep transcript parsing browser-safe and source evidence linked by speaker/timestamp or supplied utterance ID so original context remains inspectable.

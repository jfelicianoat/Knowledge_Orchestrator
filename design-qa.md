# Design QA

- Source visual truth: `C:\Users\jfeli\.codex\generated_images\019fed91-d2a6-71f2-ae4b-43b8b5292e5b\exec-5e5b214c-7fde-4214-975b-0c8715dd3759.png`
- Implementation screenshot: unavailable
- Intended implementation viewport: 1440 × 900 desktop pixels
- Source dimensions: 1487 × 1058 pixels
- Implementation dimensions: unavailable
- CSS size and density normalization: not applicable; native Tkinter desktop application
- State: Trabajo, filtro En curso/Atención, first work selected

## Full-view comparison evidence

Blocked. The source image was opened successfully, but the native implementation could not be rendered from Codex's isolated process. A user-provided capture confirms that the normal Windows PowerShell session starts Tcl/Tk 8.6.15 correctly; the failure is therefore limited to the sandbox used for automated visual capture. Code inspection, automated tests, import parsing and snapshot queries are not substitutes for visible comparison.

## Focused region comparison evidence

Not performed. Without an implementation capture it is not possible to compare navigation, master/detail proportions, typography, spacing, semantic colors, button states or dense table rendering against the source.

## Findings

- [P0] Native UI cannot be captured from the Codex sandbox.
  - Location: isolated Codex Python/Tcl/Tk process, before `OrchestratorDashboard` is constructed.
  - Evidence: `tkinter.TclError: Can't find a usable init.tcl` inside the sandbox, while the user's normal PowerShell session reports Tcl/Tk 8.6.15 successfully.
  - Packaging evidence: packaging remains unverified inside the sandbox; the build script stops rather than producing a package without Tkinter.
  - Impact: blocks a rendered implementation screenshot and interaction testing.
  - Fix: launch the app from the normal Windows session at 1440 × 900 and provide a capture of the Trabajo screen for the final comparison.

## Required fidelity surfaces

- Fonts and typography: specified in code as Segoe UI/Consolas, but not visually verified.
- Spacing and layout rhythm: master/detail structure and dimensions are implemented, but not visually verified.
- Colors and visual tokens: mapped from `DESIGN.md`, but native rendering and contrast are not visually verified.
- Image quality and asset fidelity: the reference contains no content imagery; the KO lettermark and native controls still require visual verification.
- Copy and content: Spanish operational copy is implemented and covered structurally; wrapping and truncation are not visually verified.

## Comparison history

- Attempt 1: source opened; implementation launch failed before Tk window creation. No visual fixes can be justified without a render.
- Attempt 2 (continuation): Python 3.14, Python 3.13 and the bundled Codex Python runtime were tested independently; all fail during Tcl initialization before a window exists. A minimal isolated Tcl library also failed, confirming that the blocker cannot be repaired inside the project workspace.
- Attempt 3: the user ran the Tcl/Tk preflight successfully in a normal Windows PowerShell session and provided a capture showing version 8.6.15. This isolates the remaining failure to Codex's sandbox; a native implementation capture is still required.
- Automated evidence: 125 unit tests passed, including work snapshots and manual retry/ignore recovery. This validates behavior, not fidelity.

## Implementation checklist

1. Render Trabajo from the normal Windows session at 1440 × 900 with realistic active, failed and completed jobs.
2. Capture and combine source and implementation in one comparison input.
3. Fix all visible P0/P1/P2 differences and repeat the comparison.

## Follow-up polish

Deferred until the first valid native render exists.

final result: blocked

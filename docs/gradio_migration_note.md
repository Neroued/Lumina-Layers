# Gradio Migration Note

Lumina Studio has completed the frontend migration from legacy Gradio-based UI
entrypoints to the current React + FastAPI architecture.

This update keeps runtime compatibility behavior for generic file-like upload
objects (objects exposing a `.name` attribute), while removing Gradio-specific
naming and test coupling from active code/test paths.

Historical references may remain in changelog/history documents for traceability,
but active implementation and tests should no longer require Gradio-specific
semantics.

"""Independent features, registered by the application composition root."""

from app.presentation.module_runtime import ModuleSpec


# Factories are lazy strings so optional feature pages are only imported when
# the module is enabled. The module owns its own persistence namespace.
FEATURE_MODULES = (
    ModuleSpec(
        id="lyrics",
        title="歌词学习",
        factory="app.features.lyrics:LyricsModule",
        api_version=1,
        default_enabled=True,
    ),
)

# 1.4.1: focused functional update

This update builds on the existing public workbench. It is not a copy of the private/local application. No prompt templates, agent instructions, model weights, voices, account services, private projects, or runtime configuration are added or changed.

## Optional single-line subtitle pages

The existing `media_tools.py subtitles` and recipe-rendering commands accept an optional top-level `pagination` object in their subtitle JSON:

```json
{
  "width": 1920,
  "height": 1080,
  "pagination": {"max_columns": 25},
  "subtitles": [
    {"start": 1, "end": 11, "text": "这是第一句话，随后介绍新的方法。最后检查结果！"}
  ]
}
```

`caption_pages.py` is a pure, model-free text and timing module. It prefers punctuation/clause boundaries, preserves authored punctuation, avoids starting a page with closing punctuation, and does not split Latin terms. Approximate CJK column width is capped by the canvas and font size. Oversized terms and intervals too short for ASS timestamps fail before output is written. Existing multiline output is unchanged when pagination is omitted; independent titles are not repaginated.

Original cue boundaries are retained. Internal page timing is **estimated by text width, not aligned to speech**. Review the SRT/ASS pages against audio and final render; font metrics, custom placement, and reading speed need human review. This is an opt-in CLI/recipe feature, not a new workbench transcript or caption-alignment interface.

## Module boundaries

- Frontend source and shipped runtime assets are unchanged; no assistant UI changes are included.
- Subtitle pagination has no I/O, model calls, prompts, or project state; the existing media command owns validation and serialization.
- Backend, launcher and plugin version metadata are aligned at 1.4.1; the unchanged frontend retains its existing package version. Prior 1.4.0 release assets are not replaced.

## Validation scope

Unit/integration tests cover existing public functionality plus pagination regressions. The existing frontend bundle is retained byte-for-byte. Synthetic media tests are not full-film listening, real-model quality, clean-install, or Windows validation. There are no paid/cloud generation calls.

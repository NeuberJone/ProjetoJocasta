import unittest

from core.release_notes import load_release_notes, parse_release_notes
from core.version import __version__


class ReleaseNotesTests(unittest.TestCase):
    def test_selects_exact_running_version_without_unreleased_or_older_entries(self):
        changelog = """# Changelog
## [Não lançado]
### Added
- Recurso futuro.
## [1.6.390] - 2026-11-06
### Added
- Outra versão.
## [1.6.39] - 2026-11-05
### Added
- Lista do rolo.
### Fixed
- Preserva os espaços.
## [1.6.38] - 2026-11-04
### Fixed
- Correção anterior.
"""
        notes = parse_release_notes(changelog, "1.6.39")
        self.assertIsNotNone(notes)
        self.assertEqual(notes.date, "2026-11-05")
        self.assertEqual(notes.sections, {
            "Implementado": ["Lista do rolo."],
            "Alterado": [],
            "Removido": [],
            "Corrigido": ["Preserva os espaços."],
        })

    def test_keeps_multiline_changes_and_removals_in_their_categories(self):
        notes = parse_release_notes("""## [2.0.0]
### Changed
- Novo fluxo de fechamento
  com confirmação no final.
### Removed
- Exportação antiga.
""", "2.0.0")
        self.assertEqual(notes.sections["Alterado"], [
            "Novo fluxo de fechamento com confirmação no final.",
        ])
        self.assertEqual(notes.sections["Removido"], ["Exportação antiga."])

    def test_missing_version_does_not_fall_back_to_another_release(self):
        self.assertIsNone(parse_release_notes("""## [Não lançado]
### Added
- Recurso futuro.
## [1.0.0]
### Added
- Recurso antigo.
""", "2.0.0"))

    def test_loads_notes_for_running_app_from_project_resource(self):
        notes = load_release_notes(__version__)
        self.assertIsNotNone(notes)
        self.assertTrue(any(notes.sections.values()))


if __name__ == "__main__":
    unittest.main()

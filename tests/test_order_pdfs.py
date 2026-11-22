"""Testes da descoberta/seleção de PDFs originais e das miniaturas
(core/order_pdfs.py) — Etapa D do recurso de identificação de vendedor e
rastreabilidade de arquivos (ver [[core/order_files.py]] pra Etapa B e
[[core/order_vendor_resolution.py]] pra Etapa C). Usa diretórios temporários
e PDFs sintéticos gerados com PyMuPDF (nunca arquivos reais da produção —
seção 17 da especificação original).
"""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from PIL import Image

from core.order_pdfs import (
    PDF_RESOLUTION_AMBIGUOUS,
    PDF_RESOLUTION_AUTO,
    PDF_RESOLUTION_MANUAL,
    PDF_RESOLUTION_NOT_FOUND,
    discover_order_pdfs,
    get_order_pdf_thumbnail,
    link_order_pdf,
    preview_order_pdf,
    resolve_order_pdf,
    unlink_order_pdf,
)
from core.printlogs_db import OrderRow, get_pdf_link_history, get_roll_orders, save_export_transactional


def _make_pdf(path: Path, *, pages: int = 1, width: float = 600, height: float = 800) -> None:
    doc = fitz.open()
    try:
        for _ in range(pages):
            page = doc.new_page(width=width, height=height)
            page.insert_text((50, 50), "pedido")
        doc.save(str(path))
    finally:
        doc.close()


def _make_protected_pdf(path: Path) -> None:
    doc = fitz.open()
    try:
        page = doc.new_page(width=600, height=800)
        page.insert_text((50, 50), "protegido")
        doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner123", user_pw="user123")
    finally:
        doc.close()


class DiscoverOrderPdfsTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp_dir.name) / "ESCOLINHA DOUGLAS AMERICA"
        self.folder.mkdir(parents=True)

    def tearDown(self):
        self._tmp_dir.cleanup()

    def test_missing_folder_returns_empty_list_not_raise(self):
        missing = Path(self._tmp_dir.name) / "nao_existe"
        self.assertEqual(discover_order_pdfs(str(missing)), [])

    def test_finds_pdf_directly_in_folder(self):
        _make_pdf(self.folder / "arte.pdf", pages=2)
        found = discover_order_pdfs(str(self.folder))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].page_count, 2)
        self.assertTrue(found[0].is_valid)

    def test_finds_pdf_in_subfolder_when_recursive(self):
        sub = self.folder / "Documentos"
        sub.mkdir()
        _make_pdf(sub / "arte.pdf")
        found = discover_order_pdfs(str(self.folder), recursive=True)
        self.assertEqual(len(found), 1)

    def test_non_recursive_skips_subfolder_pdfs(self):
        sub = self.folder / "Documentos"
        sub.mkdir()
        _make_pdf(sub / "arte.pdf")
        found = discover_order_pdfs(str(self.folder), recursive=False)
        self.assertEqual(found, [])

    def test_invalid_pdf_is_flagged_not_valid_but_still_listed(self):
        bad = self.folder / "corrompido.pdf"
        bad.write_bytes(b"isto nao e um pdf")
        found = discover_order_pdfs(str(self.folder))
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0].is_valid)
        self.assertTrue(found[0].error)

    def test_password_protected_pdf_is_flagged_not_valid(self):
        _make_protected_pdf(self.folder / "protegido.pdf")
        found = discover_order_pdfs(str(self.folder))
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0].is_valid)
        self.assertIn("senha", found[0].error)


def _order(document: str) -> OrderRow:
    return OrderRow(
        end_time="2026-11-10T10:00:00", document=document, fabric="DRYFIT", pedido="Cliente A",
        height_mm=1000.0, vpos_mm=0.0, real_m=1.0, source_path=f"/x/{document}", tipo="Pedido",
    )


class ResolveOrderPdfTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp_dir.name) / "ESCOLINHA DOUGLAS AMERICA"
        self.folder.mkdir(parents=True)

        self._db_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._db_dir.name) / "printlogs-test.db"
        self._patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._db_dir.cleanup()
        self._tmp_dir.cleanup()

    def _make_order(self, suffix: str = "0001") -> int:
        roll_id, _ = save_export_transactional(
            machine="M1", roll_name=f"M1-{suffix}", export_mode="normal", app_version="1.0.0",
            orders=[_order(f"doc{suffix}.jpeg")],
        )
        return int(get_roll_orders(roll_id)[0]["id"])

    def test_single_valid_pdf_auto_links(self):
        _make_pdf(self.folder / "arte.pdf")
        order_id = self._make_order()
        result = resolve_order_pdf(order_id, str(self.folder))
        self.assertEqual(result.state, PDF_RESOLUTION_AUTO)
        self.assertTrue(result.pdf_path.endswith("arte.pdf"))
        self.assertIsNotNone(result.link)

    def test_multiple_valid_pdfs_are_ambiguous_never_auto_picks_most_recent(self):
        _make_pdf(self.folder / "antigo.pdf")
        _make_pdf(self.folder / "novo.pdf")
        order_id = self._make_order()
        result = resolve_order_pdf(order_id, str(self.folder))
        self.assertEqual(result.state, PDF_RESOLUTION_AMBIGUOUS)
        self.assertEqual(len(result.candidates), 2)
        self.assertIsNone(result.link)

    def test_no_pdfs_returns_not_found(self):
        order_id = self._make_order()
        result = resolve_order_pdf(order_id, str(self.folder))
        self.assertEqual(result.state, PDF_RESOLUTION_NOT_FOUND)

    def test_manual_link_has_precedence_and_is_never_overwritten_by_auto(self):
        _make_pdf(self.folder / "arte.pdf")
        order_id = self._make_order()
        link_order_pdf(order_id, str(self.folder / "escolhido_manual.pdf"))

        result = resolve_order_pdf(order_id, str(self.folder))
        self.assertEqual(result.state, PDF_RESOLUTION_MANUAL)
        self.assertTrue(result.pdf_path.endswith("escolhido_manual.pdf"))

    def test_resolving_again_without_change_does_not_duplicate_history(self):
        _make_pdf(self.folder / "arte.pdf")
        order_id = self._make_order()
        resolve_order_pdf(order_id, str(self.folder))
        resolve_order_pdf(order_id, str(self.folder))
        self.assertEqual(len(get_pdf_link_history(order_id)), 1)

    def test_ambiguous_round_does_not_erase_previous_auto_link(self):
        _make_pdf(self.folder / "arte.pdf")
        order_id = self._make_order()
        first = resolve_order_pdf(order_id, str(self.folder))
        self.assertEqual(first.state, PDF_RESOLUTION_AUTO)

        _make_pdf(self.folder / "outra.pdf")  # agora ficou ambíguo
        second = resolve_order_pdf(order_id, str(self.folder))
        self.assertEqual(second.state, PDF_RESOLUTION_AMBIGUOUS)
        self.assertIsNotNone(second.link)
        self.assertTrue(second.link["pdf_path"].endswith("arte.pdf"))

    def test_unlink_then_resolve_allows_auto_again(self):
        _make_pdf(self.folder / "arte.pdf")
        order_id = self._make_order()
        link_order_pdf(order_id, str(self.folder / "escolha_antiga.pdf"))
        self.assertTrue(unlink_order_pdf(order_id))

        result = resolve_order_pdf(order_id, str(self.folder))
        self.assertEqual(result.state, PDF_RESOLUTION_AUTO)
        self.assertTrue(result.pdf_path.endswith("arte.pdf"))


class ThumbnailTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp_dir.name)

        self._cache_dir = tempfile.TemporaryDirectory()
        self._patcher = patch("core.order_pdfs._thumbnail_cache_dir", return_value=Path(self._cache_dir.name))
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._cache_dir.cleanup()
        self._tmp_dir.cleanup()

    def test_generates_png_thumbnail_preserving_aspect_ratio(self):
        pdf_path = self.folder / "arte.pdf"
        _make_pdf(pdf_path, width=600, height=800)

        result = get_order_pdf_thumbnail(str(pdf_path), max_size=(100, 100))
        self.assertEqual(result.error, "")
        self.assertEqual(result.page_count, 1)

        img = Image.open(io.BytesIO(result.png_bytes))
        self.assertLessEqual(img.width, 100)
        self.assertLessEqual(img.height, 100)
        self.assertAlmostEqual(img.width / img.height, 600 / 800, places=2)

    def test_second_call_reads_from_cache(self):
        pdf_path = self.folder / "arte.pdf"
        _make_pdf(pdf_path)

        first = get_order_pdf_thumbnail(str(pdf_path))
        self.assertTrue(first.png_bytes)

        cache_files = list(Path(self._cache_dir.name).glob("*.png"))
        self.assertEqual(len(cache_files), 1)
        sentinel = b"NOT-A-REAL-PNG-SENTINEL"
        cache_files[0].write_bytes(sentinel)

        second = get_order_pdf_thumbnail(str(pdf_path))
        self.assertEqual(second.png_bytes, sentinel)

    def test_cache_invalidated_when_file_changes(self):
        pdf_path = self.folder / "arte.pdf"
        _make_pdf(pdf_path, pages=1, width=600, height=800)
        first = get_order_pdf_thumbnail(str(pdf_path))

        _make_pdf(pdf_path, pages=2, width=300, height=400)
        second = get_order_pdf_thumbnail(str(pdf_path))

        self.assertEqual(second.page_count, 2)
        self.assertNotEqual(first.png_bytes, second.png_bytes)

    def test_invalid_pdf_returns_error_not_raise(self):
        bad = self.folder / "corrompido.pdf"
        bad.write_bytes(b"nao e um pdf")
        result = get_order_pdf_thumbnail(str(bad))
        self.assertTrue(result.error)
        self.assertIsNone(result.png_bytes)

    def test_password_protected_pdf_returns_error_not_raise(self):
        protected = self.folder / "protegido.pdf"
        _make_protected_pdf(protected)
        result = get_order_pdf_thumbnail(str(protected))
        self.assertIn("senha", result.error)
        self.assertIsNone(result.png_bytes)

    def test_out_of_range_page_returns_error(self):
        pdf_path = self.folder / "arte.pdf"
        _make_pdf(pdf_path, pages=1)
        result = get_order_pdf_thumbnail(str(pdf_path), page=5)
        self.assertTrue(result.error)
        self.assertIsNone(result.png_bytes)

    def test_missing_file_returns_error_not_raise(self):
        result = get_order_pdf_thumbnail(str(self.folder / "nao_existe.pdf"))
        self.assertTrue(result.error)


class PreviewOrderPdfTests(unittest.TestCase):
    """`preview_order_pdf` (Parte 1 — painel de Operação, antes do rolo ser
    salvo): mesma escolha de resolve_order_pdf, mas sem order_id e sem
    nenhum efeito colateral no banco."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp_dir.name) / "ESCOLINHA DOUGLAS AMERICA"
        self.folder.mkdir(parents=True)

    def tearDown(self):
        self._tmp_dir.cleanup()

    def test_single_valid_pdf_is_auto(self):
        _make_pdf(self.folder / "arte.pdf")
        result = preview_order_pdf(str(self.folder))
        self.assertEqual(result.state, PDF_RESOLUTION_AUTO)
        self.assertEqual(result.pdf_path, str(self.folder / "arte.pdf"))

    def test_multiple_valid_pdfs_is_ambiguous(self):
        _make_pdf(self.folder / "arte1.pdf")
        _make_pdf(self.folder / "arte2.pdf")
        result = preview_order_pdf(str(self.folder))
        self.assertEqual(result.state, PDF_RESOLUTION_AMBIGUOUS)
        self.assertEqual(result.pdf_path, "")
        self.assertEqual(len(result.candidates), 2)

    def test_no_pdf_is_not_found(self):
        result = preview_order_pdf(str(self.folder))
        self.assertEqual(result.state, PDF_RESOLUTION_NOT_FOUND)

    def test_missing_folder_is_not_found_not_raise(self):
        missing = Path(self._tmp_dir.name) / "nao_existe"
        result = preview_order_pdf(str(missing))
        self.assertEqual(result.state, PDF_RESOLUTION_NOT_FOUND)

    def test_invalid_pdf_alone_is_not_found(self):
        bad = self.folder / "corrompido.pdf"
        bad.write_bytes(b"isto nao e um pdf")
        result = preview_order_pdf(str(self.folder))
        self.assertEqual(result.state, PDF_RESOLUTION_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()

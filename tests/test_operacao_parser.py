import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from core.print_types import DEFAULT_RULES
from core.printers import Printer
from core.printlogs_db import make_job_hash
from modules.operacao.m1_check import STATUS_NOT_CONFIGURED as M1_STATUS_NOT_CONFIGURED
from modules.operacao.models import Job
from modules.operacao.parser import (
    build_auto_gap_job,
    canonicalize_fabric_name,
    check_reimported_jobs,
    classify_reimported_jobs,
    detect_machine_from_logs,
    fabric_from_document,
    find_cross_roll_duplicates,
    format_duplicate_message,
    format_reimport_warning,
    import_log_files,
    operator_code_from_document,
    parse_log_txt,
    pedido_from_document,
    resolve_default_import_dir,
    resolve_mirror_jpg_path,
    resolve_mirror_target_cm,
    split_dnd_files,
)
from modules.operacao.print_check import STATUS_INCOMPLETE, STATUS_NOT_AVAILABLE, STATUS_OK


class FabricFromDocumentTests(unittest.TestCase):
    def test_reposicao_strips_extension_and_duplicate_marker(self):
        self.assertEqual(fabric_from_document("N1 - Dryfit (2).jpeg"), "DRYFIT")

    def test_reposicao_strips_plain_extension(self):
        self.assertEqual(fabric_from_document("N1 - Dryfit.jpeg"), "DRYFIT")

    def test_reposicao_strips_textual_observation(self):
        self.assertEqual(fabric_from_document("N1 - Dryfit (reimpressão).jpeg"), "DRYFIT")

    def test_pedido_with_name_unaffected(self):
        self.assertEqual(fabric_from_document("16-10 - Dryfit - Primos e Amigos 3 (1).jpeg"), "DRYFIT")

    def test_no_fabric_segment_is_unknown(self):
        self.assertEqual(fabric_from_document("Jusc.jpg"), "DESCONHECIDO")


class FabricFromDocumentCanonicalizationTests(unittest.TestCase):
    """Com o cadastro de tecidos (fabrics_map), aliases do mesmo tecido devem
    ser agrupados sob o nome canônico — ex.: "Dry Fit" e "Dryfit" não podem
    aparecer como tecidos diferentes na Operação."""

    def setUp(self):
        self.fabrics_map = {
            "Dryfit": {"aliases": ["dryfit", "dry fit", "dry-fit", "drifit"], "roll_length_m": 90.0},
        }

    def test_alias_is_mapped_to_canonical_name(self):
        self.assertEqual(
            fabric_from_document("N1 - Dry Fit.jpeg", self.fabrics_map), "DRYFIT"
        )

    def test_canonical_and_alias_produce_same_result(self):
        canonical = fabric_from_document("N1 - Dryfit.jpeg", self.fabrics_map)
        alias = fabric_from_document("N2 - Dry Fit.jpeg", self.fabrics_map)
        self.assertEqual(canonical, alias)

    def test_unregistered_fabric_falls_back_to_raw_text(self):
        self.assertEqual(
            fabric_from_document("N1 - Tecido Novo.jpeg", self.fabrics_map), "TECIDO NOVO"
        )

    def test_no_fabrics_map_keeps_old_behavior(self):
        self.assertEqual(fabric_from_document("N1 - Dry Fit.jpeg"), "DRY FIT")


class OperatorCodeFromDocumentTests(unittest.TestCase):
    def test_single_letter_operator_code(self):
        self.assertEqual(operator_code_from_document("N1 - Dryfit"), "N")

    def test_multi_letter_operator_code(self):
        self.assertEqual(operator_code_from_document("NJ15 - Tactel"), "NJ")

    def test_space_between_letters_and_number_is_tolerated(self):
        self.assertEqual(operator_code_from_document("N 2 - Aeroready"), "N")

    def test_extension_on_single_segment_is_stripped(self):
        self.assertEqual(operator_code_from_document("N1.jpeg"), "N")

    def test_pedido_style_document_has_no_operator_code(self):
        self.assertEqual(operator_code_from_document("16-10 - Dryfit - Nome do Pedido"), "")

    def test_empty_document_has_no_operator_code(self):
        self.assertEqual(operator_code_from_document(""), "")


class PedidoFromDocumentTests(unittest.TestCase):
    def test_trailing_paren_is_noise_not_identity(self):
        self.assertEqual(pedido_from_document("16-10 - Dryfit - Salum 12 (Argentina).jpg"), "Salum 12")
        self.assertEqual(pedido_from_document("16-10 - Dryfit - Salum 12 (Brasil).jpg"), "Salum 12")

    def test_loose_trailing_number_without_paren_is_part_of_the_pedido_name(self):
        """Só número entre parênteses é ignorado — um número solto no fim,
        sem parênteses, é parte do nome do pedido (não um contador), senão
        o mesmo pedido (ex.: "Haras DRB 4") vira dois nomes diferentes
        dependendo de qual arquivo (com ou sem parênteses) é analisado."""
        self.assertEqual(pedido_from_document("16-10 - Dryfit - Escolinha Reis 21"), "Escolinha Reis 21")

    def test_same_pedido_with_and_without_parens_normalize_to_the_same_name(self):
        self.assertEqual(pedido_from_document("09-11 - Ribana - Haras DRB 4.JPEG"), "Haras DRB 4")
        self.assertEqual(pedido_from_document("09-11 - dryfit - Haras DRB 4 (2).jpeg"), "Haras DRB 4")


class ParseLogTxtPedidoModeTests(unittest.TestCase):
    """O pedido de um tipo pode ser detectado pelo nome do arquivo (padrão)
    ou usar um nome fixo configurado na regra do tipo (ex.: Reposição ->
    "Variados") — ver core.print_types.pedido_override_for_type."""

    def _write_log(self, document: str) -> str:
        tmp_dir = Path(tempfile.mkdtemp())
        path = tmp_dir / "log.txt"
        path.write_text(
            "[General]\n"
            "EndTime=21/10/2026 10:00:00\n"
            f"Document={document}\n"
            "[1]\n"
            f"Name={document}\n"
            "HeightMM=1000\n"
            "WidthMM=500\n"
            "VPositionMM=0\n",
            encoding="utf-8",
        )
        return str(path)

    def test_default_rules_still_detect_pedido_from_filename(self):
        path = self._write_log("N1 - Dryfit")
        job = parse_log_txt(path, type_rules=DEFAULT_RULES)
        self.assertEqual(job.tipo, "Reposição")
        self.assertEqual(job.pedido, "DESCONHECIDO")

    def test_fixed_pedido_mode_overrides_filename_detection(self):
        rules = [
            {"name": "Reposição", "pattern": r"^\s*[A-Za-z]{1,3}\s*\d+\s*-",
             "pedido_mode": "fixed", "pedido_fixed": "Variados"},
        ]
        path = self._write_log("N1 - Dryfit")
        job = parse_log_txt(path, type_rules=rules)
        self.assertEqual(job.tipo, "Reposição")
        self.assertEqual(job.pedido, "Variados")

    def test_auto_pedido_mode_is_unaffected_by_other_types_fixed_mode(self):
        rules = [
            {"name": "Reposição", "pattern": r"^\s*[A-Za-z]{1,3}\s*\d+\s*-",
             "pedido_mode": "fixed", "pedido_fixed": "Variados"},
            {"name": "Pedido", "pattern": r"^\s*\d{1,2}[-/.]\d{1,2}\s*-"},
        ]
        path = self._write_log("16-10 - Dryfit - Cliente A")
        job = parse_log_txt(path, type_rules=rules)
        self.assertEqual(job.tipo, "Pedido")
        self.assertEqual(job.pedido, "Cliente A")


class ParseLogTxtPrintCompletenessTests(unittest.TestCase):
    """Integração real do print_check dentro do parser — o campo que
    importa (`[Costs].PrintHeightMM`) só existe no log de verdade, não no
    fixture mínimo usado pelos outros testes desta classe."""

    def _write_log(self, *, height_mm: float, vpos_mm: float, print_height_mm: str | None, file_count: int = 1) -> str:
        tmp_dir = Path(tempfile.mkdtemp())
        path = tmp_dir / "log.txt"
        costs_line = f"PrintHeightMM = {print_height_mm}\n" if print_height_mm is not None else ""
        path.write_text(
            "[General]\n"
            "EndTime=21/10/2026 10:00:00\n"
            "Document=16-10 - Dryfit - Cliente A.jpeg\n"
            f"FileCount = {file_count}\n"
            "[Costs]\n"
            f"{costs_line}"
            "[1]\n"
            "Name=16-10 - Dryfit - Cliente A.jpeg\n"
            f"HeightMM={height_mm}\n"
            "WidthMM=500\n"
            f"VPositionMM={vpos_mm}\n",
            encoding="utf-8",
        )
        return str(path)

    def test_matching_print_height_is_ok(self):
        path = self._write_log(height_mm=1000.0, vpos_mm=0.0, print_height_mm="1000.0")
        job = parse_log_txt(path, type_rules=DEFAULT_RULES)
        self.assertEqual(job.print_status, STATUS_OK)

    def test_shortfall_is_flagged_incomplete(self):
        path = self._write_log(height_mm=7975.9, vpos_mm=0.0, print_height_mm="5171.9")
        job = parse_log_txt(path, type_rules=DEFAULT_RULES)
        self.assertEqual(job.print_status, STATUS_INCOMPLETE)
        self.assertIn("2.80 m", job.print_status_detail)

    def test_missing_costs_section_is_not_available(self):
        path = self._write_log(height_mm=1000.0, vpos_mm=0.0, print_height_mm=None)
        job = parse_log_txt(path, type_rules=DEFAULT_RULES)
        self.assertEqual(job.print_status, STATUS_NOT_AVAILABLE)

    def test_multi_file_job_is_not_available(self):
        path = self._write_log(height_mm=1000.0, vpos_mm=0.0, print_height_mm="500.0", file_count=2)
        job = parse_log_txt(path, type_rules=DEFAULT_RULES)
        self.assertEqual(job.print_status, STATUS_NOT_AVAILABLE)


class ParseLogTxtNumberedSectionTests(unittest.TestCase):
    """Achado real (log de "Gráfico de cor" direto da Mimaki TS55, pasta
    Referencia/ — teste de cor da máquina, não um pedido normal): a seção
    numérica do primeiro arquivo nem sempre se chama "[1]" — esse log real
    tinha FileCount=2 com seções "[2]"/"[3]" em vez de "[1]"/"[2]". Antes
    desta correção, o parser só reconhecia literalmente "[1]", então
    HeightMM/WidthMM/VPositionMM nunca eram lidos (ficavam 0.0) e o arquivo
    era descartado silenciosamente como inválido (ver
    `import_log_files`: `height_mm <= 0` → `skipped_invalid`)."""

    def _write_log(self, *, first_section: str, second_section: str) -> str:
        tmp_dir = Path(tempfile.mkdtemp())
        path = tmp_dir / "log.txt"
        path.write_text(
            "[General]\n"
            "EndTime=18/11/2026 15:39:42\n"
            "Document=Gráfico de cor\n"
            "FileCount = 2\n"
            f"[{first_section}]\n"
            "Name=Gráfico de cor\n"
            "HeightMM=332.4\n"
            "WidthMM=480.2\n"
            "VPositionMM=257.1\n"
            f"[{second_section}]\n"
            "Name=Gráfico de cor\n"
            "HeightMM=498.7\n"
            "WidthMM=771.1\n"
            "VPositionMM=257.1\n",
            encoding="utf-8",
        )
        return str(path)

    def test_sections_numbered_starting_from_1_still_work(self):
        path = self._write_log(first_section="1", second_section="2")
        job = parse_log_txt(path, type_rules=DEFAULT_RULES)
        self.assertEqual(job.height_mm, 332.4)

    def test_sections_numbered_starting_from_2_are_still_read(self):
        path = self._write_log(first_section="2", second_section="3")
        job = parse_log_txt(path, type_rules=DEFAULT_RULES)
        self.assertEqual(job.height_mm, 332.4)
        self.assertEqual(job.width_mm, 480.2)
        self.assertEqual(job.vpos_mm, 257.1)

    def test_only_the_first_numeric_section_is_used_never_the_second(self):
        path = self._write_log(first_section="2", second_section="3")
        job = parse_log_txt(path, type_rules=DEFAULT_RULES)
        # Nunca devolve os valores da segunda seção ("498.7"/"771.1") —
        # mesmo comportamento de sempre pra job multi-arquivo (só o
        # primeiro representa o job).
        self.assertNotEqual(job.height_mm, 498.7)


class BuildAutoGapJobTests(unittest.TestCase):
    """Impressoras sem arquivo de espaço dedicado registram o avanço em
    branco direto no log do arquivo real (VPositionMM) — esse avanço tem
    que virar um item de ESPAÇO próprio na listagem."""

    def _job(self, *, vpos_mm: float, is_gap: bool = False, start_time=None) -> Job:
        return Job(
            end_time=datetime(2026, 10, 30, 10, 0, 0),
            document="16-10 - Dryfit - Cliente A.jpeg",
            fabric="DRYFIT",
            pedido="Cliente A",
            height_mm=1000.0,
            vpos_mm=vpos_mm,
            real_mm=1000.0,
            src_file="C:/logs/16-10 - Dryfit - Cliente A.jpeg.txt",
            is_gap=is_gap,
            start_time=start_time,
        )

    def test_no_gap_when_vpos_is_zero(self):
        self.assertIsNone(build_auto_gap_job(self._job(vpos_mm=0.0)))

    def test_no_gap_for_an_already_gap_job(self):
        self.assertIsNone(build_auto_gap_job(self._job(vpos_mm=500.0, is_gap=True)))

    def test_gap_job_uses_vpos_as_length_and_marks_as_espaco(self):
        job = self._job(vpos_mm=1097.7, start_time=datetime(2026, 10, 30, 9, 58, 0))
        gap = build_auto_gap_job(job)
        self.assertIsNotNone(gap)
        self.assertTrue(gap.is_gap)
        self.assertEqual(gap.fabric, "ESPAÇO")
        self.assertEqual(gap.real_mm, 1097.7)
        self.assertEqual(gap.height_mm, 1097.7)
        self.assertEqual(gap.end_time, datetime(2026, 10, 30, 9, 58, 0))
        self.assertNotEqual(gap.src_file, job.src_file)

    def test_gap_job_falls_back_to_end_time_without_start_time(self):
        job = self._job(vpos_mm=200.0, start_time=None)
        gap = build_auto_gap_job(job)
        self.assertLess(gap.end_time, job.end_time)


class ImportLogFilesTests(unittest.TestCase):
    """`import_log_files` extrai, sem Tkinter, a decisão que antes só
    existia dentro de `modules/operacao/ui.py:_import_paths` — pular
    arquivo repetido/inválido, inserir ESPAÇO automático e cruzar com o log
    secundário (M1) — pra poder ser testada e reaproveitada (ex.: um futuro
    reprocessamento em lote) sem precisar abrir a interface."""

    def _write_log(self, tmp_dir: Path, name: str, *, document: str,
                    height_mm: float = 1000.0, vpos_mm: float = 0.0,
                    end_time: str = "21/10/2026 10:00:00") -> str:
        path = tmp_dir / name
        path.write_text(
            "[General]\n"
            f"EndTime={end_time}\n"
            f"Document={document}\n"
            "[1]\n"
            f"Name={document}\n"
            f"HeightMM={height_mm}\n"
            "WidthMM=500\n"
            f"VPositionMM={vpos_mm}\n",
            encoding="utf-8",
        )
        return str(path)

    def test_skips_file_already_in_existing_src(self):
        tmp_dir = Path(tempfile.mkdtemp())
        path = self._write_log(tmp_dir, "a.txt", document="16-10 - Dryfit - Cliente A.jpeg")
        outcome = import_log_files([path], existing_src={path})
        self.assertEqual(outcome.jobs, [])
        self.assertEqual(outcome.files_added, 0)
        self.assertEqual(outcome.skipped_invalid, 0)

    def test_skips_and_counts_invalid_height(self):
        tmp_dir = Path(tempfile.mkdtemp())
        path = self._write_log(tmp_dir, "a.txt", document="16-10 - Dryfit - Cliente A.jpeg", height_mm=0.0)
        outcome = import_log_files([path], type_rules=DEFAULT_RULES)
        self.assertEqual(outcome.jobs, [])
        self.assertEqual(outcome.files_added, 0)
        self.assertEqual(outcome.skipped_invalid, 1)

    def test_valid_file_is_added_and_counted(self):
        tmp_dir = Path(tempfile.mkdtemp())
        path = self._write_log(tmp_dir, "a.txt", document="16-10 - Dryfit - Cliente A.jpeg")
        outcome = import_log_files([path], type_rules=DEFAULT_RULES)
        self.assertEqual(outcome.files_added, 1)
        self.assertEqual(outcome.skipped_invalid, 0)
        self.assertEqual([j.src_file for j in outcome.jobs], [path])

    def test_auto_gap_job_is_inserted_before_the_real_job(self):
        tmp_dir = Path(tempfile.mkdtemp())
        path = self._write_log(
            tmp_dir, "a.txt", document="16-10 - Dryfit - Cliente A.jpeg", vpos_mm=250.0,
        )
        outcome = import_log_files([path], type_rules=DEFAULT_RULES)
        self.assertEqual(len(outcome.jobs), 2)
        self.assertTrue(outcome.jobs[0].is_gap)
        self.assertFalse(outcome.jobs[1].is_gap)
        self.assertEqual(outcome.files_added, 1)

    def test_secondary_check_disabled_leaves_m1_status_untouched(self):
        tmp_dir = Path(tempfile.mkdtemp())
        path = self._write_log(tmp_dir, "a.txt", document="16-10 - Dryfit - Cliente A.jpeg")
        outcome = import_log_files(
            [path], type_rules=DEFAULT_RULES, secondary_log_enabled=False,
        )
        self.assertEqual(outcome.jobs[0].m1_status, "")
        self.assertEqual(outcome.sec_alerts, 0)
        self.assertFalse(outcome.sec_unknown_format)

    def test_secondary_check_enabled_runs_even_with_empty_folder(self):
        """Pasta do log adicional não configurada não deve impedir o cruzamento
        de rodar — é o próprio `m1_check.check_job` quem decide "não
        configurado" (ver STATUS_NOT_CONFIGURED), não `import_log_files`."""
        tmp_dir = Path(tempfile.mkdtemp())
        path = self._write_log(tmp_dir, "a.txt", document="16-10 - Dryfit - Cliente A.jpeg")
        outcome = import_log_files(
            [path], type_rules=DEFAULT_RULES, secondary_log_enabled=True, secondary_log_folder="",
        )
        self.assertEqual(outcome.jobs[0].m1_status, M1_STATUS_NOT_CONFIGURED)
        self.assertEqual(outcome.sec_alerts, 0)
        self.assertFalse(outcome.sec_unknown_format)

    def test_secondary_check_skips_gap_jobs(self):
        tmp_dir = Path(tempfile.mkdtemp())
        path = self._write_log(
            tmp_dir, "a.txt", document="16-10 - Dryfit - Cliente A.jpeg", vpos_mm=250.0,
        )
        outcome = import_log_files(
            [path], type_rules=DEFAULT_RULES, secondary_log_enabled=True, secondary_log_folder="",
        )
        gap_job, real_job = outcome.jobs
        self.assertTrue(gap_job.is_gap)
        self.assertEqual(gap_job.m1_status, "")
        self.assertEqual(real_job.m1_status, M1_STATUS_NOT_CONFIGURED)


class DetectMachineFromLogsTests(unittest.TestCase):
    """`detect_machine_from_logs` extrai, sem Tkinter, a sugestão automática
    de máquina que antes só existia dentro de
    `modules/operacao/ui.py:_detect_machine_from_logs` — recebe o cadastro
    de impressoras por parâmetro (`printers`) em vez de ler o disco, o que
    também é o que a torna testável."""

    def _write_log(self, tmp_dir: Path, name: str, *, computer_name: str) -> str:
        path = tmp_dir / name
        path.write_text(f"[General]\nComputerName={computer_name}\n", encoding="utf-8")
        return str(path)

    def _printer(self, *, computer_name: str, display_name: str = "M1") -> Printer:
        return Printer(key=display_name.lower(), name=display_name, display_name=display_name,
                       computer_name=computer_name)

    def test_single_matching_computer_suggests_its_printer(self):
        tmp_dir = Path(tempfile.mkdtemp())
        paths = [
            self._write_log(tmp_dir, "a.txt", computer_name="PC-M1"),
            self._write_log(tmp_dir, "b.txt", computer_name="PC-M1"),
        ]
        printers = [self._printer(computer_name="PC-M1", display_name="M1")]
        self.assertEqual(detect_machine_from_logs(paths, printers), "M1")

    def test_mixed_computers_returns_none(self):
        tmp_dir = Path(tempfile.mkdtemp())
        paths = [
            self._write_log(tmp_dir, "a.txt", computer_name="PC-M1"),
            self._write_log(tmp_dir, "b.txt", computer_name="PC-M2"),
        ]
        printers = [
            self._printer(computer_name="PC-M1", display_name="M1"),
            self._printer(computer_name="PC-M2", display_name="M2"),
        ]
        self.assertIsNone(detect_machine_from_logs(paths, printers))

    def test_unregistered_computer_returns_none(self):
        tmp_dir = Path(tempfile.mkdtemp())
        paths = [self._write_log(tmp_dir, "a.txt", computer_name="PC-DESCONHECIDO")]
        self.assertIsNone(detect_machine_from_logs(paths, []))

    def test_missing_computer_name_field_returns_none(self):
        tmp_dir = Path(tempfile.mkdtemp())
        path = tmp_dir / "a.txt"
        path.write_text("[General]\nDocument=16-10 - Dryfit - Cliente A.jpeg\n", encoding="utf-8")
        self.assertIsNone(detect_machine_from_logs([str(path)], []))


class SplitDndFilesTests(unittest.TestCase):
    """`split_dnd_files` extrai, sem Tkinter, o parsing do formato de
    `event.data` do tkinterdnd2 (caminhos espaçados, com chaves em volta de
    quem tem espaço no nome) que antes só existia dentro de
    `modules/operacao/ui.py:_split_dnd_files`."""

    def test_plain_paths_without_spaces(self):
        data = "C:/logs/a.txt C:/logs/b.txt"
        self.assertEqual(split_dnd_files(data), ["C:/logs/a.txt", "C:/logs/b.txt"])

    def test_path_with_space_is_wrapped_in_braces(self):
        data = "{C:/Meus Logs/a.txt} C:/logs/b.txt"
        self.assertEqual(split_dnd_files(data), ["C:/Meus Logs/a.txt", "C:/logs/b.txt"])

    def test_single_braced_path_without_trailing_space(self):
        data = "{C:/Meus Logs/a.txt}"
        self.assertEqual(split_dnd_files(data), ["C:/Meus Logs/a.txt"])

    def test_empty_string_returns_empty_list(self):
        self.assertEqual(split_dnd_files(""), [])

    def test_extra_whitespace_between_paths_is_ignored(self):
        data = "  C:/logs/a.txt    C:/logs/b.txt  "
        self.assertEqual(split_dnd_files(data), ["C:/logs/a.txt", "C:/logs/b.txt"])


class ResolveDefaultImportDirTests(unittest.TestCase):
    """`resolve_default_import_dir` extraiu, sem Tkinter, a escolha da pasta
    inicial do diálogo de importar logs (pasta cadastrada na impressora da
    máquina atual, ou a pasta geral de Configurações) que antes só existia
    dentro de `modules/operacao/ui.py:_default_import_dir`."""

    def _printer(self, **kwargs) -> Printer:
        defaults = dict(key="m1", name="M1", display_name="M1")
        defaults.update(kwargs)
        return Printer(**defaults)

    def test_machine_with_registered_log_dir_wins(self):
        printers = [self._printer(log_import_dir="C:/Logs/M1")]
        result = resolve_default_import_dir("M1", {"general_log_dir": "C:/Logs/Geral"}, printers)
        self.assertEqual(result, "C:/Logs/M1")

    def test_machine_without_registered_log_dir_falls_back_to_general(self):
        printers = [self._printer(log_import_dir="")]
        result = resolve_default_import_dir("M1", {"general_log_dir": "C:/Logs/Geral"}, printers)
        self.assertEqual(result, "C:/Logs/Geral")

    def test_no_machine_uses_general_log_dir(self):
        result = resolve_default_import_dir(None, {"general_log_dir": "C:/Logs/Geral"}, [])
        self.assertEqual(result, "C:/Logs/Geral")

    def test_no_machine_and_no_general_dir_returns_none(self):
        self.assertIsNone(resolve_default_import_dir(None, {}, []))

    def test_unregistered_machine_falls_back_to_general(self):
        result = resolve_default_import_dir("M9", {"general_log_dir": "C:/Logs/Geral"}, [])
        self.assertEqual(result, "C:/Logs/Geral")


class FindCrossRollDuplicatesTests(unittest.TestCase):
    """`find_cross_roll_duplicates` extraiu, sem Tkinter, a montagem dos
    pares (pedido, tecido) a conferir contra outros rolos e a chamada ao
    banco (core.printlogs_db.find_pedido_fabric_rolls) que antes só existia
    dentro de `modules/operacao/ui.py:_find_cross_roll_duplicates`."""

    def _job(self, *, pedido="Cliente A", fabric="DRYFIT", tipo="", is_gap=False) -> Job:
        return Job(
            end_time=datetime(2026, 10, 30, 10, 0, 0),
            document="doc.jpeg",
            fabric=fabric,
            pedido=pedido,
            height_mm=1000.0,
            vpos_mm=0.0,
            real_mm=1000.0,
            src_file="C:/logs/doc.jpeg.txt",
            is_gap=is_gap,
            tipo=tipo,
        )

    def test_queries_distinct_pedido_fabric_pairs_excluding_gaps(self):
        jobs = [
            self._job(pedido="A", fabric="DRYFIT"),
            self._job(pedido="A", fabric="DRYFIT"),
            self._job(is_gap=True),
        ]
        captured = {}

        def fake_find(pairs, *, exclude_roll_id):
            captured["pairs"] = pairs
            captured["exclude_roll_id"] = exclude_roll_id
            return {}

        with patch("modules.operacao.parser.find_pedido_fabric_rolls", fake_find):
            find_cross_roll_duplicates(jobs, {}, exclude_roll_id=42)
        self.assertEqual(captured["pairs"], {("A", "DRYFIT")})
        self.assertEqual(captured["exclude_roll_id"], 42)

    def test_type_configured_to_not_warn_is_excluded_from_pairs(self):
        mcfg = {"print_type_rules": [{"name": "Reposição", "pattern": "x", "warn_duplicate": False}]}
        jobs = [self._job(pedido="A", fabric="DRYFIT", tipo="Reposição")]
        captured = {}

        def fake_find(pairs, *, exclude_roll_id):
            captured["pairs"] = pairs
            return {}

        with patch("modules.operacao.parser.find_pedido_fabric_rolls", fake_find):
            find_cross_roll_duplicates(jobs, mcfg)
        self.assertEqual(captured["pairs"], set())

    def test_db_exception_returns_empty_dict(self):
        def fake_find(pairs, *, exclude_roll_id):
            raise RuntimeError("db down")

        with patch("modules.operacao.parser.find_pedido_fabric_rolls", fake_find):
            result = find_cross_roll_duplicates([self._job()], {})
        self.assertEqual(result, {})

    def test_successful_match_is_returned(self):
        expected = {("A", "DRYFIT"): [{"roll_name": "Rolo 1", "machine": "M1", "created_at": None}]}

        def fake_find(pairs, *, exclude_roll_id):
            return expected

        with patch("modules.operacao.parser.find_pedido_fabric_rolls", fake_find):
            result = find_cross_roll_duplicates([self._job(pedido="A", fabric="DRYFIT")], {})
        self.assertEqual(result, expected)


class ClassifyReimportedJobsTests(unittest.TestCase):
    """`classify_reimported_jobs` — parte do item de roadmap (Fase 2)
    "importação incremental e idempotente": compara jobs recém-parseados
    contra o histórico já salvo no banco (por `Job.src_file`), separando em
    novo, já importado sem alteração (mesmo `job_hash`) ou alterado desde a
    última importação (mesmo caminho, `job_hash` diferente)."""

    MACHINE = "M1"

    def _job(self, *, document="doc.jpeg", height_mm=1000.0, src_file="C:/logs/doc.jpeg.txt") -> Job:
        return Job(
            end_time=datetime(2026, 11, 16, 10, 0, 0),
            document=document,
            fabric="DRYFIT",
            pedido="Cliente A",
            height_mm=height_mm,
            vpos_mm=0.0,
            real_mm=height_mm,
            src_file=src_file,
        )

    def _record_for(self, job: Job, *, height_mm=None) -> dict:
        return {
            "job_hash": make_job_hash(
                self.MACHINE, job.end_time.isoformat(timespec="seconds"), job.document,
                job.height_mm if height_mm is None else height_mm,
            ),
            "roll_name": "Rolo Anterior",
            "created_at": "2026-11-15T09:00:00",
        }

    def test_job_with_no_history_entry_is_new(self):
        job = self._job()
        result = classify_reimported_jobs([job], self.MACHINE, {})
        self.assertEqual(result.new, [job])
        self.assertEqual(result.already_imported, [])
        self.assertEqual(result.changed, [])

    def test_job_with_matching_hash_is_already_imported(self):
        job = self._job()
        record = self._record_for(job)
        result = classify_reimported_jobs([job], self.MACHINE, {job.src_file: record})
        self.assertEqual(result.already_imported, [(job, record)])
        self.assertEqual(result.new, [])
        self.assertEqual(result.changed, [])

    def test_job_with_different_height_than_recorded_is_changed(self):
        job = self._job(height_mm=1000.0)
        record = self._record_for(job, height_mm=900.0)  # valor registrado na importação anterior
        result = classify_reimported_jobs([job], self.MACHINE, {job.src_file: record})
        self.assertEqual(result.changed, [(job, record)])
        self.assertEqual(result.new, [])
        self.assertEqual(result.already_imported, [])

    def test_mixed_jobs_are_split_into_the_three_groups(self):
        new_job = self._job(document="novo.jpeg", src_file="C:/logs/novo.jpeg.txt")
        same_job = self._job(document="igual.jpeg", src_file="C:/logs/igual.jpeg.txt")
        changed_job = self._job(document="mudou.jpeg", src_file="C:/logs/mudou.jpeg.txt", height_mm=1000.0)

        same_record = self._record_for(same_job)
        changed_record = self._record_for(changed_job, height_mm=500.0)

        result = classify_reimported_jobs(
            [new_job, same_job, changed_job],
            self.MACHINE,
            {same_job.src_file: same_record, changed_job.src_file: changed_record},
        )
        self.assertEqual(result.new, [new_job])
        self.assertEqual(result.already_imported, [(same_job, same_record)])
        self.assertEqual(result.changed, [(changed_job, changed_record)])


class CheckReimportedJobsTests(unittest.TestCase):
    """`check_reimported_jobs` — igual a `find_cross_roll_duplicates`: busca
    o histórico no banco de verdade e nunca propaga erro; sem conseguir
    consultar, trata tudo como novo (mesmo comportamento de antes desta
    verificação existir)."""

    def _job(self, src_file="C:/logs/doc.jpeg.txt") -> Job:
        return Job(
            end_time=datetime(2026, 11, 16, 10, 0, 0), document="doc.jpeg", fabric="DRYFIT",
            pedido="Cliente A", height_mm=1000.0, vpos_mm=0.0, real_mm=1000.0, src_file=src_file,
        )

    def test_queries_by_src_file_and_classifies_using_the_result(self):
        job = self._job()
        record = {
            "job_hash": make_job_hash("M1", job.end_time.isoformat(timespec="seconds"), job.document, job.height_mm),
            "roll_name": "Rolo 1",
            "created_at": "2026-11-15T09:00:00",
        }
        captured = {}

        def fake_find(paths):
            captured["paths"] = list(paths)
            return {job.src_file: record}

        with patch("modules.operacao.parser.find_orders_by_source_path", fake_find):
            result = check_reimported_jobs([job], "M1")
        self.assertEqual(captured["paths"], [job.src_file])
        self.assertEqual(result.already_imported, [(job, record)])

    def test_db_exception_treats_everything_as_new(self):
        job = self._job()

        def fake_find(paths):
            raise RuntimeError("db down")

        with patch("modules.operacao.parser.find_orders_by_source_path", fake_find):
            result = check_reimported_jobs([job], "M1")
        self.assertEqual(result.new, [job])
        self.assertEqual(result.already_imported, [])
        self.assertEqual(result.changed, [])


class FormatReimportWarningTests(unittest.TestCase):
    """`format_reimport_warning` só monta aviso para itens alterados desde a
    última importação — "já importado sem alteração" nunca aparece aqui,
    porque não é um alerta (ver `ReimportCheck`/`check_reimported_jobs`)."""

    def _job(self) -> Job:
        return Job(
            end_time=datetime(2026, 11, 16, 10, 0, 0), document="doc.jpeg", fabric="DRYFIT",
            pedido="Cliente A", height_mm=1000.0, vpos_mm=0.0, real_mm=1000.0,
            src_file="C:/logs/doc.jpeg.txt",
        )

    def test_no_changed_entries_returns_empty_string(self):
        from modules.operacao.parser import ReimportCheck

        check = ReimportCheck(already_imported=[(self._job(), {"roll_name": "Rolo 1"})])
        self.assertEqual(format_reimport_warning(check), "")

    def test_changed_entry_mentions_document_roll_and_date(self):
        from modules.operacao.parser import ReimportCheck

        job = self._job()
        record = {"roll_name": "Rolo 1", "created_at": "2026-11-15T09:30:00"}
        check = ReimportCheck(changed=[(job, record)])
        msg = format_reimport_warning(check)
        self.assertIn("doc.jpeg", msg)
        self.assertIn("Rolo 1", msg)
        self.assertIn("2026-11-15 09:30", msg)


class ResolveMirrorTargetCmTests(unittest.TestCase):
    """`resolve_mirror_target_cm` extraiu, sem Tkinter, a validação da
    largura do espelho JPG (17/21 cm fixos, ou personalizada entre 8 e
    40 cm) que antes só existia dentro de
    `modules/operacao/ui.py:_get_mirror_target_cm`."""

    def test_mode_17_returns_17(self):
        self.assertEqual(resolve_mirror_target_cm("17", ""), 17.0)

    def test_mode_21_returns_21(self):
        self.assertEqual(resolve_mirror_target_cm("21", ""), 21.0)

    def test_custom_value_with_comma_decimal(self):
        self.assertEqual(resolve_mirror_target_cm("custom", "15,5"), 15.5)

    def test_custom_value_below_minimum_raises(self):
        with self.assertRaises(ValueError):
            resolve_mirror_target_cm("custom", "5")

    def test_custom_value_above_maximum_raises(self):
        with self.assertRaises(ValueError):
            resolve_mirror_target_cm("custom", "45")

    def test_custom_value_non_numeric_raises(self):
        with self.assertRaises(ValueError):
            resolve_mirror_target_cm("custom", "abc")


class ResolveMirrorJpgPathTests(unittest.TestCase):
    """`resolve_mirror_jpg_path` extraiu, sem Tkinter, a escolha da
    pasta/nome do espelho JPG (pasta fixa cadastrada na impressora, com
    nome de arquivo fixo opcional, ou a pasta padrão do rolo) que antes só
    existia dentro de `modules/operacao/ui.py:_resolve_mirror_jpg_path`."""

    def _printer(self, **kwargs) -> Printer:
        defaults = dict(key="m1", name="M1", display_name="M1")
        defaults.update(kwargs)
        return Printer(**defaults)

    def test_no_printer_registered_falls_back_to_default_dir(self):
        tmp_dir = Path(tempfile.mkdtemp())
        out_jpg_dir = tmp_dir / "rolo"
        result = resolve_mirror_jpg_path("M1", out_jpg_dir, "base", [])
        self.assertEqual(result, out_jpg_dir / "base.jpg")

    def test_printer_without_jpg_output_dir_falls_back_to_default_dir(self):
        tmp_dir = Path(tempfile.mkdtemp())
        out_jpg_dir = tmp_dir / "rolo"
        printers = [self._printer(jpg_output_dir="")]
        result = resolve_mirror_jpg_path("M1", out_jpg_dir, "base", printers)
        self.assertEqual(result, out_jpg_dir / "base.jpg")

    def test_printer_with_jpg_output_dir_and_no_fixed_filename_uses_versioned_base_name(self):
        tmp_dir = Path(tempfile.mkdtemp())
        mirror_dir = tmp_dir / "espelho"
        printers = [self._printer(jpg_output_dir=str(mirror_dir))]
        result = resolve_mirror_jpg_path("M1", tmp_dir / "rolo", "base", printers)
        self.assertEqual(result, mirror_dir / "base.jpg")
        self.assertTrue(mirror_dir.is_dir())

    def test_printer_with_fixed_filename_without_extension_appends_jpg(self):
        tmp_dir = Path(tempfile.mkdtemp())
        mirror_dir = tmp_dir / "espelho"
        printers = [self._printer(jpg_output_dir=str(mirror_dir), jpg_output_filename="saida")]
        result = resolve_mirror_jpg_path("M1", tmp_dir / "rolo", "base", printers)
        self.assertEqual(result, mirror_dir / "saida.jpg")

    def test_printer_with_fixed_filename_already_having_extension_is_kept(self):
        tmp_dir = Path(tempfile.mkdtemp())
        mirror_dir = tmp_dir / "espelho"
        printers = [self._printer(jpg_output_dir=str(mirror_dir), jpg_output_filename="saida.jpeg")]
        result = resolve_mirror_jpg_path("M1", tmp_dir / "rolo", "base", printers)
        self.assertEqual(result, mirror_dir / "saida.jpeg")


class CanonicalizeFabricNameTests(unittest.TestCase):
    """`canonicalize_fabric_name` extraiu, sem Tkinter, a canonicalização de
    tecido digitado à mão em "Editar tecido" que antes só existia dentro de
    `modules/operacao/ui.py:_canonicalize_fabric_name` — casa com o cadastro
    compartilhado (core/fabrics.py) ou cadastra um nome novo lá."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.store_path = Path(self._tmp_dir.name) / "fabrics.json"
        self._patcher = patch("core.fabrics._fabrics_store_path", return_value=self.store_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def test_matches_existing_alias_regardless_of_case_and_spacing(self):
        self.assertEqual(canonicalize_fabric_name("dry fit"), "DRYFIT")

    def test_unregistered_name_gets_registered_and_returned_uppercase(self):
        canonical = canonicalize_fabric_name("Tecido Novo XPTO")
        self.assertEqual(canonical, "TECIDO NOVO XPTO")

    def test_registering_same_name_twice_does_not_duplicate_entry(self):
        from core.fabrics import load_fabrics

        canonicalize_fabric_name("Tecido Novo XPTO")
        before = len(load_fabrics())
        canonicalize_fabric_name("tecido novo xpto")
        self.assertEqual(len(load_fabrics()), before)

    def test_strips_surrounding_whitespace_before_matching(self):
        self.assertEqual(canonicalize_fabric_name("  dryfit  "), "DRYFIT")


class FormatDuplicateMessageTests(unittest.TestCase):
    """`format_duplicate_message` extraiu, sem Tkinter, a montagem da
    mensagem de aviso de duplicidade (pedido + tecido já impresso em outro
    rolo) que antes só existia dentro de
    `modules/operacao/ui.py:_format_duplicate_message`."""

    def test_empty_matches_returns_empty_string(self):
        self.assertEqual(format_duplicate_message({}), "")

    def test_single_match_formats_roll_name_machine_and_date(self):
        matches = {
            ("Pedido A", "DRYFIT"): [
                {"roll_name": "Rolo 1", "machine": "M1", "created_at": "2026-11-16T10:30:00"}
            ]
        }
        msg = format_duplicate_message(matches)
        self.assertEqual(
            msg,
            '- Pedido "Pedido A" + Tecido "DRYFIT" já impresso em: Rolo 1 (M1, 2026-11-16 10:30)',
        )

    def test_multiple_rolls_for_same_pair_are_joined_with_comma(self):
        matches = {
            ("Pedido A", "DRYFIT"): [
                {"roll_name": "Rolo 1", "machine": "M1", "created_at": "2026-11-16T10:30:00"},
                {"roll_name": "Rolo 2", "machine": "M2", "created_at": "2026-11-17T09:00:00"},
            ]
        }
        msg = format_duplicate_message(matches)
        self.assertEqual(
            msg,
            '- Pedido "Pedido A" + Tecido "DRYFIT" já impresso em: Rolo 1 (M1, 2026-11-16 10:30), Rolo 2 (M2, 2026-11-17 09:00)',
        )

    def test_missing_created_at_does_not_raise(self):
        matches = {("Pedido A", "DRYFIT"): [{"roll_name": "Rolo 1", "machine": "M1", "created_at": None}]}
        msg = format_duplicate_message(matches)
        self.assertEqual(msg, '- Pedido "Pedido A" + Tecido "DRYFIT" já impresso em: Rolo 1 (M1, )')

    def test_multiple_pairs_produce_one_line_each(self):
        matches = {
            ("Pedido A", "DRYFIT"): [{"roll_name": "Rolo 1", "machine": "M1", "created_at": "2026-11-16T10:30:00"}],
            ("Pedido B", "RIBANA"): [{"roll_name": "Rolo 2", "machine": "M2", "created_at": "2026-11-17T09:00:00"}],
        }
        msg = format_duplicate_message(matches)
        self.assertEqual(len(msg.splitlines()), 2)


if __name__ == "__main__":
    unittest.main()

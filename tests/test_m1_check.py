"""Testes da verificação de impressão real da M1 (modules/operacao/m1_check.py)."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from modules.operacao import m1_check


def _write_daily_log(folder: Path, day: datetime, lines: list[str], *, subdir: str = "main") -> Path:
    target_dir = folder / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"Log[{day:%Y_%m_%d}].txt"
    path.write_text("\n".join(lines), encoding="gb18030")
    return path


def _job_lines(job_id: str, *, queued: str, size: str, final: str, width="2.68", height="999.91", error="0"):
    return [
        f"[软件][调试][{queued}][000000] 作业【~section0.prn】打印完成.作业ID: {job_id}, 作业状态 :10",
        f"[软件][调试][{size}][000000] 作业ID:{job_id}, 图像大小 : {width}mm X {height}mm",
        f"[软件][调试][{final}][000000] 作业打印完成，发送打印结果到RIP，作业状态:1, 作业名称:~section0.prn, "
        f"作业ID:{job_id}, 错误码:{error}, 总次数:1, 被调用次数:1",
    ]


class M1CheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        m1_check.clear_cache()
        self.addCleanup(m1_check.clear_cache)

    def test_positive_job_id_matches(self):
        day = datetime(2026, 11, 11)
        lines = _job_lines("716966140", queued="07:20:47", size="07:21:29", final="07:21:30")
        _write_daily_log(self.folder, day, lines)

        res = m1_check.check_job(folder=str(self.folder), end_time=datetime(2026, 11, 11, 7, 10, 0))
        self.assertEqual(res.status, m1_check.STATUS_OK)

    def test_negative_job_id_matches(self):
        """Regressão: o contador de lote da M1 pode ficar negativo (visto em
        produção real em 2026-11-11) — as regexes antigas só aceitavam
        dígitos sem sinal e perdiam 100% desses lotes, mesmo com o arquivo do
        dia certo presente."""
        day = datetime(2026, 11, 11)
        lines = _job_lines("-716966140", queued="07:20:47", size="07:21:29", final="07:21:30")
        _write_daily_log(self.folder, day, lines)

        res = m1_check.check_job(folder=str(self.folder), end_time=datetime(2026, 11, 11, 7, 10, 0))
        self.assertEqual(res.status, m1_check.STATUS_OK)

    def test_negative_job_id_error_code_reported(self):
        day = datetime(2026, 11, 11)
        lines = _job_lines("-716966140", queued="07:20:47", size="07:21:29", final="07:21:30", error="-1")
        _write_daily_log(self.folder, day, lines)

        res = m1_check.check_job(folder=str(self.folder), end_time=datetime(2026, 11, 11, 7, 10, 0))
        self.assertEqual(res.status, m1_check.STATUS_ERROR)

    def test_queued_status_100_is_not_mistaken_for_10(self):
        """Achado de revisão de código: a regex de fila não tinha fronteira
        depois do "10", então um código de status "100" batia por
        coincidência de prefixo como se fosse "10" (fila) — essa linha não
        deve ser reconhecida como um "QUEUED" válido."""
        day = datetime(2026, 11, 11)
        line = "[软件][调试][07:20:47][000000] 作业【~section0.prn】打印完成.作业ID: 5, 作业状态 :100"
        _write_daily_log(self.folder, day, [line])

        jobs, recognized = m1_check.parse_daily_log(
            self.folder / "main" / f"Log[{day:%Y_%m_%d}].txt"
        )
        self.assertEqual(recognized, 0)
        self.assertEqual(jobs, [])

    def test_cld_dash_filename_variant(self):
        day = datetime(2026, 11, 11)
        lines = _job_lines("-5", queued="07:20:47", size="07:21:29", final="07:21:30")
        _write_daily_log(self.folder, day, lines, subdir="cld")
        # cld não é indexado automaticamente como "main" — simula a pasta
        # apontando direto pra "cld".
        res = m1_check.check_job(
            folder=str(self.folder / "cld"), end_time=datetime(2026, 11, 11, 7, 10, 0)
        )
        self.assertEqual(res.status, m1_check.STATUS_OK)

    def test_not_configured(self):
        res = m1_check.check_job(folder="", end_time=datetime(2026, 11, 11, 7, 10, 0))
        self.assertEqual(res.status, m1_check.STATUS_NOT_CONFIGURED)

    def test_no_daily_file_for_day(self):
        res = m1_check.check_job(folder=str(self.folder), end_time=datetime(2026, 11, 11, 7, 10, 0))
        self.assertEqual(res.status, m1_check.STATUS_NOT_FOUND)

    def test_no_batch_sent_after_end_time(self):
        day = datetime(2026, 11, 11)
        lines = _job_lines("-1", queued="07:20:47", size="07:21:29", final="07:21:30")
        _write_daily_log(self.folder, day, lines)

        res = m1_check.check_job(folder=str(self.folder), end_time=datetime(2026, 11, 11, 23, 0, 0))
        self.assertEqual(res.status, m1_check.STATUS_NOT_FOUND)

    def test_unknown_format_warns_when_file_has_content(self):
        day = datetime(2026, 11, 11)
        path = self.folder / "main"
        path.mkdir(parents=True, exist_ok=True)
        (path / f"Log[{day:%Y_%m_%d}].txt").write_text("x" * 3000, encoding="gb18030")

        res = m1_check.check_job(folder=str(self.folder), end_time=datetime(2026, 11, 11, 7, 10, 0))
        self.assertEqual(res.status, m1_check.STATUS_UNKNOWN_FORMAT)

    def test_batch_crossing_midnight_is_found_on_next_day(self):
        day = datetime(2026, 11, 11)
        next_day = datetime(2026, 11, 12)
        lines = _job_lines("-9", queued="23:58:00", size="23:58:10", final="00:05:00")
        _write_daily_log(self.folder, next_day, lines)

        res = m1_check.check_job(folder=str(self.folder), end_time=datetime(2026, 11, 11, 23, 57, 0))
        self.assertEqual(res.status, m1_check.STATUS_OK)


class ExtractSpeedSamplesTests(unittest.TestCase):
    """"Detectar velocidade de log(s)" (Nexor.py) pedido do usuário pra
    também aceitar o log diário físico (M1/JetPrime), não só o log
    por-arquivo (Mimaki) — ver modules/operacao/m1_check.py."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_completed_batch_without_error_is_a_sample(self):
        day = datetime(2026, 11, 18)
        lines = _job_lines("1", queued="07:00:00", size="07:00:05", final="07:12:00", height="1000.00")
        path = _write_daily_log(self.folder, day, lines)

        samples, recognized = m1_check.extract_speed_samples(path)
        self.assertEqual(recognized, 3)
        self.assertEqual(len(samples), 1)
        label, length_m, elapsed_min = samples[0]
        self.assertIn("1", label)
        self.assertAlmostEqual(length_m, 1.0)
        self.assertAlmostEqual(elapsed_min, 12.0)

    def test_batch_with_error_is_not_a_sample(self):
        day = datetime(2026, 11, 18)
        lines = _job_lines("2", queued="07:00:00", size="07:00:05", final="07:12:00", error="-1")
        path = _write_daily_log(self.folder, day, lines)

        samples, recognized = m1_check.extract_speed_samples(path)
        self.assertGreater(recognized, 0)
        self.assertEqual(samples, [])

    def test_batch_without_image_size_is_not_a_sample(self):
        day = datetime(2026, 11, 18)
        lines = [
            "[软件][调试][07:00:00][000000] 作业【~section0.prn】打印完成.作业ID: 3, 作业状态 :10",
            "[软件][调试][07:12:00][000000] 作业打印完成，发送打印结果到RIP，作业状态:1, 作业名称:~section0.prn, "
            "作业ID:3, 错误码:0, 总次数:1, 被调用次数:1",
        ]
        path = _write_daily_log(self.folder, day, lines)

        samples, recognized = m1_check.extract_speed_samples(path)
        self.assertGreater(recognized, 0)
        self.assertEqual(samples, [])

    def test_multiple_completed_batches_each_become_a_sample(self):
        day = datetime(2026, 11, 18)
        lines = _job_lines("10", queued="07:00:00", size="07:00:05", final="07:10:00", height="500.00")
        lines += _job_lines("11", queued="08:00:00", size="08:00:05", final="08:20:00", height="2000.00")
        path = _write_daily_log(self.folder, day, lines)

        samples, _recognized = m1_check.extract_speed_samples(path)
        self.assertEqual(len(samples), 2)
        lengths = sorted(length_m for _label, length_m, _elapsed in samples)
        self.assertEqual(lengths, [0.5, 2.0])

    def test_unrecognized_format_returns_no_samples(self):
        path = self.folder / "nao-e-log-diario.txt"
        path.write_text("conteúdo qualquer, não é log da JetPrime", encoding="utf-8")

        samples, recognized = m1_check.extract_speed_samples(path)
        self.assertEqual(recognized, 0)
        self.assertEqual(samples, [])


if __name__ == "__main__":
    unittest.main()

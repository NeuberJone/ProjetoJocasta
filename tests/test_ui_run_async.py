"""Testes de core.ui.run_async — helper introduzido na Etapa E do recurso
de identificação de vendedor (ver core/order_files.py, core/order_pdfs.py)
pra nunca travar o Tkinter durante indexação/miniaturas (regra obrigatória
"Não bloquear a interface..."). Usa um widget falso (sem display real,
sem necessidade de um ambiente gráfico pros testes) cujo `after` só
confirma que o callback chega sempre através dele, nunca direto da thread
de trabalho."""
import threading
import time
import tkinter as tk
import unittest

from core.ui import run_async


class _FakeWidget:
    """`after(ms, cb)` chama `cb` na hora, mas registra de qual thread a
    chamada partiu — é exatamente essa thread que run_async deve manter
    igual à que criou o widget (nunca a thread de trabalho tocando o
    widget direto)."""
    def __init__(self):
        self.after_calls = 0
        self.after_thread = None

    def after(self, _ms, callback):
        self.after_calls += 1
        self.after_thread = threading.current_thread()
        callback()


class _WidgetDestroyedBeforeScheduling:
    """Simula a janela já fechada quando a thread de trabalho termina:
    `after()` em si falha, como o Tkinter faz num widget destruído."""
    def after(self, _ms, _callback):
        raise tk.TclError("invalid command name (widget destruído)")


class _WidgetDestroyedDuringCallback:
    """`after()` ainda funciona (a janela existia ao agendar), mas o
    callback entregue falha ao tentar atualizar um botão/variável que foi
    destruído entre o agendamento e a execução."""
    def after(self, _ms, callback):
        callback()


class RunAsyncTests(unittest.TestCase):
    def test_on_done_runs_through_after_with_the_result(self):
        widget = _FakeWidget()
        done = threading.Event()
        received = {}

        def work():
            return 42

        def on_done(result):
            received["value"] = result
            received["thread"] = threading.current_thread()
            done.set()

        run_async(widget, work, on_done)
        self.assertTrue(done.wait(timeout=2))
        self.assertEqual(received["value"], 42)
        self.assertEqual(widget.after_calls, 1)

    def test_work_runs_off_the_calling_thread(self):
        widget = _FakeWidget()
        done = threading.Event()
        work_thread = {}

        def work():
            work_thread["thread"] = threading.current_thread()
            return None

        def on_done(_result):
            done.set()

        calling_thread = threading.current_thread()
        run_async(widget, work, on_done)
        self.assertTrue(done.wait(timeout=2))
        self.assertNotEqual(work_thread["thread"], calling_thread)

    def test_exception_in_work_is_routed_to_on_error_not_raised(self):
        widget = _FakeWidget()
        done = threading.Event()
        received = {}

        def work():
            raise ValueError("falhou de propósito")

        def on_error(exc):
            received["exc"] = exc
            done.set()

        run_async(widget, work, on_done=None, on_error=on_error)
        self.assertTrue(done.wait(timeout=2))
        self.assertIsInstance(received["exc"], ValueError)

    def test_exception_without_on_error_does_not_crash_the_thread(self):
        widget = _FakeWidget()

        def work():
            raise RuntimeError("sem handler")

        run_async(widget, work)
        time.sleep(0.2)
        self.assertEqual(widget.after_calls, 0)

    def test_on_done_not_called_when_work_raises(self):
        widget = _FakeWidget()
        done = threading.Event()

        def work():
            raise RuntimeError("boom")

        def on_done(_result):
            done.set()

        def on_error(_exc):
            done.set()

        run_async(widget, work, on_done=on_done, on_error=on_error)
        self.assertTrue(done.wait(timeout=2))
        self.assertEqual(widget.after_calls, 1)  # só o on_error, nunca o on_done

    def _capture_thread_exceptions(self):
        """`threading.excepthook` é o único jeito de ver, do thread principal
        (o do teste), se a thread de trabalho de `run_async` deixou escapar
        uma exceção não tratada — por padrão o Python só imprime isso no
        stderr, nunca falha o teste por conta própria."""
        captured = []
        original = threading.excepthook

        def hook(args):
            captured.append(args.exc_value)

        threading.excepthook = hook
        self.addCleanup(lambda: setattr(threading, "excepthook", original))
        return captured

    def test_destroyed_widget_fails_to_schedule_without_crashing_the_thread(self):
        """Achado de revisão de código: fechar a janela enquanto a thread
        de trabalho ainda roda não deve derrubar a thread nem propagar um
        TclError pra fora — só registra e segue (não há mais ninguém
        esperando o resultado). Sem o `try/except` em `_deliver`, esse
        TclError escapava sem tratamento da thread de trabalho."""
        captured = self._capture_thread_exceptions()
        widget = _WidgetDestroyedBeforeScheduling()
        done = threading.Event()

        def work():
            done.set()
            return 42

        run_async(widget, work, on_done=lambda _r: None)
        self.assertTrue(done.wait(timeout=2))
        time.sleep(0.2)  # dá tempo pro after() (que levanta TclError) ser alcançado
        self.assertEqual(captured, [])

    def test_destroyed_widget_fails_during_callback_without_crashing_the_thread(self):
        """Mesma garantia, mas com a janela destruída DEPOIS do agendamento
        — o próprio callback (ex.: `_set_busy` tocando um botão morto)
        levanta TclError ao ser executado. Sem o `try/except` em
        `_run_callback`, esse TclError escapava sem tratamento."""
        captured = self._capture_thread_exceptions()
        widget = _WidgetDestroyedDuringCallback()
        done = threading.Event()

        def work():
            return 42

        def on_done(_result):
            done.set()
            raise tk.TclError("invalid command name (botão destruído)")

        run_async(widget, work, on_done=on_done)
        self.assertTrue(done.wait(timeout=2))
        time.sleep(0.2)
        self.assertEqual(captured, [])


if __name__ == "__main__":
    unittest.main()

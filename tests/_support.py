import sys
import types


def ensure_dependency_stubs() -> None:
    """Install lightweight runtime stubs for optional dependencies in test env."""
    if "rich" not in sys.modules:
        rich_mod = types.ModuleType("rich")

        console_mod = types.ModuleType("rich.console")

        class Console:
            def __init__(self, *args, **kwargs):
                pass

            def print(self, *args, **kwargs):
                return None

        console_mod.Console = Console

        panel_mod = types.ModuleType("rich.panel")

        class Panel:
            def __init__(self, *args, **kwargs):
                pass

            @staticmethod
            def fit(*args, **kwargs):
                return ""

        panel_mod.Panel = Panel

        progress_mod = types.ModuleType("rich.progress")
        table_mod = types.ModuleType("rich.table")

        class Progress:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def add_task(self, *args, **kwargs):
                return 1

            def update(self, *args, **kwargs):
                return None

        class SpinnerColumn:
            def __init__(self, *args, **kwargs):
                pass

        class TextColumn:
            def __init__(self, *args, **kwargs):
                pass

        progress_mod.Progress = Progress
        progress_mod.SpinnerColumn = SpinnerColumn
        progress_mod.TextColumn = TextColumn

        class Table:
            def __init__(self, *args, **kwargs):
                pass

            def add_column(self, *args, **kwargs):
                return None

            def add_row(self, *args, **kwargs):
                return None

        table_mod.Table = Table

        rich_mod.console = console_mod
        rich_mod.panel = panel_mod
        rich_mod.progress = progress_mod
        rich_mod.table = table_mod

        sys.modules["rich"] = rich_mod
        sys.modules["rich.console"] = console_mod
        sys.modules["rich.panel"] = panel_mod
        sys.modules["rich.progress"] = progress_mod
        sys.modules["rich.table"] = table_mod

    if "loguru" not in sys.modules:
        loguru_mod = types.ModuleType("loguru")

        class _DummyLogger:
            def __getattr__(self, _name):
                def _noop(*args, **kwargs):
                    return None
                return _noop

        loguru_mod.logger = _DummyLogger()
        sys.modules["loguru"] = loguru_mod

    if "dotenv" not in sys.modules:
        dotenv_mod = types.ModuleType("dotenv")

        def load_dotenv(*args, **kwargs):
            return None

        dotenv_mod.load_dotenv = load_dotenv
        sys.modules["dotenv"] = dotenv_mod

"""Debug-Steuerung für das Hauptfenster: Start (Python/C/C++/Rust), Zustandsanzeige (Aktionen, Statusleiste), gelbe Ausführungszeile,
Haltepunkt-Abgleich und Aktualisierung der Debug-Fenster."""
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

from ..build.languages import lang_for
from ..build.runner import Runner
from .session import Bp, DebugSession, csharp_spec, go_spec, java_spec, native_spec, node_spec, python_module_spec, python_spec
from .tools import find, missing_message
from ..theme import t


class DebugController(QObject):
    stateChanged = Signal(str)       # idle | starting | running | paused

    def __init__(self, win, panels: dict):
        super().__init__(win)
        self.w = win
        self.locals, self.watch, self.stack, self.immediate = panels["locals"], panels["watch"], panels["stack"], panels["immediate"]
        self.session: DebugSession | None = None
        self.state = "idle"
        self.store: dict[str, list] = {}          # gespeicherte Haltepunkte je Datei: [(Zeile, Bedingung, deaktiviert)]
        self._first_pause = True
        self.pauseInfo = ("", "")
        self._user_stop = False
        self.stack.frameActivated.connect(lambda i: self.session and self.session.select_frame(i))
        self.immediate.submitted.connect(self._immediate)

    # --- Abfragen ---------------------------------------------------------------------------------------
    @property
    def active(self) -> bool:
        return self.session is not None and self.state != "idle"

    # --- Start ----------------------------------------------------------------------------------------------
    def start(self):
        """F5: Ohne Sitzung debuggen, im angehaltenen Zustand fortsetzen."""
        if self.session and self.state == "paused":
            return self.session.resume()
        if self.active:
            return
        w = self.w
        doc = w.docs.current_doc()
        if w.run_project_command("buildrun") or w.run_web(doc):      # Start-Befehl / Web-Formulare: Dev-Server statt Debugger
            return
        file = w.project.startup_path(w.root) or (doc.run_target if doc else None)
        if file is None:
            return w.statusBar().showMessage("Keine Datei zum Debuggen – öffne eine Datei oder lege eine Startdatei fest.", 5000)
        lang = lang_for(file)
        if lang is None:
            return w.statusBar().showMessage("Für diese Datei gibt es keinen Debugger.", 4000)
        w.docs.save_all()
        if doc and doc.kind == "form":
            doc.save()
        w.output.clear(); w.errors.set_source("build", [])
        w.d_output.show(); w.d_output.raise_()
        self._first_pause = True
        fn = getattr(self, "_start_" + {"c": "native", "cpp": "native", "rust": "native", "javascript": "node", "typescript": "node"}.get(lang.id, lang.id), None)
        if fn is None:
            return w.statusBar().showMessage(f"Debugging für {lang.name} ist noch nicht angebunden.", 6000)
        fn(file, lang)

    def _need(self, tool: str, purpose: str) -> str | None:
        path = find(tool)
        if not path:
            self.w.output.append(missing_message(tool, purpose) + "\n", "stderr")
            self.w.statusBar().showMessage(f"'{tool}' fehlt – siehe Ausgabe.", 6000)
        return path

    def debug_test(self, framework_name: str, ids: list, root: Path):
        """Einzelne Python-Tests unter dem Debugger ausführen (pytest oder unittest)."""
        if self.active:
            return
        w = self.w
        w.docs.save_all()
        w.output.clear()
        w.d_output.show(); w.d_output.raise_()
        self._first_pause = True
        module = "pytest" if framework_name == "pytest" else "unittest"
        args = ["-p", "no:cacheprovider", "-s", *ids] if module == "pytest" else list(ids)
        self._launch(python_module_spec(module, args, root, w.runner.interpreter(root / "x.py")), root / "tests")

    def _opts(self, spec, file: Path):
        """Argumente, Umgebung und Arbeitsordner aus den Projekteinstellungen in die Startparameter übernehmen."""
        kind, factory, launch = spec
        pr, root = self.w.project, self.w.root
        args = pr.arg_list()
        if kind == "csharp":
            launch["args"] = [launch["args"][0]] + args
        else:
            launch["args"] = args
        if pr.env and kind != "native":
            launch["env"] = dict(pr.env)
        launch["cwd"] = str(pr.work_dir(root, file))
        return spec

    def _start_python(self, file, lang):
        self._launch(self._opts(python_spec(file, self.w.runner.interpreter(file)), file), file)

    def _start_native(self, file, lang):
        if not self._need("gdb", "das Debuggen von C/C++/Rust"):
            return
        w = self.w
        binary = w.runner.build_dir / file.stem
        w._after_build = lambda: self._launch(self._opts(native_spec(binary, file.parent), file), file)
        w.runner.start(file, "build", "Debug")        # mit Debug-Symbolen (-g)

    def _start_node(self, file, lang):
        if not self._need("node", "das Debuggen von JavaScript/TypeScript"):
            return
        self._launch(self._opts(node_spec(file, file.parent, typescript=lang.id == "typescript"), file), file)

    def _start_java(self, file, lang):
        if not (self._need("javac", "das Kompilieren von Java") and self._need("jdb", "das Debuggen von Java")):
            return
        import re
        w = self.w
        text = file.read_text(encoding="utf-8", errors="replace")
        pkg = re.search(r"^\s*package\s+([\w.]+)\s*;", text, re.M)
        src_root = file.parent
        if pkg:
            for _ in pkg.group(1).split("."):
                src_root = src_root.parent
        main_class = (pkg.group(1) + "." if pkg else "") + file.stem
        out = w.runner.build_dir / "java"
        out.mkdir(parents=True, exist_ok=True)
        sources = [str(p) for p in sorted(src_root.rglob("*.java")) if ".vds" not in p.parts]
        w._after_build = lambda: self._launch(self._opts(java_spec(main_class, out, src_root, file.parent), file), file)
        w.runner.start_command(["javac", "-g", "-d", str(out)] + sources, src_root)

    def _start_go(self, file, lang):
        dlv = self._need("dlv", "das Debuggen von Go")
        if not dlv or not self._need("go", "das Debuggen von Go"):
            return
        mod = any((p / "go.mod").exists() for p in [file.parent, *file.parents][:5])
        self._launch(self._opts(go_spec(file.parent if mod else file, file.parent, dlv), file), file)

    def _start_csharp(self, file, lang):
        proj = Runner._csproj(file)
        if proj is None:
            return self.w.statusBar().showMessage("C#-Debugging braucht ein Projekt (.csproj) – lege eines über Datei → Neu → Projekt an.", 8000)
        dbg = self._need("netcoredbg", "das Debuggen von C#")
        if not dbg or not self._need("dotnet", "das Debuggen von C#"):
            return
        import re
        w = self.w

        def launch():
            text = proj.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"<AssemblyName>([^<]+)</AssemblyName>", text)
            name = m.group(1) if m else proj.stem
            dlls = sorted((proj.parent / "bin" / "Debug").glob(f"*/{name}.dll"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not dlls:
                return w.output.append(f"Gebaute Datei {name}.dll nicht gefunden (bin/Debug).\n", "stderr")
            self._launch(self._opts(csharp_spec(dlls[0], proj.parent, dbg), file), file)
        w._after_build = launch
        w.runner.start_command(["dotnet", "build", str(proj), "-c", "Debug"], proj.parent)

    def _launch(self, spec, file: Path):
        s = DebugSession(self)
        self.session = s
        s.output.connect(self.w.output.append)
        s.stateChanged.connect(self._on_state)
        s.framesChanged.connect(self._on_frames)
        s.paused.connect(self._on_paused)
        s.ended.connect(self._on_ended)
        self.w.output.append(f"Debugging gestartet: {file.name}\n", "info")
        s.start(spec, file.parent, self._collect())

    # --- Steuerung ---------------------------------------------------------------------------------------------
    def resume(self): self.session and self.session.resume()
    def pause(self): self.session and self.session.pause()
    def step_over(self): self.session and self.session.step_over()
    def step_in(self): self.session and self.session.step_in()
    def step_out(self): self.session and self.session.step_out()

    def stop(self):
        if self.session:
            self._user_stop = True
            self.session.stop()

    def restart(self):
        if self.session:
            s = self.session
            s.ended.connect(lambda _c: self.start())
            s.stop()

    def write_stdin(self, text: str) -> bool:
        if self.session and self.active:
            self.session.write_stdin(text)
            return True
        return False

    # --- Zustand --------------------------------------------------------------------------------------------------
    def _set_state(self, st):
        self.state = st
        self.stateChanged.emit(st)

    def _on_state(self, st):
        if st == "paused":
            return                      # wird erst nach dem Laden der Aufrufliste (_on_paused) gemeldet – dann mit Grund
        if st in ("starting", "running"):
            self._clear_exec()
            self.locals.grey_out(); self.watch.grey_out()
        self._set_state(st)

    def _on_frames(self, frames, sel):
        self.stack.show_frames(frames, sel)
        if not frames:
            return
        f = frames[sel]
        self._clear_exec()
        if f.path and Path(f.path).is_file():
            doc = self.w.docs.open(Path(f.path))
            if doc and doc.editor:
                doc.editor.set_exec_line(f.line)
                doc.editor.goto(f.line)
        self.locals.refresh(self.session)
        self.watch.refresh(self.session)

    def _on_paused(self, reason, text):
        w = self.w
        if reason == "exception":
            w.output.append(f"\n⚠ Nicht behandelte Ausnahme: {text}\n", "stderr")
        if self._first_pause:
            self._first_pause = False
            w.d_locals.show(); w.d_locals.raise_()
        self.pauseInfo = (reason, text)
        self._set_state("paused")          # löst Statusleisten-Update mit Grund aus

    def _on_ended(self, code):
        self._clear_exec()
        self.locals.reset_state(); self.watch.grey_out(); self.stack.clear()
        if self._user_stop:
            self.w.output.append("\nDebugsitzung beendet.\n", "info")
        else:
            self.w.output.append(f"\nDebugsitzung beendet (Exit-Code {code}).\n", "ok" if code == 0 else "info")
        self._user_stop = False
        self.session = None
        self._set_state("idle")

    def _clear_exec(self):
        for d in self.w.docs.docs.values():
            if d.kind == "code":
                d.view.set_exec_line(None)

    def _immediate(self, expr):
        s = self.session
        if not s or s.state != "paused":
            return self.immediate.line("(nur im angehaltenen Zustand möglich)", QColor(t("#ffc474")))
        s.evaluate(expr, lambda ok, result, typ, ref: self.immediate.line(result if ok else f"Fehler: {result}", QColor(t("#dbe6ff")) if ok else QColor(t("#ff4d6d"))), "repl")

    def datatip(self, expr: str, cb):
        """Wert eines Ausdrucks beim Überfahren im Editor (nur im angehaltenen Zustand)."""
        s = self.session
        if not s or s.state != "paused":
            return cb(None)
        import html
        s.evaluate(expr, lambda ok, res, typ, ref: cb(
            t(f"<b>{html.escape(expr)}</b> = <span style='color:#ffc474'>{html.escape(res)}</span>"
              + (f" <span style='color:#8fa3c7'>({html.escape(typ)})</span>" if typ else "")) if ok else None), "hover")

    # --- Haltepunkte -----------------------------------------------------------------------------------------------
    def _collect(self) -> dict:
        """Aktive Haltepunkte aller offenen Editoren plus gespeicherte Dateien, die nicht offen sind."""
        out: dict[str, list] = {}
        open_paths = set()
        for d in self.w.docs.docs.values():
            if d.kind == "code":
                open_paths.add(str(d.path))
                bl = d.editor.breakpoint_list()
                if bl:
                    out[str(d.path)] = [Bp(l, c) for l, c in bl]
        for path, items in self.store.items():
            if path not in open_paths:
                bl = [Bp(l, c) for l, c, off in items if not off]
                if bl:
                    out[path] = bl
        return out

    def breakpoints_changed(self):
        """Wird bei jeder Änderung an Haltepunkten gerufen: Speicher aktualisieren und laufende Sitzung informieren."""
        for d in self.w.docs.docs.values():
            if d.kind != "code":
                continue
            ed, key = d.editor, str(d.path)
            if ed.breakpoints:
                self.store[key] = sorted((n, ed.bp_conditions.get(n, ""), n in ed.bp_disabled) for n in ed.breakpoints)
            else:
                self.store.pop(key, None)
        if self.session and self.active:
            now = self._collect()
            for path in set(now) | set(self.session.bps):
                if [(b.line, b.condition) for b in now.get(path, [])] != [(b.line, b.condition) for b in self.session.bps.get(path, [])]:
                    self.session.set_breakpoints(path, now.get(path, []))

    def toggle_here(self):
        d = self.w.docs.current_doc()
        if d and d.kind == "code":
            d.editor.toggle_breakpoint(d.editor.textCursor().blockNumber() + 1)

    def clear_all(self):
        for d in self.w.docs.docs.values():
            if d.kind == "code" and d.editor.breakpoints:
                d.editor.breakpoints.clear(); d.editor.bp_conditions.clear(); d.editor.bp_disabled.clear(); d.editor._bp_changed()
        self.store.clear()

    # --- Speicherung (QSettings) ----------------------------------------------------------------------------------------
    def save(self, settings, key: str):
        self.breakpoints_changed()
        settings.setValue(key, [f"{p}\t{l}\t{c}\t{int(off)}" for p, items in self.store.items() for l, c, off in items])

    def load(self, settings, key: str):
        raw = settings.value(key) or []
        raw = [raw] if isinstance(raw, str) else list(raw)
        self.store = {}
        for r in raw:
            try:
                p, l, c, off = r.split("\t")
                self.store.setdefault(p, []).append((int(l), c, off == "1"))
            except ValueError:
                pass

    def apply_saved(self, doc):
        """Gespeicherte Haltepunkte in einen frisch geöffneten Editor eintragen."""
        items = self.store.get(str(doc.path))
        if doc.kind == "code" and items and not doc.editor.breakpoints:
            for l, c, off in items:
                doc.editor.set_breakpoint_state(l, c, off)
